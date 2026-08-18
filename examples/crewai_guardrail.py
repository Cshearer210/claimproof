#!/usr/bin/env python3
"""Gate a CrewAI crew's tasks against unbacked completion claims.

`gate_task(task)` attaches the claims gate to a `Task` as its `guardrail`.
A blocked task gets fed the reason and re-run by CrewAI's own retry
mechanism (`guardrail_max_retries`, default 3) -- no separate loop-guard
here, because CrewAI's retry loop is already bounded; see `crewai.py`'s
module docstring for why that makes one unnecessary.

Wire it into your own crew:

    from claimproof.crewai import gate_task

    research = Task(description="...", agent=researcher, expected_output="...")
    gate_task(research)  # in place; research.guardrail is now set

    Crew(agents=[researcher], tasks=[research]).kickoff()

By default, `gate_task()` only gates tasks that made at least `WORK_THRESHOLD` tool calls -- a
deliberately conservative heuristic: tool-call count is used as a proxy for substantive work, not
a judgment of what those calls did, so a task that stayed under the threshold is left alone even if
its claim would otherwise look unbacked. Override it with `gate_task(task, work_threshold=...)`, or
pass `work_threshold=1` to gate on any tool use at all.

Try it without a crew, using a stand-in for what CrewAI hands the guardrail:

    python crewai_guardrail.py
"""
from dataclasses import dataclass

from claimproof.crewai import WORK_THRESHOLD, gate_task
from crewai import Task
from crewai.events import crewai_event_bus
from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent
from datetime import datetime


@dataclass
class FakeTaskOutput:
    """Stands in for `crewai.tasks.task_output.TaskOutput` here so this file
    runs without an LLM key. A real crew produces the real thing; the
    guardrail only ever reads `.raw`.
    """
    raw: str


def fire_tool_calls(task: Task, count: int) -> None:
    """Simulate `count` tool calls finishing during `task`'s execution --
    what a real agent invoking a search/file/shell tool would trigger.
    """
    for _ in range(count):
        crewai_event_bus.emit(task, ToolUsageFinishedEvent(
            agent_key="demo-agent", tool_name="demo_tool", tool_args={},
            task_id=str(task.id), started_at=datetime.now(),
            finished_at=datetime.now(), output="ok",
        ))
    crewai_event_bus.flush(timeout=5.0)


if __name__ == "__main__":
    def new_task() -> Task:
        return gate_task(Task(
            description="Investigate the failing deploy and report the fix.",
            expected_output="A root-cause summary.",
        ))

    unbacked = FakeTaskOutput(raw="Deployed the fix. Everything works now.")

    print(f"-- fewer than WORK_THRESHOLD ({WORK_THRESHOLD}) tool calls --")
    t1 = new_task()
    fire_tool_calls(t1, count=2)
    ok, result = t1.guardrail(unbacked)
    print(f"allowed={ok}  (too little tool use to judge -- not gated)\n")

    print(f"-- WORK_THRESHOLD ({WORK_THRESHOLD})+ tool calls, no evidence --")
    t2 = new_task()
    fire_tool_calls(t2, count=WORK_THRESHOLD)
    ok, result = t2.guardrail(unbacked)
    print(f"allowed={ok}")
    if not ok:
        print(f"reason: {result}\n")

    print(f"-- calling the guardrail again on that task, still no evidence --")
    print(f"-- (this simulates the guardrail being invoked a second time --")
    print(f"--  it does NOT advance t2.retry_count or otherwise reproduce")
    print(f"--  CrewAI's real retry machinery; the test suite's live-kickoff")
    print(f"--  tests do that, against an actual crew.kickoff()) --")
    fire_tool_calls(t2, count=WORK_THRESHOLD)
    ok, result = t2.guardrail(unbacked)
    print(f"allowed={ok}  (judged fresh, same as the first attempt; CrewAI's")
    print(f"             own retry cap bounds this, not anything in the")
    print(f"             adapter -- see crewai.py's module docstring)\n")

    print(f"-- WORK_THRESHOLD+ tool calls, claim WITH evidence --")
    t3 = new_task()
    fire_tool_calls(t3, count=WORK_THRESHOLD)
    backed = FakeTaskOutput(
        raw="Deployed the fix.\nHealth check: 200 OK, 0 errors in the last 5 min.")
    ok, result = t3.guardrail(backed)
    print(f"allowed={ok}")
