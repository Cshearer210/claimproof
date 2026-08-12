#!/usr/bin/env python3
"""Gate a CrewAI crew's tasks against unbacked completion claims.

`gate_task(task)` attaches the claims gate to a `Task` as its `guardrail`.
CrewAI already retries a failed guardrail (feeding the reason back to the
agent) up to `guardrail_max_retries` times, so a blocked task gets a real
chance to fix itself rather than dying on the spot.

Wire it into your own crew:

    from claimproof.crewai import gate_task

    research = Task(description="...", agent=researcher, expected_output="...")
    gate_task(research)  # in place; research.guardrail is now set

    Crew(agents=[researcher], tasks=[research]).kickoff()

Only tasks that used at least `WORK_THRESHOLD` tools get gated -- a task that
never touched a tool but still claims "done" is exactly the case this exists
for; a one-line factual answer is not.

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
    investigate = Task(
        description="Investigate the failing deploy and report the fix.",
        expected_output="A root-cause summary.",
    )
    gate_task(investigate)

    print(f"-- fewer than WORK_THRESHOLD ({WORK_THRESHOLD}) tool calls --")
    fire_tool_calls(investigate, count=2)
    claim = FakeTaskOutput(raw="Deployed the fix. Everything works now.")
    ok, result = investigate.guardrail(claim)
    print(f"allowed={ok}  (too little tool use to judge -- not gated)\n")

    print(f"-- WORK_THRESHOLD ({WORK_THRESHOLD})+ tool calls, no evidence --")
    fire_tool_calls(investigate, count=WORK_THRESHOLD)
    ok, result = investigate.guardrail(claim)
    print(f"allowed={ok}")
    if not ok:
        print(f"reason: {result}\n")

    print(f"-- same task, same claim, right after a block (loop guard) --")
    ok, result = investigate.guardrail(claim)
    print(f"allowed={ok}  (one retry's worth of leniency, so the loop ends)\n")

    print(f"-- WORK_THRESHOLD+ tool calls, claim WITH evidence --")
    fire_tool_calls(investigate, count=WORK_THRESHOLD)
    backed = FakeTaskOutput(
        raw="Deployed the fix.\nHealth check: 200 OK, 0 errors in the last 5 min.")
    ok, result = investigate.guardrail(backed)
    print(f"allowed={ok}")