"""One command wires the claims gate into Claude Code. This is the whole
journey in a sandbox: install, a turn refused, the fix, uninstall.

Run me:

    python claude_code_install.py

Everything happens in a temp directory. Your own settings are never touched.
"""
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

MODULE = [sys.executable, "-m", "claimproof.claude_code"]


def run(args=None, stdin=""):
    return subprocess.run(MODULE + (args or []), input=stdin,
                          capture_output=True, text=True, timeout=120)


def show(label, body):
    print(label)
    print("-" * len(label))
    print(textwrap.indent(body.rstrip() or "(no output -- the turn is allowed)", "  "))
    print()


def transcript(tmp, reply):
    """A minimal session transcript: the agent edited a file, then said `reply`."""
    lines = [
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Edit", "input": {}}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": reply}]}}),
    ]
    path = Path(tmp) / "transcript.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return json.dumps({"transcript_path": str(path)})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        r = run(["install", "--project", tmp])
        show("1. Install into a project", r.stdout)

        settings = Path(tmp) / ".claude" / "settings.json"
        show("What was written to .claude/settings.json",
             settings.read_text(encoding="utf-8"))

        r = run(stdin=transcript(tmp, "Refactored the parser. All tests pass."))
        verdict = json.loads(r.stdout)
        show("2. The agent ends a turn on an unbacked claim",
             json.dumps(verdict, indent=2))

        r = run(stdin=transcript(
            tmp, "Refactored the parser.\n```\n56 passed in 0.14s\n```"))
        show("3. The same claim, with the receipt attached", r.stdout)

        r = run(["uninstall", "--project", tmp])
        show("4. Uninstall removes exactly our entry", r.stdout)

    print("The gate only inspects turns that did real work (a file edit, or")
    print("several tool calls). Conversational turns are never gated -- a hook")
    print("that nags small talk gets uninstalled, and then it catches nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
