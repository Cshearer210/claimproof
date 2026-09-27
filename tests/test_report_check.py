"""`claimproof check`: machine-readable output, config select/ignore, inline suppression, plugins."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from claimproof import report   # noqa: E402


def test_flags_unbacked_and_emits_json():
    pairs = report.check("Done. Everything works now.")
    names = {n for n, _ in pairs}
    assert "UnbackedClaims" in names
    doc = json.loads(report.to_json(pairs))
    assert doc["tool"] == "claimproof" and doc["findings"]


def test_sarif_shape():
    doc = json.loads(report.to_sarif(report.check("Done. All tests pass.")))
    assert doc["version"] == "2.1.0" and doc["runs"][0]["results"]


def test_ground_truth_via_root(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "summary.json").write_text("{}")
    pairs = report.check("Created config/settings.yaml with the values.", root=str(tmp_path))
    assert "GroundTruth" in {n for n, _ in pairs}


def test_config_ignore(tmp_path):
    (tmp_path / ".claimproof.json").write_text(json.dumps({"ignore": ["UnbackedClaims"]}))
    pairs = report.check("Done. Everything works now.", root=str(tmp_path))
    assert "UnbackedClaims" not in {n for n, _ in pairs}


def test_inline_suppression():
    quiet = report.check("Done. Everything works now.  # claimproof: allow UnbackedClaims")
    assert "UnbackedClaims" not in {n for n, _ in quiet}


def test_quiet_on_honest_reply():
    pairs = report.check("Fixed the parser.\n$ pytest -q\n12 passed\nSee core.py:41.")
    assert not pairs
