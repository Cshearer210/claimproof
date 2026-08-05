"""Runtime hook adapters. This is the part that makes a gate binding.

A gate you have to remember to call is a suggestion. The same gate wired into the
agent runtime is a rule, because the runtime calls it whether anyone remembers or
not. These adapters turn a `Gate` into something an agent harness can invoke.

The conventions here follow Claude Code's hook protocol (JSON on stdin, exit 2 to
block with the reason on stderr), because that is the harness this was proven in.
The functions take plain dicts, so adapting to another runtime is a small shim
rather than a rewrite.
"""
from __future__ import annotations

import json
import sys
from typing import Callable, Iterable, Sequence

from agentattest.core import Finding, Gate

__all__ = ["BLOCK", "ALLOW", "stop_hook", "pre_tool_use_hook", "run_stop_hook"]

#: Exit codes. 2 blocks the action and shows stderr to the agent.
BLOCK = 2
ALLOW = 0


def _render(findings: Sequence[Finding], header: str, remedy: str) -> str:
    lines = [header]
    for f in findings:
        lines.append(f"  x {f}")
    lines.append(remedy)
    return "\n".join(lines)


def stop_hook(payload: dict, gates: Iterable[Gate]) -> tuple[int, str]:
    """Decide whether an agent may end its turn.

    Returns (exit_code, message). BLOCK means the turn is refused and `message`
    is handed back to the agent so it can fix the reply rather than guess.

    Every gate is verified before it is trusted, so a broken gate raises loudly
    here instead of quietly waving the turn through.
    """
    text = payload.get("text") or payload.get("message") or payload.get("transcript") or ""

    all_findings: list[Finding] = []
    for gate in gates:
        all_findings.extend(gate.check(text))    # check() verifies first

    if not all_findings:
        return ALLOW, ""

    return BLOCK, _render(
        all_findings,
        "Turn refused: completion claim(s) with no evidence in the same turn.",
        "Show the proof (command output, exit code, test result, or file and snippet), "
        "or soften the claim. A dry run proves wiring, not correctness.",
    )


def pre_tool_use_hook(
    payload: dict,
    invariants: Iterable[Callable[[str, dict], str | None]],
) -> tuple[int, str]:
    """Decide whether a tool call may proceed.

    Each invariant takes (tool_name, tool_input) and returns a reason string to
    refuse, or None to allow. Refusing here means the bad write never lands, as
    opposed to being caught in review after it has already broken something.
    """
    tool = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or payload.get("input") or {}

    reasons = []
    for inv in invariants:
        reason = inv(tool, tool_input)
        if reason:
            reasons.append(reason)

    if not reasons:
        return ALLOW, ""

    body = "\n".join(f"  x {r}" for r in reasons)
    return BLOCK, f"Tool call refused: it would violate a declared invariant.\n{body}"


def run_stop_hook(gates: Iterable[Gate], stream=None) -> int:
    """Entry point for wiring into a real harness. Reads JSON on stdin.

    Fails OPEN on malformed input (exit 0) but never on a gate error, because a
    hook that crashes the agent on every turn gets removed within the hour, and a
    removed hook protects nothing.
    """
    stream = stream or sys.stdin
    try:
        payload = json.load(stream)
    except Exception:
        return ALLOW

    code, message = stop_hook(payload, gates)
    if message:
        print(message, file=sys.stderr)
    return code
