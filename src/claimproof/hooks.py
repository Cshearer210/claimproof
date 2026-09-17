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
import re
import sys
from typing import Callable, Iterable, Sequence

from claimproof import capture, evidence
from claimproof.core import Finding, Gate

__all__ = ["BLOCK", "ALLOW", "stop_hook", "pre_tool_use_hook", "post_tool_use_hook", "gate_invariant",
           "run_stop_hook"]

#: Tools whose payload carries text about to be written to a file.
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "write_file", "edit_file")
#: Payload keys those tools use for the text itself.
CONTENT_FIELDS = ("content", "new_string", "new_source", "text", "contents")

#: Exit codes. 2 blocks the action and shows stderr to the agent.
BLOCK = 2
ALLOW = 0


def _as_text(value) -> str:
    """Whatever a runtime handed us, as inspectable text. Never raises.

    A string is itself. A list is the concatenation of its text-ish parts,
    which is how content-block APIs represent one message. A dict contributes
    its own `text`/`content` field if it has one. Anything else -- a number,
    None, an object -- has no text in it, and saying so honestly is better than
    stringifying it into something a gate might match on by accident.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                return _as_text(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(p for p in (_as_text(v) for v in value) if p)
    return ""


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

    The payload comes from someone else's runtime, so its fields are whatever
    that runtime sends -- a number, a list of content blocks, a nested dict, or
    not a dict at all. Found 2026-08-07 by feeding it hostile payloads: a
    non-string `text` raised TypeError and took the whole turn down. Found
    2026-09-16, same class: `payload=None` (or a list, or a bare string) reached
    `payload.get(...)` unguarded and raised AttributeError -- one layer up from
    the first hostile-FIELD case. A gate that kills the turn it was guarding
    gets uninstalled, so anything text-shaped is read as text and anything else
    -- including a malformed payload itself -- is treated as no text at all.
    """
    if not isinstance(payload, dict):
        payload = {}
    text = _as_text(payload.get("text") or payload.get("message")
                    or payload.get("transcript") or "")

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


#: Tools whose payload is a command with a real exit code behind it.
RUN_TOOLS = ("Bash", "bash", "shell", "run_command", "execute_command")


def _exit_code_of(response) -> int | None:
    """The exit code a runtime reported, or None if it reported none.

    Runtimes disagree about this field, so several spellings are accepted. What
    is NOT done here is inferring failure from the presence of stderr: plenty of
    healthy commands write to stderr, and a gate built on that guess would fire
    on ordinary turns and be uninstalled. No code reported means no code known.
    """
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode", "returncode", "return_code", "code", "status"):
            v = response.get(key)
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                return v
            if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
                return int(v.strip())
        err = response.get("is_error", response.get("isError"))
        if isinstance(err, bool):
            return 1 if err else 0
    return None


def post_tool_use_hook(
    payload: dict,
    gates: Iterable[Gate] = (),
    session: str | None = None,
    store: bool = True,
) -> tuple[int, str]:
    """Record what a tool just really did, and judge the claim attached to it.

    `stop_hook` runs once, at the end, when every exit code has already become
    a memory. This runs after each tool call, while the result is still a fact,
    and it does two things:

    * **Records the real exit code** as a receipt, so `ExitCodeMismatch` has
      something to check the final reply against. This is the half that makes
      that gate work outside a demo -- without it, a turn's text carries a
      captured exit code only if the author remembered to use `capture.run`.
    * **Judges any claim carried in the same tool call** against the evidence
      just produced -- a commit message, a file being written -- so a false
      intermediate claim is caught before the rest of the task is built on it.

    Returns (exit_code, message). BLOCK means the message goes back to the
    agent; the tool has already run, so this is a correction rather than a veto.
    A call with nothing to judge returns ALLOW, quietly, which is almost all of
    them.
    """
    if not isinstance(payload, dict):
        payload = {}
    tool = str(payload.get("tool_name") or payload.get("tool") or "")
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    response = payload.get("tool_response") or payload.get("output") or {}
    session = session or str(payload.get("session_id") or payload.get("session") or "unknown")

    receipt_line = ""
    if tool in RUN_TOOLS or tool.lower() in {t.lower() for t in RUN_TOOLS}:
        code = _exit_code_of(response)
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        if code is not None and command:
            receipt_line = capture.receipt(command, code)
            if store:
                evidence.record(session, receipt_line)

    gates = list(gates)
    if not gates:
        return ALLOW, ""

    # What this call itself said, plus what it actually produced. Both, because
    # a claim is only wrong relative to its own evidence.
    said = _as_text(tool_input) if not isinstance(tool_input, dict) else "\n".join(
        str(tool_input[f]) for f in ("command", "description", "message", "content",
                                     "new_string", "text")
        if tool_input.get(f))
    text = "\n".join(p for p in (receipt_line, said, _as_text(response)) if p)
    if not text.strip():
        return ALLOW, ""

    findings: list[Finding] = []
    for gate in gates:
        findings.extend(gate.check(text))
    if not findings:
        return ALLOW, ""

    return BLOCK, _render(
        findings,
        "Mid-task claim does not match what that tool call actually produced.",
        "Correct it now, before the rest of the task is built on it.",
    )
