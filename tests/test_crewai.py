"""The CrewAI guardrail adapter, tested against the real crewai package.

Skips cleanly (not an error) when `crewai` is not installed -- it is an
optional extra, not a runtime dependency of claimproof itself. Install it
with `pip install claimproof[crewai]` to run these.
"""
import threading
from dataclasses import dataclass
from datetime import datetime

import pytest

crewai_pkg = pytest.importorskip("crewai")

from crewai import Task
from crewai.events import crewai_event_bus
from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent
from crewai.events.types.task_events import TaskFailedEvent

from claimproof.crewai import WORK_THRESHOLD, decide, gate_task, guardrail


@dataclass
class FakeTaskOutput:
    """Stands in for `crewai.tasks.task_output.TaskOutput`: `guardrail()`
    only ever reads `.raw` off it.
    """
    raw: str


def fire_tool_calls(task: Task, count: int) -> None:
    for _ in range(count):
        crewai_event_bus.emit(task, ToolUsageFinishedEvent(
            agent_key="a", tool_name="t", tool_args={}, task_id=str(task.id),
            started_at=datetime.now(), finished_at=datetime.now(), output="x",
        ))
    crewai_event_bus.flush(timeout=5.0)  # handlers run on the bus's own
    # thread pool, not inline with emit() -- the guardrail flushes for the
    # same reason (see crewai.py's module docstring); without it here the
    # very next guardrail() call in a test can race the counter increment.


def registered_listener_count(event_type=ToolUsageFinishedEvent) -> int:
    # Test-only introspection of CrewAI's own private event-bus registry
    # (_sync_handlers). Coupled to crewai 1.15.14 like everything else this
    # adapter relies on -- not part of claimproof's own supported API.
    handlers = crewai_event_bus._sync_handlers.get(event_type, frozenset())
    return len(handlers)


# --------------------------------------------------------------------- decide
def test_unbacked_claim_with_work_is_blocked():
    reason = decide("Fixed the bug. All tests pass.", did_work=True)
    assert reason is not None and "no evidence" in reason


def test_backed_claim_is_allowed():
    reason = decide("Fixed.\n```\n56 passed in 0.14s\n```", did_work=True)
    assert reason is None


def test_unbacked_claim_without_work_is_never_gated():
    reason = decide("Fixed the bug. All tests pass.", did_work=False)
    assert reason is None


def test_empty_text_allows():
    assert decide("", did_work=True) is None
    assert decide("   ", did_work=True) is None


def test_decide_is_pure_same_input_same_verdict_every_time():
    # No hidden state: calling it three times in a row with an unbacked
    # claim blocks all three -- CrewAI's own retry cap is what prevents
    # this from looping forever in practice, not leniency here.
    text = "Fixed the bug. All tests pass."
    assert decide(text, did_work=True) is not None
    assert decide(text, did_work=True) is not None
    assert decide(text, did_work=True) is not None


# ------------------------------------------------------------------ guardrail
def test_guardrail_blocks_an_unbacked_claim():
    out = FakeTaskOutput(raw="Deployed. Everything works now.")
    ok, result = guardrail(out)
    assert ok is False
    assert "no evidence" in result


def test_guardrail_allows_a_backed_claim():
    out = FakeTaskOutput(raw="Deployed.\nservice healthy, 200 OK")
    ok, result = guardrail(out)
    assert ok is True
    assert result is out


def test_guardrail_allows_empty_output():
    ok, result = guardrail(FakeTaskOutput(raw=""))
    assert ok is True


def test_guardrail_fails_open_on_a_malformed_output(capsys):
    class Hostile:
        @property
        def raw(self):
            raise RuntimeError("boom")

    ok, result = guardrail(Hostile())
    assert ok is True  # allowed, not blocked
    assert "failed open" in capsys.readouterr().err  # announced, not silent


# ------------------------------------------------------------------ gate_task
def test_gate_task_ignores_a_claim_below_work_threshold():
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    fire_tool_calls(t, count=WORK_THRESHOLD - 1)

    out = FakeTaskOutput(raw="Investigated. All fixed now.")
    ok, _ = t.guardrail(out)
    assert ok is True  # not enough tool use to trust "did work"


def test_gate_task_blocks_an_unbacked_claim_at_work_threshold():
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    fire_tool_calls(t, count=WORK_THRESHOLD)

    out = FakeTaskOutput(raw="Investigated. All fixed now.")
    ok, reason = t.guardrail(out)
    assert ok is False
    assert "no evidence" in reason


def test_gate_task_allows_a_backed_claim_at_work_threshold():
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    fire_tool_calls(t, count=WORK_THRESHOLD)

    out = FakeTaskOutput(raw="Investigated.\nRoot cause: stale cache. Log: cache_miss=0 after clear.")
    ok, _ = t.guardrail(out)
    assert ok is True


def test_gate_task_work_threshold_is_configurable():
    t = Task(description="Quick check", expected_output="A summary")
    gate_task(t, work_threshold=2)
    fire_tool_calls(t, count=2)

    out = FakeTaskOutput(raw="Checked it. All fixed now.")
    ok, _ = t.guardrail(out)
    assert ok is False  # 2 calls is enough here, though below the default 5


@pytest.mark.parametrize("call_count,expect_gated", [
    (0, False),
    (1, False),
    (4, False),
    (5, True),  # WORK_THRESHOLD itself
    (6, True),
])
def test_gate_task_work_threshold_boundary(call_count, expect_gated):
    t = Task(description="Boundary check", expected_output="A summary")
    gate_task(t)
    fire_tool_calls(t, count=call_count)

    out = FakeTaskOutput(raw="Checked it. All fixed now.")
    ok, _ = t.guardrail(out)
    assert ok is (not expect_gated)


def test_gate_task_event_flush_timeout_is_configurable():
    # Doesn't test the timeout actually elapsing (that would slow the suite
    # down for no real signal) -- just that the parameter is accepted and
    # threaded through to a real flush() call rather than ignored.
    t = Task(description="x", expected_output="y")
    gate_task(t, event_flush_timeout=0.5)
    fire_tool_calls(t, count=WORK_THRESHOLD)

    out = FakeTaskOutput(raw="Fixed it. All good now.")
    ok, _ = t.guardrail(out)
    assert ok is False


def test_gate_task_re_blocks_an_unbacked_claim_on_every_retry():
    # No adapter-side leniency: a retry that still lacks evidence is judged
    # fresh, same as the first attempt. CrewAI's own guardrail_max_retries
    # is what stops this from looping forever, not anything in this file.
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    out = FakeTaskOutput(raw="Investigated. All fixed now.")

    for _ in range(3):
        fire_tool_calls(t, count=WORK_THRESHOLD)
        ok, _ = t.guardrail(out)
        assert ok is False


def test_gate_task_tool_count_does_not_leak_between_tasks():
    a = Task(description="Task A", expected_output="x")
    b = Task(description="Task B", expected_output="x")
    gate_task(a)
    gate_task(b)

    fire_tool_calls(a, count=WORK_THRESHOLD)  # only A did the work
    out = FakeTaskOutput(raw="Fixed it. All good now.")
    ok_a, _ = a.guardrail(out)
    ok_b, _ = b.guardrail(out)
    assert ok_a is False  # A: enough tool calls, unbacked claim -> blocked
    assert ok_b is True  # B: no tool calls counted for it -> not gated


def test_gate_task_returns_the_task_for_chaining():
    t = Task(description="x", expected_output="y")
    assert gate_task(t) is t


def test_gate_task_populates_crewai_runtime_guardrail():
    # Regression test for a real bug: CrewAI's task execution invokes
    # task._guardrail (a private, Pydantic-populated attribute), not
    # task.guardrail directly -- confirmed in task.py's _execute_core:
    # `if self._guardrail: ... guardrail=self._guardrail`. Setting only
    # the public field after construction (as an earlier version of this
    # adapter did) leaves _guardrail at its original None, and every test
    # that calls task.guardrail(output) directly -- including every other
    # test in this file -- still passes while a real crew run would never
    # invoke the gate at all. This test would have caught that: it checks
    # the private attribute CrewAI actually reads, not the public one.
    t = Task(description="x", expected_output="y")
    gate_task(t)
    assert t._guardrail is t.guardrail
    assert callable(t._guardrail)


def test_gate_task_gate_runs_when_invoked_the_way_crewai_actually_invokes_it():
    # Same regression, from the other direction: call task._guardrail
    # directly, the way CrewAI's real execution path does, instead of
    # task.guardrail -- and confirm the gate's actual behavior (not just
    # that something callable is present) survives that path.
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    fire_tool_calls(t, count=WORK_THRESHOLD)

    out = FakeTaskOutput(raw="Investigated. All fixed now.")
    ok, reason = t._guardrail(out)  # not t.guardrail -- mirrors task.py
    assert ok is False
    assert "no evidence" in reason


# ---------------------------------------------------- listener cleanup / leaks
def test_gate_task_unsubscribes_its_listener_on_allow():
    before_tool = registered_listener_count(ToolUsageFinishedEvent)
    before_fail = registered_listener_count(TaskFailedEvent)
    t = Task(description="x", expected_output="y")
    gate_task(t)
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool + 1
    assert registered_listener_count(TaskFailedEvent) == before_fail + 1

    fire_tool_calls(t, count=WORK_THRESHOLD)
    out = FakeTaskOutput(raw="Done.\nlog: 3 passed, 0 failed.")
    ok, _ = t.guardrail(out)
    assert ok is True
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool  # not leaked
    assert registered_listener_count(TaskFailedEvent) == before_fail  # not leaked


def test_gate_task_unsubscribes_after_the_final_retry_attempt():
    before_tool = registered_listener_count(ToolUsageFinishedEvent)
    t = Task(description="x", expected_output="y", guardrail_max_retries=2)
    gate_task(t)
    out = FakeTaskOutput(raw="Fixed it. All good now.")  # never backed -> always blocked

    # Attempt 0: blocked, more retries remain, listener stays.
    t.retry_count = 0
    fire_tool_calls(t, count=WORK_THRESHOLD)
    ok, _ = t.guardrail(out)
    assert ok is False
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool + 1

    # Attempt 1: still blocked, still not the final attempt (1 < 2), listener
    # stays. Testing this middle attempt explicitly, not just 0 and the
    # final one, is the point: the cleanup condition is retry_count >=
    # guardrail_max_retries, and skipping the boundary in between would
    # leave "does it correctly NOT clean up early" unverified.
    t.retry_count = 1
    fire_tool_calls(t, count=WORK_THRESHOLD)
    ok, _ = t.guardrail(out)
    assert ok is False
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool + 1

    # Attempt 2 == guardrail_max_retries: the final attempt, cleaned up.
    t.retry_count = 2
    fire_tool_calls(t, count=WORK_THRESHOLD)
    ok, _ = t.guardrail(out)
    assert ok is False
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool


def test_gate_task_unsubscribes_on_a_failed_guardrail_run(capsys):
    before = registered_listener_count(ToolUsageFinishedEvent)
    t = Task(description="x", expected_output="y")
    gate_task(t)

    class Hostile:
        @property
        def raw(self):
            raise RuntimeError("boom")

    ok, _ = t.guardrail(Hostile())
    assert ok is True
    assert registered_listener_count(ToolUsageFinishedEvent) == before  # cleaned up even on failure


def test_gate_task_unsubscribes_on_an_abnormal_task_failure():
    # Covers what the other three cleanup paths can't: CrewAI aborting the
    # task for a reason unrelated to our verdict (agent crash, etc.)
    # between one guardrail call and the next, so guardrail is never
    # called again and none of the other unsubscribe paths ever run.
    before_tool = registered_listener_count(ToolUsageFinishedEvent)
    before_fail = registered_listener_count(TaskFailedEvent)
    t = Task(description="x", expected_output="y")
    gate_task(t)
    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool + 1

    crewai_event_bus.emit(t, TaskFailedEvent(task=t, error="agent crashed"))
    crewai_event_bus.flush(timeout=5.0)

    assert registered_listener_count(ToolUsageFinishedEvent) == before_tool
    assert registered_listener_count(TaskFailedEvent) == before_fail


def test_gate_task_task_failed_event_for_a_different_task_does_not_unsubscribe():
    # Locks down the identity filtering in _on_task_failed: the event bus
    # is global, so a failure on an unrelated task must not tear down this
    # task's still-active listeners.
    a = Task(description="Task A", expected_output="x")
    b = Task(description="Task B", expected_output="x")
    gate_task(a)
    before = registered_listener_count(ToolUsageFinishedEvent)

    crewai_event_bus.emit(b, TaskFailedEvent(task=b, error="unrelated crash"))
    crewai_event_bus.flush(timeout=5.0)

    assert registered_listener_count(ToolUsageFinishedEvent) == before  # A's listener remains

    fire_tool_calls(a, count=WORK_THRESHOLD)
    out = FakeTaskOutput(raw="Fixed it. All good now.")
    ok, _ = a.guardrail(out)
    assert ok is False  # A still works correctly after B's unrelated failure


def test_gate_task_rejects_being_installed_twice():
    t = Task(description="x", expected_output="y")
    gate_task(t)
    with pytest.raises(ValueError, match="already"):
        gate_task(t)


def test_gate_task_rejects_negative_work_threshold():
    t = Task(description="x", expected_output="y")
    with pytest.raises(ValueError, match="work_threshold"):
        gate_task(t, work_threshold=-1)


def test_gate_task_rejects_negative_event_flush_timeout():
    t = Task(description="x", expected_output="y")
    with pytest.raises(ValueError, match="event_flush_timeout"):
        gate_task(t, event_flush_timeout=-1)


def test_gate_task_allows_and_unsubscribes_when_flush_times_out(capsys, monkeypatch):
    # A timed-out flush means the tool-call count for this attempt can't be
    # trusted (a handler could still be running and increment it after we
    # read and reset), so this is treated as "cannot judge": allow, and say
    # why on stderr, rather than gate on a possibly-wrong number.
    monkeypatch.setattr(crewai_event_bus, "flush", lambda timeout=None: False)
    before = registered_listener_count(ToolUsageFinishedEvent)
    t = Task(description="x", expected_output="y")
    gate_task(t)

    out = FakeTaskOutput(raw="Fixed it. All good now.")  # would otherwise be blocked
    ok, _ = t.guardrail(out)
    assert ok is True
    assert "flush timed out" in capsys.readouterr().err
    assert registered_listener_count(ToolUsageFinishedEvent) == before  # cleaned up, not left dangling


def test_gate_task_requires_a_real_task_id():
    class NoIdStandIn:
        pass

    with pytest.raises(ValueError, match="task.id"):
        gate_task(NoIdStandIn())


# ---------------------------------------------------- real crewai integration
def test_gate_task_blocks_and_crewai_really_retries_through_a_live_kickoff():
    # Every other test in this file calls task.guardrail(...) or
    # task._guardrail(...) directly. This one instead runs an actual
    # crew.kickoff() with a stub LLM, closing the gap those tests can't:
    # proving CrewAI's real execution path invokes task._guardrail (the
    # exact thing the task._guardrail bugfix above depends on), that a
    # block genuinely triggers CrewAI's own retry (agent re-invoked, a
    # second real LLM call happens, task.retry_count actually increments),
    # and that the crew's final accepted output is the backed claim, not
    # the unbacked one an unblocked run would have kept.
    #
    # work_threshold=0 here on purpose: simulating a real tool call through
    # CrewAI's action-parsing loop is a second, separate integration
    # surface (ReAct-style "Action: ..." text parsing) this test isn't
    # trying to cover -- WORK_THRESHOLD's own boundary behavior is already
    # covered directly above. This test's job is the guardrail/retry wiring
    # itself, which doesn't need a tool call to exercise.
    from crewai.llms.base_llm import BaseLLM
    from crewai import Agent, Crew

    class StubLLM(BaseLLM):
        def __init__(self, **data):
            super().__init__(model="stub-model", **data)
            object.__setattr__(self, "_responses", [
                "Investigated. All fixed now.",  # attempt 1: unbacked -> blocked
                "Investigated.\nRoot cause: stale cache. Log: cache_miss=0 after clear.",
            ])
            object.__setattr__(self, "_call_count", 0)

        def call(self, messages, tools=None, callbacks=None,
                  available_functions=None, from_task=None, from_agent=None,
                  response_model=None):
            i = self._call_count
            object.__setattr__(self, "_call_count", i + 1)
            resp = self._responses[min(i, len(self._responses) - 1)]
            return f"Thought: I now know the final answer\nFinal Answer: {resp}"

        def supports_function_calling(self):
            return False

    agent = Agent(role="Investigator", goal="Find the bug", backstory="x",
                   llm=StubLLM())
    task = Task(description="Investigate", expected_output="A summary",
                agent=agent, guardrail_max_retries=2)
    gate_task(task, work_threshold=0)

    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()

    assert task.retry_count >= 1  # CrewAI's own retry counter actually moved
    assert "Root cause" in result.raw  # accepted the backed retry, not the first


def test_crewai_retry_exhaustion_raises_and_cleans_up_listener():
    # Companion to the test above, for the other end of the retry contract:
    # a claim that NEVER becomes backed, so CrewAI exhausts every retry and
    # raises rather than accepting anything. Pins down the exact lifecycle:
    # the LLM is called guardrail_max_retries + 1 times (one per attempt,
    # 0 through guardrail_max_retries inclusive), task.retry_count reaches
    # guardrail_max_retries, kickoff() raises rather than returning, and --
    # the part none of the other tests confirm through a real run -- the
    # tool-call listener is gone afterward, not left registered because the
    # task ended via an exception instead of a clean allow.
    from crewai.llms.base_llm import BaseLLM
    from crewai import Agent, Crew

    call_count = {"n": 0}

    class AlwaysUnbackedLLM(BaseLLM):
        def __init__(self, **data):
            super().__init__(model="stub-model", **data)

        def call(self, messages, tools=None, callbacks=None,
                  available_functions=None, from_task=None, from_agent=None,
                  response_model=None):
            call_count["n"] += 1
            return ("Thought: I now know the final answer\n"
                    "Final Answer: Investigated. All fixed now.")

        def supports_function_calling(self):
            return False

    before = registered_listener_count(ToolUsageFinishedEvent)
    agent = Agent(role="Investigator", goal="Find the bug", backstory="x",
                   llm=AlwaysUnbackedLLM())
    task = Task(description="Investigate", expected_output="A summary",
                agent=agent, guardrail_max_retries=2)
    gate_task(task, work_threshold=0)

    with pytest.raises(Exception, match="no evidence"):
        Crew(agents=[agent], tasks=[task], verbose=False).kickoff()

    assert call_count["n"] == 3  # attempts 0, 1, 2 -- guardrail_max_retries + 1
    assert task.retry_count == 2  # == guardrail_max_retries, the final attempt
    assert registered_listener_count(ToolUsageFinishedEvent) == before  # not leaked


def test_crewai_really_emits_task_failed_event_on_a_genuine_crash():
    # test_gate_task_unsubscribes_on_an_abnormal_task_failure (above) only
    # proves _on_task_failed cleans up correctly when *something* emits
    # TaskFailedEvent -- it manually constructs and emits one itself, which
    # doesn't prove CrewAI's real execution path actually emits that event
    # on a genuine, unrelated crash. This test closes that gap: an LLM that
    # raises mid-task (nothing to do with claimproof's own verdict), run
    # through a real crew.kickoff(), confirmed to raise, and confirmed to
    # leave no listener behind -- proving the safety net the module
    # docstring describes is triggered by CrewAI itself, not just by a
    # unit test emitting the event it expects to receive.
    from crewai.llms.base_llm import BaseLLM
    from crewai import Agent, Crew

    class CrashingLLM(BaseLLM):
        def __init__(self, **data):
            super().__init__(model="crash-model", **data)

        def call(self, messages, tools=None, callbacks=None,
                  available_functions=None, from_task=None, from_agent=None,
                  response_model=None):
            raise RuntimeError("simulated crash, unrelated to claimproof")

        def supports_function_calling(self):
            return False

    before = registered_listener_count(ToolUsageFinishedEvent)
    agent = Agent(role="Investigator", goal="Find the bug", backstory="x",
                   llm=CrashingLLM())
    task = Task(description="Investigate", expected_output="A summary",
                agent=agent)
    gate_task(task, work_threshold=0)

    with pytest.raises(Exception, match="simulated crash"):
        Crew(agents=[agent], tasks=[task], verbose=False).kickoff()

    assert registered_listener_count(ToolUsageFinishedEvent) == before  # not leaked


# ---------------------------------------------------------- concurrent tasks
def test_gate_task_stays_correct_under_concurrent_tool_calls_and_guardrails():
    # Two tasks, tool-call events interleaved from separate threads (what
    # CrewAI's async_execution=True tasks, or a Flow, can produce), then
    # both guardrails checked. Each must only see its own task's tool calls.
    a = Task(description="Task A", expected_output="x")
    b = Task(description="Task B", expected_output="x")
    gate_task(a)
    gate_task(b)

    def hammer(task: Task, n: int) -> None:
        for _ in range(n):
            crewai_event_bus.emit(task, ToolUsageFinishedEvent(
                agent_key="a", tool_name="t", tool_args={}, task_id=str(task.id),
                started_at=datetime.now(), finished_at=datetime.now(), output="x",
            ))

    threads = [
        threading.Thread(target=hammer, args=(a, WORK_THRESHOLD)),
        threading.Thread(target=hammer, args=(b, WORK_THRESHOLD - 1)),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    crewai_event_bus.flush(timeout=5.0)

    out = FakeTaskOutput(raw="Fixed it. All good now.")
    ok_a, _ = a.guardrail(out)
    ok_b, _ = b.guardrail(out)
    assert ok_a is False  # A: reached the threshold -> gated -> blocked
    assert ok_b is True  # B: one short of the threshold -> not gated
