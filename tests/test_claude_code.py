"""The one-command Claude Code integration, tested the way it will be used.

The install path is tested against real files in temp directories, and the hook
is run as a real subprocess fed a real payload -- because the failure mode that
matters is not "the function returns the wrong value", it is "the wiring never
fires and nobody can tell".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentattest.claude_code import (
    MARKER, decide, hook_command, install, last_assistant_turn,
    settings_file, uninstall,
)


# ------------------------------------------------------------ transcript fixtures
def transcript_line(role: str, blocks: list) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": blocks}})


def write_transcript(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def working_turn(reply: str) -> list[str]:
    """A turn that edited a file and then said `reply`."""
    return [
        transcript_line("user", [{"type": "text", "text": "fix the parser"}]),
        transcript_line("assistant", [
            {"type": "tool_use", "name": "Edit", "input": {}},
        ]),
        transcript_line("assistant", [{"type": "text", "text": reply}]),
    ]


# ------------------------------------------------------- last_assistant_turn
def test_finds_the_final_reply_and_sees_the_work(tmp_path):
    t = write_transcript(tmp_path, working_turn("Fixed. All tests pass."))
    text, did_work = last_assistant_turn(t)
    assert text == "Fixed. All tests pass."
    assert did_work


def test_a_conversational_turn_did_no_work(tmp_path):
    t = write_transcript(tmp_path, [
        transcript_line("user", [{"type": "text", "text": "thanks"}]),
        transcript_line("assistant", [{"type": "text", "text": "That works, glad it helped."}]),
    ])
    text, did_work = last_assistant_turn(t)
    assert text == "That works, glad it helped."
    assert not did_work


def test_the_last_text_block_wins_not_the_first(tmp_path):
    t = write_transcript(tmp_path, [
        transcript_line("assistant", [
            {"type": "text", "text": "status note mid-turn"},
            {"type": "text", "text": "the actual final reply"},
        ]),
    ])
    text, _ = last_assistant_turn(t)
    assert text == "the actual final reply"


def test_garbage_lines_are_skipped_not_fatal(tmp_path):
    lines = ["not json at all", "[1, 2, 3]"] + working_turn("Done. exit=0")
    text, did_work = last_assistant_turn(write_transcript(tmp_path, lines))
    assert text == "Done. exit=0"
    assert did_work


# ------------------------------------------------------------------- decide
def test_unbacked_claim_after_real_work_is_blocked(tmp_path):
    t = write_transcript(tmp_path, working_turn("Fixed the bug. All tests pass."))
    verdict = decide({"transcript_path": str(t)})
    assert verdict is not None and verdict["decision"] == "block"
    assert "no evidence" in verdict["reason"]


def test_claim_with_receipt_is_allowed(tmp_path):
    t = write_transcript(
        tmp_path, working_turn("Fixed the bug.\n```\n56 passed in 0.14s\n```"))
    assert decide({"transcript_path": str(t)}) is None


def test_conversational_turn_is_never_gated(tmp_path):
    # The same unbacked wording -- but no work was done, so no gate.
    t = write_transcript(tmp_path, [
        transcript_line("assistant", [{"type": "text", "text": "That works."}]),
    ])
    assert decide({"transcript_path": str(t)}) is None


def test_loop_guard_second_pass_is_allowed(tmp_path):
    t = write_transcript(tmp_path, working_turn("Fixed. All tests pass."))
    assert decide({"transcript_path": str(t), "stop_hook_active": True}) is None


def test_missing_transcript_allows(tmp_path):
    assert decide({"transcript_path": str(tmp_path / "absent.jsonl")}) is None
    assert decide({}) is None


# ------------------------------------------------------------------ install
def test_install_creates_settings_and_is_idempotent(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    msg = install(path)
    assert "installed" in msg
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["hooks"]["Stop"]
    assert len(entries) == 1
    assert MARKER in entries[0]["hooks"][0]["command"]

    assert "already installed" in install(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["hooks"]["Stop"]) == 1  # still one, not two


def test_install_preserves_someone_elses_hooks(tmp_path):
    path = tmp_path / "settings.json"
    theirs = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "their-precious-hook"}]}]},
        "model": "keep-me"}
    path.write_text(json.dumps(theirs), encoding="utf-8")

    install(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert "their-precious-hook" in commands
    assert any(MARKER in c for c in commands)
    assert data["model"] == "keep-me"

    uninstall(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    commands = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == ["their-precious-hook"]  # ours gone, theirs untouched


def test_uninstall_removes_empty_scaffolding(tmp_path):
    path = tmp_path / "settings.json"
    install(path)
    uninstall(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "hooks" not in data  # no empty husk left behind


def test_unparseable_settings_are_refused_not_replaced(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"hooks": broken', encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to touch"):
        install(path)
    assert path.read_text(encoding="utf-8") == '{"hooks": broken'  # untouched


def test_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "settings.json"
    msg = install(path, dry_run=True)
    assert "would write" in msg
    assert not path.exists()


def test_hook_command_uses_a_real_interpreter_with_forward_slashes():
    cmd = hook_command()
    assert MARKER in cmd
    assert "\\" not in cmd
    exe = cmd.split('"')[1]
    assert Path(exe).exists()


def test_settings_file_locations(tmp_path):
    assert settings_file(user=True) == Path.home() / ".claude" / "settings.json"
    proj = settings_file(project=tmp_path)
    assert proj == tmp_path / ".claude" / "settings.json"


# ------------------------------------------------- the real thing, end to end
def run_module(args=None, stdin=""):
    return subprocess.run(
        [sys.executable, "-m", "agentattest.claude_code"] + (args or []),
        input=stdin, capture_output=True, text=True, timeout=120,
    )


def test_subprocess_blocks_an_unbacked_claim(tmp_path):
    t = write_transcript(tmp_path, working_turn("Deployed. Everything works now."))
    r = run_module(stdin=json.dumps({"transcript_path": str(t)}))
    assert r.returncode == 0, r.stderr
    verdict = json.loads(r.stdout)
    assert verdict["decision"] == "block"
    assert "no evidence" in verdict["reason"]


def test_subprocess_allows_a_backed_claim(tmp_path):
    t = write_transcript(
        tmp_path, working_turn("Deployed.\n```\nservice healthy, 200 OK\n```"))
    r = run_module(stdin=json.dumps({"transcript_path": str(t)}))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_subprocess_garbage_stdin_allows_and_announces(tmp_path):
    r = run_module(stdin="this is not json")
    assert r.returncode == 0
    assert r.stdout.strip() == ""              # no block emitted
    assert "gate did not run" in r.stderr      # announced, never silent


def test_subprocess_install_the_way_the_readme_says(tmp_path):
    r = run_module(["install", "--project", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    written = tmp_path / ".claude" / "settings.json"
    assert written.exists()
    assert MARKER in written.read_text(encoding="utf-8")
    assert "installed" in r.stdout

    r2 = run_module(["uninstall", "--project", str(tmp_path)])
    assert r2.returncode == 0, r2.stderr
    assert "uninstalled" in r2.stdout
