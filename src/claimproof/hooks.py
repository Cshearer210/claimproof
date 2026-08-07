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

from claimproof.core import Finding, Gate

__all__ = ["BLOCK", "ALLOW", "stop_hook", "pre_tool_use_hook", "gate_invariant",
           "run_stop_hook"]

#: Tools whose payload carries text about to be written to a file.
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "write_file", "edit_file")
#: Payload keys those tools use for the text itself.
CONTENT_FIELDS = ("content", "new_string", "new_source", "text", "contents")

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


def gate_invariant(
    gate: Gate,
    tools: Sequence[str] = WRITE_TOOLS,
    fields: Sequence[str] = CONTENT_FIELDS,
    strict: bool = False,
    suffixes: Sequence[str] | None = None,
) -> Callable[[str, dict], str | None]:
    """Turn a `Gate` into an invariant that inspects what is about to be WRITTEN.

    `stop_hook` reads what an agent is about to say. This reads what it is about
    to save, which is the difference between catching a bad pattern in review and
    never letting it land::

        from claimproof.gates import TypedScope
        from claimproof.hooks import pre_tool_use_hook, gate_invariant

        code, message = pre_tool_use_hook(payload, [gate_invariant(TypedScope())])

    The gate is verified before it is trusted, so a gate that can no longer catch
    its own must-fail case raises here rather than quietly allowing every write.

    `suffixes` restricts it to files a gate can actually read::

        gate_invariant(SilentSkip(), suffixes=(".py",))

    That matters for a gate whose lenient behaviour on unreadable input is itself
    a degrade. Filtering by suffix is the honest way to keep it off Markdown,
    rather than having it stay quiet about text it never could have judged.

    **It fails OPEN when a targeted tool carries no recognisable content field.**
    That is a deliberate trade and it is the wrong default for some people, so
    `strict=True` refuses instead. The reasoning for the default: a pre-write hook
    that blocks on everything it cannot parse gets removed within the day, and a
    removed hook protects nothing. `strict=True` is right when you control the
    payload shape and would rather be stopped than guessed at.
    """
    wanted = {t.lower() for t in tools}
    endings = tuple(s.lower() for s in suffixes) if suffixes else None

    def _invariant(tool: str, tool_input: dict) -> str | None:
        if (tool or "").lower() not in wanted:
            return None

        if endings is not None:
            path = ""
            if isinstance(tool_input, dict):
                path = str(tool_input.get("file_path") or tool_input.get("path") or "")
            if not path.lower().endswith(endings):
                return None

        chunks = [str(tool_input[f]) for f in fields
                  if isinstance(tool_input, dict) and tool_input.get(f)]
        if not chunks:
            if strict:
                return (f"{gate.name}: {tool} carried no inspectable content, so "
                        f"this write could not be checked. Refusing rather than "
                        f"assuming it is fine.")
            return None

        findings = gate.check("\n".join(chunks))   # check() verifies the gate first
        if not findings:
            return None

        where = ""
        if isinstance(tool_input, dict):
            where = str(tool_input.get("file_path") or tool_input.get("path") or "")
        head = f"{gate.name} in {where}" if where else gate.name
        detail = "; ".join(str(f) for f in findings[:3])
        more = f" (+{len(findings) - 3} more)" if len(findings) > 3 else ""
        return f"{head}: {detail}{more}"

    return _invariant


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
