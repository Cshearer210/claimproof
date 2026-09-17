"""Exit codes and test counts are read from what was captured, not the prose.

Each gate's own `selftest_cases()` proves it fires and stays quiet, and
`check()` refuses to run until they pass. These cover what the cases cannot:
that the gates are REACHABLE (exported, and in the hook's default set), and
that a finding names both numbers -- the one claimed and the one recorded --
because a finding a reader cannot act on gets ignored.
"""
import os
import tempfile

import claimproof
from claimproof import capture
from claimproof.claude_code import default_gates
from claimproof.gates import ExitCodeMismatch, UnbackedTestCount


def _junit(tests, failures=0, errors=0, skipped=0):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?><testsuites><testsuite '
                 'tests="%d" failures="%d" errors="%d" skipped="%d"/></testsuites>'
                 % (tests, failures, errors, skipped))
    return path


def test_both_are_exported_from_the_package_root():
    assert claimproof.ExitCodeMismatch is ExitCodeMismatch
    assert claimproof.UnbackedTestCount is UnbackedTestCount


def test_both_run_in_the_installed_hooks_default_set():
    kinds = {type(g).__name__ for g in default_gates()}
    assert {"ExitCodeMismatch", "UnbackedTestCount"} <= kinds, (
        "a gate nothing reaches catches nothing; %s" % sorted(kinds))


def test_the_default_set_leaves_an_ordinary_turn_alone():
    text = ("Renamed the helper and reran the suite.\n"
            "[claimproof:exit] 0 pytest -q\n")
    for gate in default_gates():
        assert not gate.inspect(text), "%s fired on an ordinary turn" % type(gate).__name__


def test_a_receipt_records_what_really_happened():
    ran = capture.run(["python3", "-c", "raise SystemExit(4)"], echo=False)
    assert ran.returncode == 4 and not ran.ok
    assert capture.receipt(ran.command, ran.returncode).startswith("[claimproof:exit] 4 ")


def test_an_exit_finding_names_the_captured_code():
    found = ExitCodeMismatch().inspect("[claimproof:exit] 2 make build\nIt exited 0.")
    assert found
    assert "2" in found[0].message, "the finding must carry the code that was RECORDED"


def test_a_count_finding_names_both_numbers():
    found = UnbackedTestCount().inspect(
        "All 200 tests pass. --junit-xml=%s" % _junit(105))
    assert found
    assert "200" in found[0].message and "105" in found[0].message


def test_a_named_report_that_cannot_be_read_is_not_a_pass():
    found = UnbackedTestCount().inspect(
        "All 105 tests pass. --junit-xml=/nonexistent/report.xml")
    assert found, "unknown must never read as clean"
