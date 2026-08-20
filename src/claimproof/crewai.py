"""Wire the claims gate into CrewAI via `Task.guardrail`.

CrewAI's `Task.guardrail` is a callable invoked on a task's output before the
crew moves on. Returning `(False, reason)` fails the task; CrewAI re-runs the
agent with `reason` as context and calls the guardrail again -- up to
`guardrail_max_retries` (default 3) times, then raises. Checked directly in
`crewai/task.py`'s `_invoke_guardrail_function`, not assumed from docs: the
failure branch genuinely calls `agent.execute_task(...)` again, and the loop
is hard-bounded by CrewAI itself (`max_attempts = guardrail_max_retries + 1`;
past that it raises instead of calling the guardrail again).

That bound is exactly why this adapter carries no loop-guard of its own.
Claude Code's Stop hook needs one -- claimproof's `claude_code.py` uses
`stop_hook_active` to avoid blocking a retry twice in a row -- because
nothing on that side caps how many times a blocked turn can be revised and
re-submitted; without a guard, a stuck agent and a strict gate can loop
forever. In the crewai version this adapter supports (see the version note
below), that loop is bounded: the same unbacked claim, re-blocked on
every retry, terminates in `guardrail_max_retries` steps either because the
agent produces real evidence or because CrewAI gives up and raises. Adding
a second, adapter-side "allow the next attempt for free" on top of that
would only make the gate weaker -- one specific retry would go unchecked
for no reason tied to CrewAI's own semantics -- while doing nothing to
prevent a loop that already cannot happen. So `decide()` here is a pure
function: same text and same amount of real work always gets the same
verdict, no matter which attempt it is.

The guardrail callable itself is only ever handed a `TaskOutput`. In the
crewai version tested here (see the version note below), `TaskOutput`
carries no task identity -- checked against the installed `crewai` package,
not its docs: `description`, `name`, `raw`, `agent`, `pydantic`,
`json_dict`, `output_format`, `messages`, `tool_failures`, no `task_id`, no
reference back to the `Task`. That is a statement about the runtime this
adapter was tested against, not a permanent claim about CrewAI's API --
a future release could add one. So `guardrail()` alone cannot tell whether
the task actually did anything -- a `TaskOutput` carries no tool-call count
either.

`gate_task(task, gates=..., work_threshold=..., event_flush_timeout=...)`
exists to fix that by building a closure that has what `guardrail()` alone
does not: the real `Task`. It:

  * subscribes a listener to `crewai_event_bus` for `ToolUsageFinishedEvent`,
    filtered to this task's `id`, and counts real tool calls per attempt.
    `work_threshold` (default `WORK_THRESHOLD`) is a count of tool calls,
    not a judgment of importance -- one call that edits a production
    database and nine that read a file are both "1", and a task with four
    harmless searches is treated the same as one with zero. This is a
    deliberately blunt, cheap-to-compute proxy for "did something", not a
    risk assessment; callers who need better resolution (e.g. only counting
    writes, or gating on the first tool call regardless of count) should
    filter `ToolUsageFinishedEvent` themselves rather than trust this number
    to mean more than it does
  * calls `crewai_event_bus.flush(timeout=event_flush_timeout)` before
    reading that counter, because `ToolUsageFinishedEvent` handlers run on
    the bus's own thread pool, not inline with the tool call, and CrewAI's
    own task execution never waits for them either -- checked in `task.py`,
    not assumed. Skipping the flush is not hypothetical: the adapter's own
    test suite flakes without it, the same race a real crew could hit under
    load. The default (5s) is a guess at "long enough to not flake, short
    enough to not stall a crew"; `flush()` is bus-wide, so it can end up
    waiting on unrelated in-flight events too -- tune it if that cost shows
    up in your own crew. A timed-out flush is treated as "cannot trust this
    count", not just "cannot judge this claim": the task is allowed and the
    listener is unsubscribed, on the reasoning that a bus backed up enough
    to miss a 5s deadline isn't a state worth staying subscribed through.
    The counter itself is reset to 0 right after being read, on the
    assumption that the read happens at a clean boundary between attempts
    -- true here because `task.py`'s `_execute_core`/`_aexecute_core` calls
    `agent.execute_task(...)` and waits for it to fully return *before*
    invoking `self._guardrail`, so no tool call belonging to a next attempt
    can begin, let alone emit an event, until this guardrail call has
    already returned control to CrewAI. That sequencing is what makes the
    reset boundary safe without keying counts by `task.retry_count`
    instead; it does not hold for a hypothetical caller that invokes the
    same closure concurrently from outside CrewAI's own call sequence.
  * unsubscribes both listeners -- the tool-call counter and a
    `TaskFailedEvent` safety net -- when the task is allowed, when the
    final configured guardrail attempt is reached, when the guardrail
    itself fails, or when CrewAI reports the task failed outright. That
    last case is the one the other three can't cover on their own: an
    abnormal abort between one guardrail call and the next (the agent
    crashing for a reason unrelated to our verdict) means no further
    guardrail call, and no other chance to unsubscribe, ever comes. Left
    subscribed forever, a long-running process gating many tasks over time
    accumulates one live listener per task ever gated, each still paying
    to inspect every future tool-call event process-wide even though its
    task finished retries ago.

A crew-level `guardrail` module attribute is exported for the simple case
(no work-filter, no listener, no per-task state) -- see its docstring for
the trade-off.

Version note: written and tested against crewai 1.15.14 only. The fields and
methods this relies on (`Task.retry_count`, `Task.guardrail_max_retries`,
`ToolUsageFinishedEvent.task_id`, `crewai_event_bus.flush`/`.off`) were
confirmed present there by reading the installed source, not by checking
when each was introduced or whether they're considered stable/public by
CrewAI. `pyproject.toml` pins a narrow range around the tested version
rather than an open `>=` floor, on purpose -- CrewAI's own internals move
quickly, and a broad compatibility promise here would be a guess dressed up
as a fact. Widening it is a "someone tested it and it still holds" change,
not a default.
"""
from __future__ import annotations

import sys
import threading
from typing import Any, Iterable

from .core import Finding, Gate
from .gates import UnbackedClaims


def _crewai_events():
    """Import crewai's event-bus pieces lazily, on first actual use.

    Not at module import time: `claimproof`'s own test suite discovers every
    `Gate` the package ships by walking `pkgutil.iter_modules(claimproof.__path__)`
    and unconditionally `importlib.import_module()`-ing each one -- see
    `tests/test_core.py`'s `_shipped_gates()`. `crewai` is an optional extra,
    not a runtime dependency of claimproof itself, so `import claimproof.crewai`
    has to succeed even when `crewai` isn't installed; only calling `guardrail()`
    or `gate_task()` should require it. A module-level import here would make
    that discovery walk crash on this file specifically -- confirmed by running
    it, not assumed: `claude_code.py` never surfaces this, because it has no
    external dependency to be missing in the first place.
    """
    try:
        from crewai.events import crewai_event_bus
        from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent
        from crewai.events.types.task_events import TaskFailedEvent
    except ImportError as exc:
        raise ImportError(
            "claimproof.crewai needs the 'crewai' package, which is not a runtime "
            "dependency of claimproof itself. Install it with:\n"
            "    pip install claimproof[crewai]\n"
            "or: pip install crewai"
        ) from exc
    return crewai_event_bus, ToolUsageFinishedEvent, TaskFailedEvent


__all__ = ["MARKER", "WORK_THRESHOLD", "decide", "guardrail", "gate_task"]

MARKER = "claimproof.crewai"

# Minimum number of completed tool calls before the claims gate runs. This
# is a heuristic, not a determination that the task did meaningful work: a
# single call that edits a production database sits below this default just
# like four harmless searches would. Override per call for a stricter
# policy, e.g. `gate_task(task, work_threshold=1)` to gate on any tool use
# at all -- or `work_threshold=0` to gate every nonempty output regardless
# of tool use, since 0 tool calls already satisfies `count >= 0`. Mirrors
# WORK_THRESHOLD's role in claude_code.py, though the two aren't measuring
# the same thing (that one also counts file writes).
WORK_THRESHOLD = 5


def decide(text: str, did_work: bool,
           gates: Iterable[Gate] | None = None) -> str | None:
    """The whole policy in one pure, testable function.

    Returns a block reason string, or None to allow. No hidden state: the
    same `(text, did_work)` always gets the same verdict, on any attempt --
    see the module docstring for why that is safe under CrewAI's own
    bounded retry loop. Never raises on bad input -- empty text, or a task
    that did no real work, is "cannot judge usefully" and allows.
    """
    if not text or not text.strip() or not did_work:
        return None

    findings: list[Finding] = []
    for gate in (gates if gates is not None else [UnbackedClaims(window=2)]):
        findings.extend(gate.check(text))  # check() verifies the gate first
    if not findings:
        return None

    shown = " | ".join(f'"{(f.excerpt or f.message)[:80]}"' for f in findings[:4])
    return (
        "completion claim(s) with no evidence in this task's output: " + shown +
        ". Show the proof (command output, exit code, test result, or file "
        "and snippet) for each, or soften the claim. A dry run proves "
        "wiring, not correctness."
    )


def guardrail(output: Any) -> tuple[bool, Any]:
    """Drop-in value for `Task(..., guardrail=claimproof.crewai.guardrail)`.

    The simple case: no per-task tool-call tracking, so `did_work` is
    approximated as "the output is non-empty" rather than counted -- use
    `gate_task()` instead when you want the real WORK_THRESHOLD filter.
    Fails open, out loud: any error inspecting the output allows the task
    and prints why to stderr, rather than blocking (or silently passing)
    on a claimproof bug.
    """
    try:
        text = getattr(output, "raw", "") or ""
        reason = decide(text, did_work=bool(text.strip()))
    except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
        print(f"claimproof: guardrail failed open ({type(exc).__name__}: "
              f"{exc}); allowing the task.", file=sys.stderr)
        return True, output
    if reason is not None:
        return False, reason
    return True, output


def gate_task(task: Any, gates: Iterable[Gate] | None = None,
              work_threshold: int = WORK_THRESHOLD,
              event_flush_timeout: float | None = 5.0) -> Any:
    """Attach the claims gate to `task` in place, with real work-tracking.

    Subscribes a per-task tool-call counter to `crewai_event_bus` and wires
    a guardrail closure that uses it. Unsubscribes both listeners exactly
    once -- on an allow, on the final configured guardrail attempt, on a
    guardrail failure, or on `TaskFailedEvent` (an abnormal abort between
    guardrail calls, e.g. the agent crashing for an unrelated reason after
    a block, which none of the other three cases catches). Returns `task`
    for chaining:

        for t in [research_task, write_task, review_task]:
            gate_task(t)

    Requires a real `Task`: `task.id` is CrewAI's own field, a
    `uuid.UUID` with `default_factory=uuid.uuid4` -- every genuine `Task`
    has one, so this raises rather than silently degrading into a tracker
    that can never match anything, which a same-looking-but-wrong fallback
    would do quietly.

    Sets both `task.guardrail` and `task._guardrail`. CrewAI's own task
    execution reads the private `_guardrail`, not the public field --
    confirmed in `task.py`, not assumed: `if self._guardrail: ... 
    guardrail=self._guardrail`. `_guardrail` only gets populated from
    `guardrail` by a `@model_validator(mode="after")`, which Pydantic runs
    at construction time (or on `.model_validate()`/`.model_copy()`), not on
    a plain attribute assignment after the fact -- `Task.model_config` has
    no `validate_assignment=True` to make it re-run. Setting only
    `task.guardrail` after construction, as an earlier version of this
    adapter did, leaves `_guardrail` at its original `None` and the gate
    silently never runs in a real crew, while every test that calls
    `task.guardrail(output)` directly still passes -- the public field
    holds the right closure, just not the one CrewAI actually invokes.

    Raises if called twice on the same task: a second call would register a
    second pair of listeners and replace `task.guardrail`/`task._guardrail`,
    orphaning the first pair -- nothing left referencing them would ever
    call their `_unsubscribe`, a real leak on the success path
    specifically. Call it once per task.
    """
    if getattr(task, "_claimproof_gated", False):
        raise ValueError(
            "gate_task() was already called on this task. Calling it again "
            "would leak the first pair of event listeners. Call it once."
        )
    if work_threshold < 0:
        raise ValueError("work_threshold must be >= 0")
    if event_flush_timeout is not None and event_flush_timeout < 0:
        raise ValueError("event_flush_timeout must be >= 0 (or None to wait indefinitely)")

    real_id = getattr(task, "id", None)
    if real_id is None:
        raise ValueError(
            "gate_task() needs task.id (a real crewai.Task field) to match "
            "tool-call events to this task. Got an object with no .id -- "
            "pass an actual crewai.Task, not a stand-in."
        )
    crewai_event_bus, ToolUsageFinishedEvent, TaskFailedEvent = _crewai_events()
    task_id = str(real_id)
    tool_calls = {"count": 0}
    lock = threading.Lock()
    unsubscribed = {"done": False}
    unsubscribe_lock = threading.Lock()

    @crewai_event_bus.on(ToolUsageFinishedEvent)
    def _count_tool_call(source: Any, event: ToolUsageFinishedEvent) -> None:
        if event.task_id == task_id:
            with lock:
                tool_calls["count"] += 1

    def _unsubscribe() -> None:
        # Idempotent on purpose: several call sites can each reach this
        # (allow, final retry, guardrail failure, TaskFailedEvent), and a
        # repeated crewai_event_bus.off() is harmless but the flag makes
        # the intent explicit -- exactly one cleanup per gated task.
        with unsubscribe_lock:
            if unsubscribed["done"]:
                return
            unsubscribed["done"] = True
        crewai_event_bus.off(ToolUsageFinishedEvent, _count_tool_call)
        crewai_event_bus.off(TaskFailedEvent, _on_task_failed)

    @crewai_event_bus.on(TaskFailedEvent)
    def _on_task_failed(source: Any, event: TaskFailedEvent) -> None:
        # Safety net for the case _guardrail() itself can't cover: CrewAI
        # aborting the task for a reason unrelated to our verdict (e.g. the
        # agent crashing) between one guardrail call and the next, so no
        # further guardrail call -- and no other chance to unsubscribe --
        # ever comes. `is task` is checked first as a cheap common-case
        # match; the `.id` comparison is kept alongside it deliberately,
        # not as leftover complexity, in case some path ever hands the
        # event a copy or re-wrapped reference to the same logical task
        # rather than the exact object -- id equality still catches that,
        # identity alone would not.
        failed_task = getattr(event, "task", None)
        if failed_task is task or getattr(failed_task, "id", None) == real_id:
            _unsubscribe()

    def _is_final_attempt() -> bool:
        retry_count = getattr(task, "retry_count", None)
        max_retries = getattr(task, "guardrail_max_retries", None)
        if retry_count is None or max_retries is None:
            return False  # can't tell; err toward keeping the listener
        return retry_count >= max_retries

    def _guardrail(output: Any) -> tuple[bool, Any]:
        try:
            text = getattr(output, "raw", "") or ""
        except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
            print(f"claimproof: guardrail failed open ({type(exc).__name__}: "
                  f"{exc}); allowing the task.", file=sys.stderr)
            _unsubscribe()
            return True, output

        # See the module docstring for why this flush is not optional.
        # flush() returns False, not an exception, if it times out -- and
        # any handler still running past that point keeps running in the
        # background and can increment tool_calls["count"] after this
        # function has already moved on. Kept in its own try/except and
        # deliberately outside the try/finally below: a timed-out flush
        # means the count cannot be trusted at all for this attempt, so
        # there is nothing to "reset to a clean boundary" -- the state is
        # abandoned, not zeroed, and no finally block should imply
        # otherwise by running here.
        try:
            flushed = crewai_event_bus.flush(timeout=event_flush_timeout)
        except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
            print(f"claimproof: guardrail failed open ({type(exc).__name__}: "
                  f"{exc}); allowing the task.", file=sys.stderr)
            _unsubscribe()
            return True, output
        if not flushed:
            print("claimproof: event bus flush timed out; tool-call count "
                  "for this attempt is not trustworthy, allowing the task.",
                  file=sys.stderr)
            _unsubscribe()
            return True, output

        # From here on the count is trusted, so this is a genuine clean
        # boundary between attempts -- the finally reset means what it says.
        try:
            with lock:
                did_work = tool_calls["count"] >= work_threshold
            reason = decide(text, did_work, gates=gates)
        except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
            print(f"claimproof: guardrail failed open ({type(exc).__name__}: "
                  f"{exc}); allowing the task.", file=sys.stderr)
            _unsubscribe()
            return True, output
        finally:
            with lock:
                tool_calls["count"] = 0  # next attempt starts its own count

        if reason is None:
            _unsubscribe()
            return True, output
        if _is_final_attempt():
            _unsubscribe()
        return False, reason

    # CrewAI's runtime executes the private normalized callable
    # (`Task._guardrail`), not the public field -- see the docstring above.
    # Because this closure is installed after Task construction, Pydantic's
    # `ensure_guardrail_is_callable` validator will not run again to
    # populate it, so both must be set explicitly.
    task.guardrail = _guardrail
    task._guardrail = _guardrail
    task._claimproof_gated = True
    return task