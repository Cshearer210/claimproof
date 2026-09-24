"""Evidence is recorded while it is still a fact, and read back when it is judged.

The gap this closes: a command's exit code exists only while the process is
being reaped. By the time the reply is written it is a memory, and a memory and
a measurement look identical in prose. So the PostToolUse hook records each
result as it happens and the Stop hook reads those records before judging.

These test the seam. The gates' own cases already prove they fire and stay
quiet; what is worth testing here is that the two halves actually meet.
"""
import json
import uuid

import pytest

from claimproof import evidence
from claimproof.claude_code import POST_MARKER, hook_command, install, uninstall
from claimproof.gates import ExitCodeMismatch
from claimproof.hooks import ALLOW, BLOCK, post_tool_use_hook


@pytest.fixture()
def session():
    s = "test-" + uuid.uuid4().hex
    yield s
    evidence.clear(s)


def _call(session, command, code, **kw):
    return post_tool_use_hook(
        {"session_id": session, "tool_name": "Bash",
         "tool_input": {"command": command},
         "tool_response": {"exit_code": code}}, **kw)


def test_it_records_the_code_the_runtime_really_reported(session):
    assert _call(session, "pytest -q", 1) == (ALLOW, "")
    assert evidence.read(session) == ["[claimproof:exit] 1 pytest -q"]


def test_receipts_accumulate_in_order(session):
    _call(session, "make build", 0)
    _call(session, "pytest -q", 2)
    assert evidence.read(session) == ["[claimproof:exit] 0 make build",
                                      "[claimproof:exit] 2 pytest -q"]


def test_stderr_is_not_treated_as_failure(session):
    """A great many healthy commands write to stderr. Guessing failure from it
    would fire on ordinary turns, and a gate that does that gets uninstalled."""
    post_tool_use_hook({"session_id": session, "tool_name": "Bash",
                        "tool_input": {"command": "curl -s x"},
                        "tool_response": {"stderr": "warning: slow"}})
    assert evidence.read(session) == [], "no code reported means no code known"


def test_a_mid_task_claim_is_caught_at_the_call_that_disproves_it(session):
    code, message = post_tool_use_hook(
        {"session_id": session, "tool_name": "Bash",
         "tool_input": {"command": "git commit -m 'all tests pass now'"},
         "tool_response": {"exit_code": 1}}, gates=[ExitCodeMismatch()])
    assert code == BLOCK
    assert "exited 1" in message


def test_an_ordinary_successful_call_says_nothing(session):
    assert _call(session, "ls -la", 0, gates=[ExitCodeMismatch()]) == (ALLOW, "")


@pytest.mark.parametrize("payload", [None, {}, [], "nonsense", {"tool_name": "Bash"}])
def test_a_malformed_payload_never_takes_the_turn_down(payload):
    """This runs after every command the agent issues. An exception here would
    be an exception on all of them."""
    assert post_tool_use_hook(payload) == (ALLOW, "")


def test_a_hostile_session_id_stays_inside_the_store():
    import os
    assert os.path.dirname(evidence.path_for("../../etc/passwd")) == evidence.store_dir()


# ------------------------------------------------------------------ installer
def test_the_two_hook_commands_are_distinguishable():
    assert hook_command() != hook_command(python=None, event="PostToolUse")
    assert POST_MARKER in hook_command(event="PostToolUse")
    assert POST_MARKER not in hook_command()


def test_install_wires_both_events_and_uninstall_removes_both(tmp_path):
    s = tmp_path / ".claude" / "settings.json"
    install(s)
    data = json.loads(s.read_text())
    assert set(data["hooks"]) == {"Stop", "PostToolUse"}, (
        "the recorder blocks nothing and the judge has nothing to read; "
        "either alone is half a gate")

    assert "already installed" in install(s), "a second install must not double the gate"
    assert json.loads(s.read_text()) == data

    uninstall(s)
    assert "claimproof" not in s.read_text()


def test_uninstall_leaves_somebody_elses_hook_alone(tmp_path):
    s = tmp_path / ".claude" / "settings.json"
    install(s)
    data = json.loads(s.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo mine"}]})
    s.write_text(json.dumps(data))

    uninstall(s)
    after = s.read_text()
    assert "claimproof" not in after
    assert "echo mine" in after, "we removed a stranger's configuration"
