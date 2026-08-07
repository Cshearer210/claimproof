"""The hook adapters: a gate is only binding once the runtime calls it."""
import io
import json

import pytest

from claimproof import Case, Gate, SelftestError
from claimproof.gates import UnbackedClaims
from claimproof.hooks import (ALLOW, BLOCK, pre_tool_use_hook, run_stop_hook,
                               stop_hook)


def test_a_turn_with_an_unbacked_claim_is_blocked():
    code, msg = stop_hook({"text": "It works."}, [UnbackedClaims()])
    assert code == BLOCK
    assert "Turn refused" in msg
    assert "no evidence" in msg


def test_a_turn_that_shows_its_work_is_allowed():
    code, msg = stop_hook({"text": "It works. exit=0"}, [UnbackedClaims()])
    assert code == ALLOW
    assert msg == ""


def test_the_block_message_tells_the_agent_how_to_fix_it():
    _, msg = stop_hook({"text": "Deployed."}, [UnbackedClaims()])
    assert "Show the proof" in msg
    assert "dry run proves wiring" in msg


@pytest.mark.parametrize("key", ["text", "message", "transcript"])
def test_it_reads_the_payload_under_any_of_the_common_keys(key):
    code, _ = stop_hook({key: "It works."}, [UnbackedClaims()])
    assert code == BLOCK


class BrokenGate(Gate):
    """Passes everything, and its own fixtures say it should not."""

    def inspect(self, text):
        return []

    def selftest_cases(self):
        return [Case(text="anything", expect_flagged=True)]


def test_a_broken_gate_raises_instead_of_quietly_allowing_the_turn():
    """The whole point. A gate that cannot prove itself must not wave things through."""
    with pytest.raises(SelftestError):
        stop_hook({"text": "It works."}, [BrokenGate()])


# ----------------------------------------------------------------- pre tool use

def no_writes_to_generated(tool, tool_input):
    path = str(tool_input.get("file_path", ""))
    if tool in ("Write", "Edit") and "/generated/" in path.replace("\\", "/"):
        return f"{path} is generated output and must not be hand-edited"
    return None


def test_a_write_violating_an_invariant_is_refused_before_it_lands():
    code, msg = pre_tool_use_hook(
        {"tool_name": "Write", "tool_input": {"file_path": "src/generated/api.py"}},
        [no_writes_to_generated],
    )
    assert code == BLOCK
    assert "generated output" in msg


def test_an_ordinary_write_is_allowed():
    code, msg = pre_tool_use_hook(
        {"tool_name": "Write", "tool_input": {"file_path": "src/app/main.py"}},
        [no_writes_to_generated],
    )
    assert code == ALLOW and msg == ""


def test_every_violated_invariant_is_reported_not_just_the_first():
    always = lambda t, i: "first reason"
    also = lambda t, i: "second reason"
    code, msg = pre_tool_use_hook({"tool_name": "Write"}, [always, also])
    assert code == BLOCK
    assert "first reason" in msg and "second reason" in msg


# --------------------------------------------------------------------- stdin

def test_the_entry_point_blocks_on_a_bad_turn():
    stream = io.StringIO(json.dumps({"text": "It works."}))
    assert run_stop_hook([UnbackedClaims()], stream=stream) == BLOCK


def test_the_entry_point_allows_a_good_turn():
    stream = io.StringIO(json.dumps({"text": "It works. exit=0"}))
    assert run_stop_hook([UnbackedClaims()], stream=stream) == ALLOW


def test_malformed_input_fails_open_rather_than_wedging_every_turn():
    """A hook that crashes the agent constantly gets deleted, and then protects nothing."""
    assert run_stop_hook([UnbackedClaims()], stream=io.StringIO("not json")) == ALLOW
