"""One command wires the claims gate into Claude Code.

    python -m agentattest.claude_code install           # this project
    python -m agentattest.claude_code install --user    # every project
    python -m agentattest.claude_code uninstall

After `install`, the agent in that project cannot end a turn on "Fixed. All
tests pass." with nothing attached. Claude Code invokes this module at the end
of every turn; it reads the reply the turn just produced, and if a completion
claim has no evidence near it, the turn is refused with the reason handed back
to the agent -- which then revises the reply instead of guessing.

`hooks.stop_hook` is the raw adapter: it expects the reply text handed to it.
This module is the missing half that makes it real: Claude Code's Stop event
does NOT carry the reply text. It carries a path to the session transcript, and
the text has to be dug out of the last assistant message. That wiring -- payload
field names, transcript walking, the block protocol -- was learned from a hook
that has run in production for months, not from documentation. (The documented
field name for another hook event was simply wrong once, and the capture hook
built on it recorded nothing, silently, for weeks. Field names come from
working systems.)

Design decisions, each earned:

* **Conversational turns are never gated.** A turn that ran no tools and wrote
  no files ("sounds good, that works") makes no completion claim worth
  policing. Only turns that did real work -- a file edit, or a meaningful
  number of tool calls -- are inspected. A gate that nags small talk gets
  uninstalled, and then it catches nothing.
* **The loop guard is not optional.** When a Stop hook blocks, the agent
  revises and stops again, and the hook runs again. `stop_hook_active` is set
  on that second pass; blocking on it would loop the agent forever.
* **Errors allow the turn, and say so.** A broken hook that blocks every turn
  kills the session it was guarding. But swallowing the error silently is the
  exact failure `gates.SilentSkip` exists to catch -- absent-and-fine must
  never look like present-and-fine. So every error path allows the turn AND
  writes one line to stderr saying the gate did not run.
* **Install merges; it never overwrites.** Other hooks in the settings file
  belong to someone. Install is idempotent (running it twice adds one entry,
  not two), uninstall removes exactly our entry and nothing else, and a
  settings file that does not parse is refused loudly rather than replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from agentattest.core import Finding, Gate
from agentattest.gates import UnbackedClaims
from agentattest.hooks import WRITE_TOOLS

__all__ = [
    "MARKER", "WORK_THRESHOLD", "last_assistant_turn", "decide",
    "hook_command", "settings_file", "install", "uninstall", "main",
]

#: The substring that identifies OUR entry in a settings file. Install checks
#: for it before adding (idempotence); uninstall removes only entries carrying
#: it. It is the module's own import path, so it cannot collide with a hook
#: somebody else wrote unless they invoke this module -- in which case it is us.
MARKER = "-m agentattest.claude_code"

#: A turn with at least this many tool calls "did work" even without a file
#: write -- long investigations end in factual claims worth backing too.
WORK_THRESHOLD = 5

#: How many transcript lines to walk back looking for the just-finished turn.
#: The transcript is one JSON object per line and the last turn is at the end.
LOOKBACK = 80


# --------------------------------------------------------------- transcript
def last_assistant_turn(transcript_path: str | Path,
                        lookback: int = LOOKBACK) -> tuple[str, bool]:
    """Return (reply_text, did_work) for the turn that just ended.

    Walks the transcript backwards. `reply_text` is the final text block of the
    most recent assistant message. `did_work` is True when the recent window
    contains a file-writing tool call, or `WORK_THRESHOLD`+ tool calls of any
    kind.

    The honest limit: the window is recent lines, not an exact turn boundary,
    so `did_work` can credit a tool call from the tail of the previous turn.
    That errs toward inspecting slightly too often, never toward missing the
    reply text itself, and the gate it feeds ignores everything but unbacked
    claims -- so the cost of the approximation is a few spare inspections, not
    false blocks.
    """
    lines = Path(transcript_path).read_text(
        encoding="utf-8", errors="replace").splitlines()

    text = ""
    tool_uses = 0
    had_write = False

    for raw in reversed(lines[-lookback:]):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue

        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = msg.get("role") or obj.get("type")
        content = msg.get("content")
        if isinstance(content, list):
            blocks = content
        elif isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        else:
            blocks = []

        texts_here = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_uses += 1
                if block.get("name") in WRITE_TOOLS:
                    had_write = True
            elif block.get("type") == "text" and role == "assistant":
                texts_here.append(block.get("text") or "")

        # Reversed order means the first assistant text we meet is the last one
        # spoken. Within that message, the final text block is the reply.
        if texts_here and not text:
            text = texts_here[-1]

    return text, (had_write or tool_uses >= WORK_THRESHOLD)


# ------------------------------------------------------------------ decide
def decide(payload: dict, gates: Iterable[Gate] | None = None) -> dict | None:
    """The whole policy in one testable function.

    Returns the block decision as a dict, or None to allow. Raises nothing on a
    malformed payload -- missing pieces mean "cannot judge", and cannot-judge
    allows (the runtime entry announces it; see `main`).
    """
    if payload.get("stop_hook_active"):
        return None  # second pass after a block; blocking again would loop
    transcript = payload.get("transcript_path") or ""
    if not transcript or not os.path.isfile(transcript):
        return None

    text, did_work = last_assistant_turn(transcript)
    if not text or not did_work:
        return None

    findings: list[Finding] = []
    for gate in (gates if gates is not None else [UnbackedClaims(window=2)]):
        findings.extend(gate.check(text))  # check() verifies the gate first
    if not findings:
        return None

    shown = " | ".join(f'"{(f.excerpt or f.message)[:80]}"' for f in findings[:4])
    return {
        "decision": "block",
        "reason": (
            "completion claim(s) with no evidence in the same turn: " + shown +
            ". Show the proof (command output, exit code, test result, or "
            "file and snippet) for each, or soften the claim. A dry run "
            "proves wiring, not correctness."
        ),
    }


# ----------------------------------------------------------------- install
def settings_file(user: bool = False, project: str | Path | None = None) -> Path:
    """Where the hook gets wired. Project-level by default, `--user` for all."""
    base = Path.home() if user else Path(project or ".")
    return base / ".claude" / "settings.json"

def hook_command(python: str | None = None) -> str:
    """The command Claude Code will run at every Stop event.

    Defaults to the interpreter running the install, by full path -- that is
    the one proven to have agentattest importable. Forward slashes on purpose:
    they survive JSON, cmd.exe, and every POSIX shell alike.
    """
    exe = (python or sys.executable).replace("\\", "/")
    return f'"{exe}" {MARKER}'


def _entries(data: dict) -> list:
    return data.setdefault("hooks", {}).setdefault("Stop", [])


def _installed(data: dict) -> bool:
    for entry in data.get("hooks", {}).get("Stop", []):
        for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if MARKER in str(hook.get("command", "")):
                return True
    return False


def _load(path: Path) -> dict:
    """Parse the settings file, refusing to proceed over one we cannot parse.

    Overwriting a hand-edited settings file because it had a trailing comma
    would cost a stranger their whole configuration. Refusal is the only
    honest response to a file we cannot round-trip.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(
            f"refusing to touch {path}: it is not valid JSON ({exc}). "
            f"Fix the file first; nothing was changed."
        )
    if not isinstance(data, dict):
        raise SystemExit(
            f"refusing to touch {path}: expected a JSON object at the top "
            f"level, found {type(data).__name__}. Nothing was changed."
        )
    return data


def install(path: Path, python: str | None = None, dry_run: bool = False) -> str:
    """Wire the Stop hook into `path`, creating the file if needed."""
    data = _load(path)
    if _installed(data):
        return f"already installed in {path} -- nothing to do"

    _entries(data).append({
        "hooks": [{"type": "command", "command": hook_command(python),
                   "timeout": 20}],
    })
    if dry_run:
        return (f"would write {path}:\n"
                + json.dumps(data, indent=2))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return (f"installed: {path}\n"
            f"Every turn in this scope now has to back its completion claims. "
            f"Try it: tell the agent to reply exactly 'Fixed. All tests pass.' "
            f"after any file edit, and watch the turn get refused.")


def uninstall(path: Path, dry_run: bool = False) -> str:
    """Remove exactly our entry. Everything else in the file is untouched."""
    data = _load(path)
    if not _installed(data):
        return f"not installed in {path} -- nothing to do"

    stop = data["hooks"]["Stop"]
    for entry in list(stop):
        hooks = entry.get("hooks", []) if isinstance(entry, dict) else []
        kept = [h for h in hooks if MARKER not in str(h.get("command", ""))]
        if kept:
            entry["hooks"] = kept
        else:
            stop.remove(entry)
    if not stop:
        del data["hooks"]["Stop"]
    if not data["hooks"]:
        del data["hooks"]

    if dry_run:
        return f"would write {path}:\n" + json.dumps(data, indent=2)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"uninstalled from {path}"


# -------------------------------------------------------------------- main
def _run_hook() -> int:
    """The runtime entry Claude Code invokes. Never blocks by accident.

    Exit is always 0; a block is the JSON decision on stdout, which survives
    dispatchers that merge several hooks' output. Any internal failure allows
    the turn and says so on stderr -- an announced skip, never a silent one.
    """
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        verdict = decide(payload)
    except Exception as exc:  # noqa: BLE001 - announced fail-open, by design
        print(f"agentattest: gate did not run ({type(exc).__name__}: {exc}); "
              f"allowing the turn.", file=sys.stderr)
        return 0
    if verdict is not None:
        print(json.dumps(verdict))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agentattest.claude_code",
        description="Wire the claims gate into Claude Code, or run as its Stop hook.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for name in ("install", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--user", action="store_true",
                       help="wire into ~/.claude (every project) instead of ./.claude")
        p.add_argument("--project", default=None,
                       help="project directory (default: current directory)")
        p.add_argument("--settings", default=None,
                       help="explicit settings.json path, overriding --user/--project")
        p.add_argument("--dry-run", action="store_true",
                       help="print what would be written, write nothing")
        if name == "install":
            p.add_argument("--python", default=None,
                           help="interpreter to run the hook with "
                                "(default: the one running this install)")

    args = parser.parse_args(argv)
    if args.cmd is None:
        return _run_hook()

    path = Path(args.settings) if args.settings else settings_file(
        user=args.user, project=args.project)
    if args.cmd == "install":
        print(install(path, python=args.python, dry_run=args.dry_run))
    else:
        print(uninstall(path, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
