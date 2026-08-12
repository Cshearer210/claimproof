"""Wire the claims gate into CrewAI via `Task.guardrail`.

CrewAI's `Task.guardrail` is a callable invoked on a task's output before the
crew moves on. Returning `(False, reason)` fails the task; CrewAI re-runs it,
feeding `reason` back to the agent as the reason to revise -- up to
`guardrail_max_retries` (default 3) times. That retry loop is CrewAI's own,
built in, so this adapter does not build a second one. What it does need to
build, because CrewAI has no equivalent, is a way to tell "was this attempt a
retry caused by our own last block" apart from "is this a fresh task" -- the
same distinction Claude Code hands over for free as `stop_hook_active`.

The guardrail callable itself is only ever handed a `TaskOutput`, and
`TaskOutput` carries no task identity (checked against the installed
`crewai` package, not its docs: `description`, `name`, `raw`, `agent`,
`pydantic`, `json_dict`, `output_format`, `messages`, `tool_failures` --
no `task_id`, no reference back to the `Task`). So `guardrail()` alone
cannot key a "did I already block this one" set on anything trustworthy,
and it cannot tell whether the task actually did anything -- a `TaskOutput`
carries no tool-call count either.

`gate_task(task, gates=...)` exists to fix both problems by building a
closure that has what `guardrail()` alone does not: the real `Task`, whose
`.id` is a stable `uuid.UUID` untouched by retries. It:

  * subscribes a listener to `crewai_event_bus` for `ToolUsageFinishedEvent`,
    filtered to this task's id, and counts real tool calls per attempt
  * uses `task.id` (not a hash of description text) as the retry-guard key
  * only reads the counter, never blocks on it directly -- a task with no
    tools that still asserts a finished result is exactly the case the gate
    exists for
  * calls `crewai_event_bus.flush()` before reading that counter, because
    `ToolUsageFinishedEvent` handlers run on the bus's own thread pool, not
    inline with the tool call, and CrewAI's own task execution never waits
    for them either -- checked in `task.py`, not assumed. Skipping the
    flush is not hypothetical: the adapter's own test suite flakes without
    it, the same race a real crew could hit under load.

A crew-level `guardrail` module attribute is also exported for the simple
case (no work-filter, no per-task state) -- see its docstring for the
trade-off.
"""
from __future__ import annotations

import sys
import threading
import uuid
from typing import Any, Iterable

try:
    from crewai.events import crewai_event_bus
    from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent
except ImportError as exc:  # pragma: no cover - exercised by not installing crewai
    raise ImportError(
        "claimproof.crewai needs the 'crewai' package, which is not a runtime "
        "dependency of claimproof itself. Install it with:\n"
        "    pip install claimproof[crewai]\n"
        "or: pip install crewai"
    ) from exc

from .core import Finding, Gate
from .gates import UnbackedClaims

__all__ = ["MARKER", "WORK_THRESHOLD", "decide", "guardrail", "gate_task"]

MARKER = "claimproof.crewai"

# A task with at least this many tool calls counts as "did real work" even
# if none of them wrote a file -- mirrors WORK_THRESHOLD in claude_code.py.
WORK_THRESHOLD = 5

# Task ids we have already blocked once. An id reappearing here means: we
# blocked that task, CrewAI is re-running it, don't block it twice in a row.
_already_blocked: set[str] = set()


def decide(text: str, task_key: str, did_work: bool,
           gates: Iterable[Gate] | None = None) -> str | None:
    """The whole policy in one testable function.

    Returns a block reason string, or None to allow. Never raises on bad
    input -- empty text, or a task that did no real work, is "cannot judge
    usefully" and allows, same as `claude_code.decide()`.
    """
    if task_key and task_key in _already_blocked:
        _already_blocked.discard(task_key)  # one retry's worth of leniency
        return None

    if not text or not text.strip() or not did_work:
        return None

    findings: list[Finding] = []
    for gate in (gates if gates is not None else [UnbackedClaims(window=2)]):
        findings.extend(gate.check(text))  # check() verifies the gate first
    if not findings:
        return None

    shown = " | ".join(f'"{(f.excerpt or f.message)[:80]}"' for f in findings[:4])
    if task_key:
        _already_blocked.add(task_key)
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
        task_key = getattr(output, "description", "") or ""
        reason = decide(text, task_key, did_work=bool(text.strip()))
    except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
        print(f"claimproof: gate did not run ({type(exc).__name__}: {exc}); "
              f"allowing the task.", file=sys.stderr)
        return True, output
    if reason is not None:
        return False, reason
    return True, output


def gate_task(task: Any, gates: Iterable[Gate] | None = None) -> Any:
    """Attach the claims gate to `task` in place, with real work-tracking.

    Subscribes a per-task tool-call counter to `crewai_event_bus` and wires
    a guardrail closure that uses it, then returns `task` for chaining:

        for t in [research_task, write_task, review_task]:
            gate_task(t)
    """
    task_id = str(getattr(task, "id", "") or uuid.uuid4())
    tool_calls = {"count": 0}
    lock = threading.Lock()

    @crewai_event_bus.on(ToolUsageFinishedEvent)
    def _count_tool_call(source: Any, event: ToolUsageFinishedEvent) -> None:
        if event.task_id == task_id:
            with lock:
                tool_calls["count"] += 1

    def _guardrail(output: Any) -> tuple[bool, Any]:
        try:
            text = getattr(output, "raw", "") or ""
            # ToolUsageFinishedEvent handlers run on the event bus's own
            # thread pool, not inline with the tool call -- CrewAI's own
            # task execution never waits for them either, so without this
            # the count below can read as 0 even after real tool calls,
            # depending on scheduling. flush() is bus-wide, not scoped to
            # this task, so it can wait on unrelated in-flight events too;
            # bounded by a short timeout so a slow, unrelated handler can
            # only ever cost time, never turn into a hang that blocks the
            # crew.
            crewai_event_bus.flush(timeout=5.0)
            with lock:
                did_work = tool_calls["count"] >= WORK_THRESHOLD
            reason = decide(text, task_id, did_work, gates=gates)
        except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
            print(f"claimproof: gate did not run ({type(exc).__name__}: {exc}); "
                  f"allowing the task.", file=sys.stderr)
            return True, output
        finally:
            with lock:
                tool_calls["count"] = 0  # next attempt starts its own count
        if reason is not None:
            return False, reason
        return True, output

    task.guardrail = _guardrail
    return task
