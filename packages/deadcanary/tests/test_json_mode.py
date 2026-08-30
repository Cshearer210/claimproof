"""`--json` promises stdout is nothing but the report. Hold it to that.

`main()` used to print a plain-English status line unconditionally on success for
`--attest`, `--expect-dead` and `--baseline` -- harmless alone, and silently wrong
combined with `--json`, which is exactly the combination a CI step piping the JSON
into another tool would reach for. Every case below combines `--json` with one of
those flags and asserts stdout parses as JSON and nothing else landed there.

`hunt()` is monkeypatched to a fixed report dict, the same shape `test_gate.py`
writes to a fixture file rather than running a real dbt project -- this is testing
which STREAM a line goes to, not whether corruption detection is correct, so a real
dbt run would prove nothing extra here.
"""
import json

import pytest

import deadcanary.__main__ as cli

CLEAN_REPORT = {
    "project": "somewhere",
    "seconds": 1.0,
    "tests_total": 7, "tests_green": 7,
    "dead_canaries": [], "dead_canaries_provisional": [],
    "coverage_complete": True,
    "never_executed": [],
    "tables_corrupted": [], "tables_available": [],
    "mutations_planned": 4, "mutations_applied": 4, "mutations_noop": 0,
    "mutations_undone": 0, "mutations_missed": 0,
    "outcomes": [],
    "killers": {}, "unreliable_killers": [],
    "corruptions": [],
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "dbt_project.yml").write_text("name: p\n", encoding="utf-8")
    # DbtProject.__init__ resolves a real warehouse file via glob before hunt() is ever
    # called -- it does not open it, so an empty file satisfies construction without
    # needing a real duckdb database, and hunt() being monkeypatched below means nothing
    # downstream ever tries to read it for real.
    (root / "warehouse.duckdb").write_bytes(b"")
    monkeypatch.setattr(cli, "hunt", lambda *a, **k: dict(CLEAN_REPORT))
    return root


def _stdout_is_pure_json(capsys):
    out = capsys.readouterr()
    parsed = json.loads(out.out)
    return parsed, out.err


def test_json_plus_expect_dead_keeps_stdout_pure(project, capsys):
    code = cli.main([str(project), "--json", "--expect-dead", "0"])
    parsed, err = _stdout_is_pure_json(capsys)
    assert code == 0
    assert parsed["tests_green"] == 7
    assert "as expected" in err, "the human status line disappeared instead of moving to stderr"


def test_json_plus_baseline_first_run_keeps_stdout_pure(project, capsys):
    baseline = project.parent / "baseline.json"
    code = cli.main([str(project), "--json", "--baseline", str(baseline)])
    parsed, err = _stdout_is_pure_json(capsys)
    assert code == 0
    assert parsed["dead_canaries"] == []
    assert "no baseline yet" in err


def test_json_plus_baseline_regression_keeps_stdout_pure(project, capsys, monkeypatch):
    baseline = project.parent / "baseline.json"
    baseline.write_text(json.dumps({"dead_canaries": 0}), encoding="utf-8")
    report = dict(CLEAN_REPORT, dead_canaries=["some_test"])
    monkeypatch.setattr(cli, "hunt", lambda *a, **k: report)

    code = cli.main([str(project), "--json", "--baseline", str(baseline)])
    parsed, err = _stdout_is_pure_json(capsys)

    assert code == 1
    assert parsed["dead_canaries"] == ["some_test"]
    assert "worse" in err.lower()


def test_without_json_the_status_line_still_prints_to_stdout(project, capsys):
    """The guard: this is a stream fix, not a feature removal. Plain mode is untouched."""
    code = cli.main([str(project), "--expect-dead", "0"])
    out = capsys.readouterr()
    assert code == 0
    assert "as expected" in out.out, "the ordinary (non-JSON) success message moved to stderr"
