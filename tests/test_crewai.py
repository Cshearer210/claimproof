"""The CrewAI guardrail adapter, tested against the real crewai package.

Skips cleanly (not an error) when `crewai` is not installed -- it is an
optional extra, not a runtime dependency of claimproof itself. Install it
with `pip install claimproof[crewai]` to run these.
"""
from dataclasses import dataclass
from datetime import datetime

import pytest

crewai_pkg = pytest.importorskip("crewai")

from crewai import Task
from crewai.events import crewai_event_bus
from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent

from claimproof.crewai import WORK_THRESHOLD, decide, gate_task, guardrail


@dataclass
class FakeTaskOutput:
    """Stands in for `crewai.tasks.task_output.TaskOutput`: `guardrail()`
    only ever reads `.raw` and `.description` off it.
    """
    raw: str
    description: str = "a task"


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


# --------------------------------------------------------------------- decide
def test_unbacked_claim_with_work_is_blocked():
    reason = decide("Fixed the bug. All tests pass.", "k1", did_work=True)
    assert reason is not None and "no evidence" in reason


def test_backed_claim_is_allowed():
    reason = decide("Fixed.\n```\n56 passed in 0.14s\n```", "k2", did_work=True)
    assert reason is None


def test_unbacked_claim_without_work_is_never_gated():
    # Same unbacked wording -- but no real work was done, so no gate.
    reason = decide("Fixed the bug. All tests pass.", "k3", did_work=False)
    assert reason is None


def test_empty_text_allows():
    assert decide("", "k4", did_work=True) is None
    assert decide("   ", "k4", did_work=True) is None


def test_loop_guard_the_retry_right_after_a_block_is_allowed():
    text = "Fixed the bug. All tests pass."
    first = decide(text, "k5", did_work=True)
    assert first is not None  # blocked

    second = decide(text, "k5", did_work=True)
    assert second is None  # the retry: not blocked again

    # But a THIRD attempt with the same unbacked claim is a fresh judgment,
    # not another free pass -- the leniency is one retry, not a standing
    # exemption for this task_key.
    third = decide(text, "k5", did_work=True)
    assert third is not None


# ------------------------------------------------------------------ guardrail
def test_guardrail_blocks_an_unbacked_claim():
    out = FakeTaskOutput(raw="Deployed. Everything works now.", description="d1")
    ok, result = guardrail(out)
    assert ok is False
    assert "no evidence" in result


def test_guardrail_allows_a_backed_claim():
    out = FakeTaskOutput(
        raw="Deployed.\nservice healthy, 200 OK", description="d2")
    ok, result = guardrail(out)
    assert ok is True
    assert result is out


def test_guardrail_allows_empty_output():
    ok, result = guardrail(FakeTaskOutput(raw="", description="d3"))
    assert ok is True


def test_guardrail_fails_open_on_a_malformed_output(capsys):
    class Hostile:
        @property
        def raw(self):
            raise RuntimeError("boom")

    ok, result = guardrail(Hostile())
    assert ok is True  # allowed, not blocked
    assert "gate did not run" in capsys.readouterr().err  # announced, not silent


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


def test_gate_task_loop_guard_the_retry_is_allowed_then_a_fresh_block_can_follow():
    t = Task(description="Investigate", expected_output="A summary")
    gate_task(t)
    out = FakeTaskOutput(raw="Investigated. All fixed now.")

    fire_tool_calls(t, count=WORK_THRESHOLD)
    ok1, _ = t.guardrail(out)
    assert ok1 is False  # first attempt: blocked

    fire_tool_calls(t, count=WORK_THRESHOLD)  # the retry also does real work
    ok2, _ = t.guardrail(out)
    assert ok2 is True  # the retry itself: not blocked again

    fire_tool_calls(t, count=WORK_THRESHOLD)
    ok3, _ = t.guardrail(out)
    assert ok3 is False  # still unbacked on the second retry: blocked again


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