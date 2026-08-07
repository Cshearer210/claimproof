"""No silent drops: the ledger, and the gate that checks "all done" against it."""
import json
import subprocess
import sys

import pytest

from agentattest import SelftestError
from agentattest.ledger import Ledger, LedgerError, NothingLeft


# ----------------------------------------------------------------- recording
def test_an_ask_is_recorded_verbatim_and_immediately_trackable():
    led = Ledger()
    ask = led.ask("  fix the parser AND update the docs  ")
    assert ask.text == "fix the parser AND update the docs"  # trimmed, not summarized
    assert [i.id for i in led.open_items()] == ["1a"]


def test_an_empty_ask_is_refused():
    with pytest.raises(LedgerError, match="empty ask"):
        Ledger().ask("   ")


def test_split_turns_one_ask_into_named_pieces():
    led = Ledger()
    led.ask("three things please")
    items = led.split(1, "thing one", "thing two", "thing three")
    assert [i.id for i in items] == ["1a", "1b", "1c"]
    assert len(led.open_items()) == 3


def test_split_is_refused_once_evidence_points_into_the_list():
    led = Ledger()
    led.ask("two things")
    led.split(1, "first", "second")
    led.done("1a", "exit=0")
    with pytest.raises(LedgerError, match="already has closed items"):
        led.split(1, "rewritten history")


# ------------------------------------------------------------------- closing
def test_done_requires_evidence():
    led = Ledger()
    led.ask("fix it")
    with pytest.raises(LedgerError, match="needs evidence"):
        led.done("1a", "   ")


@pytest.mark.parametrize("bare", ["done", "Done.", "fixed", "works", "verified", "ok"])
def test_a_bare_claim_word_is_not_evidence(bare):
    led = Ledger()
    led.ask("fix it")
    with pytest.raises(LedgerError, match="claim, not evidence"):
        led.done("1a", bare)


def test_real_evidence_closes_the_item():
    led = Ledger()
    led.ask("fix it")
    item = led.done("1a", "pytest: 56 passed in 0.14s")
    assert item.status == "done"
    assert led.open_items() == []


def test_skip_requires_a_reason_because_that_is_the_whole_point():
    led = Ledger()
    led.ask("maybe not needed")
    with pytest.raises(LedgerError, match="silent drop"):
        led.skip("1a", "")
    item = led.skip("1a", "superseded by the rewrite in ask 2")
    assert item.status == "skipped"
    assert led.open_items() == []


def test_unknown_ids_are_loud():
    led = Ledger()
    with pytest.raises(LedgerError, match="no ask"):
        led.split(7, "x")
    with pytest.raises(LedgerError, match="no item"):
        led.done("7z", "evidence: exit=0")


# --------------------------------------------------------------- persistence
def test_state_survives_a_new_instance(tmp_path):
    path = tmp_path / "ledger.json"
    led = Ledger(path)
    led.ask("first")
    led.ask("second")
    led.done("1a", "exit=0, output shown")

    reborn = Ledger(path)  # the session that forgot
    assert [i.id for i in reborn.open_items()] == ["2a"]
    assert reborn.asks[0].items[0].evidence == "exit=0, output shown"


def test_a_corrupt_ledger_is_refused_not_replaced(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(LedgerError, match="not valid JSON"):
        Ledger(path)
    assert path.read_text(encoding="utf-8") == "{broken"  # untouched


# ------------------------------------------------------------------ the gate
def open_ledger():
    led = Ledger()
    led.ask("fix the parser")
    led.ask("update the changelog")
    return led


def test_all_done_with_items_open_is_flagged():
    findings = NothingLeft(open_ledger()).check("Everything is finished.")
    assert len(findings) == 1
    assert "2 item(s) are open" in findings[0].message
    assert "fix the parser" in findings[0].message


def test_one_item_done_is_not_a_total_claim():
    led = open_ledger()
    led.done("1a", "pytest: 56 passed")
    assert NothingLeft(led).check("Done with the parser fix; changelog is next.") == []


def test_a_true_all_done_is_left_alone():
    led = open_ledger()
    led.done("1a", "pytest: 56 passed")
    led.skip("2a", "changelog is generated at release time")
    assert NothingLeft(led).check("All done.") == []


def test_negated_and_hedged_claims_pass_even_with_items_open():
    gate = NothingLeft(open_ledger())
    assert gate.check("Not all done yet -- the changelog remains.") == []
    assert gate.check("Almost all done.") == []
    assert gate.check("Once everything is done I will report back.") == []


def test_the_gates_selftest_holds_regardless_of_live_state():
    checked = NothingLeft(Ledger()).verify()  # live ledger is EMPTY
    assert any("total claim with an item open" in c for c in checked)
    assert any("clean ledger" in c for c in checked)


def test_a_broken_detector_is_refused_by_its_own_selftest(monkeypatch):
    import agentattest.ledger as mod
    import re as _re
    # the classic silent death: someone "tightens" the pattern into nonsense
    monkeypatch.setattr(mod, "_TOTAL_CLAIM", _re.compile(r"(?!x)x"))
    with pytest.raises(SelftestError):
        NothingLeft(Ledger()).verify()


# ---------------------------------------------------------------------- CLI
def run_cli(tmp_path, *args, stdin=""):
    return subprocess.run(
        [sys.executable, "-m", "agentattest.ledger",
         "--file", str(tmp_path / "ledger.json")] + list(args),
        input=stdin, capture_output=True, text=True, timeout=120)


def test_cli_round_trip_the_way_a_harness_would_drive_it(tmp_path):
    assert "recorded ask 1" in run_cli(tmp_path, "ask", "fix the parser").stdout
    assert "recorded ask 2" in run_cli(tmp_path, "ask", "update the docs").stdout

    r = run_cli(tmp_path, "gate", stdin="All done, wrapping up.")
    assert r.returncode == 2
    assert "item(s) are open" in r.stderr

    run_cli(tmp_path, "done", "1a", "pytest: 56 passed")
    run_cli(tmp_path, "skip", "2a", "docs are generated at release")
    r = run_cli(tmp_path, "gate", stdin="All done, wrapping up.")
    assert r.returncode == 0

    r = run_cli(tmp_path, "show")
    assert "0 open" in r.stdout


def test_cli_refuses_bare_evidence_loudly(tmp_path):
    run_cli(tmp_path, "ask", "fix it")
    r = run_cli(tmp_path, "done", "1a", "done")
    assert r.returncode == 1
    assert "claim, not evidence" in r.stderr
