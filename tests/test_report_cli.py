"""report.main() — the `claimproof check` CLI — plus the three formatters.

test_report_check.py exercised check() but never main() or the format branches, so the suite
killed only 8/21 of report.py's mutants; the whole argv parser (--format / --format= / --root,
the i+=2 stepping, argv-is-None) and to_text/to_json/to_sarif were untested. These are real logic,
not equivalent mutants, so they are worth killing."""
import io
import json
import os
import tempfile
import contextlib

from claimproof import report


def _run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = report.main(argv)
    return rc, buf.getvalue()


def _tmp(text):
    fd, p = tempfile.mkstemp(suffix=".txt")
    os.write(fd, text.encode("utf-8"))
    os.close(fd)
    return p


def test_main_flags_a_bare_claim_and_reports_it_as_text():
    p = _tmp("It works. Everything is fixed now.")
    try:
        rc, out = _run([p])                       # kills L144 argv-is-None (list arg is used, not sys.argv)
        assert rc == 1                            # findings -> nonzero
        assert "finding" in out.lower()
    finally:
        os.unlink(p)


def test_main_clean_text_returns_zero():
    p = _tmp("I changed core.py:41 and ran the suite: 12 passed. exit=0")
    try:
        rc, out = _run([p])
        assert rc == 0
        assert "nothing flagged" in out.lower()
    finally:
        os.unlink(p)


def test_main_format_json_space_form():
    p = _tmp("It works. Everything is fixed now.")
    try:
        rc, out = _run([p, "--format", "json"])   # kills L151/L152 (--format <val>, i+=2)
        data = json.loads(out)
        assert data["tool"] == "claimproof"
        assert len(data["findings"]) >= 1
    finally:
        os.unlink(p)


def test_main_format_equals_form_sarif():
    p = _tmp("It works. Everything is fixed now.")
    try:
        rc, out = _run([p, "--format=sarif"])     # kills L153/L154 (--format=<val>)
        data = json.loads(out)
        assert data["version"] == "2.1.0"
        assert data["runs"][0]["results"]
    finally:
        os.unlink(p)


def test_main_root_flag_is_consumed_not_treated_as_a_file():
    p = _tmp("It works. Everything is fixed now.")
    try:
        # --root DIR must be consumed (i+=2); if it were treated as a file the parser would try to
        # open the repo dir as the input file and crash. kills L155/L156.
        rc, out = _run(["--root", os.path.dirname(p), p])
        assert rc == 1
        assert "finding" in out.lower()
    finally:
        os.unlink(p)


def test_formatters_on_empty_pairs():
    assert "nothing flagged" in report.to_text([]).lower()
    assert json.loads(report.to_json([]))["findings"] == []
    assert json.loads(report.to_sarif([]))["runs"][0]["results"] == []
