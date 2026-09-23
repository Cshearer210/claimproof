"""GroundTruth proven in BOTH directions: it fires on a fabricated artifact and stays quiet on a
real one -- and its own selftest is hermetic (an absolute temp world), so it needs no project."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from claimproof.ground_truth import GroundTruth


def test_selftest_passes_both_directions():
    assert len(GroundTruth().verify()) == 5   # 2 bad, 3 guard, no SelftestError


def test_flags_missing_and_nearmiss_but_not_real(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "summary.json").write_text("{}")
    g = GroundTruth(root=str(tmp_path))
    assert g.inspect("Created config/settings.yaml with the values.")      # not written
    assert g.inspect("See results in output/summary.json.")               # near-miss
    assert not g.inspect("The results are in outputs/summary.json.")       # real -> quiet
    assert not g.inspect("Fixed the parser, tests pass.")                  # no path -> quiet


def test_placeholder_body(tmp_path):
    (tmp_path / "h.py").write_text("def h():\n    raise NotImplementedError\n")
    (tmp_path / "r.py").write_text("def h():\n    return 1\n")
    g = GroundTruth(root=str(tmp_path))
    assert g.inspect("Implemented the handler in h.py.")     # placeholder -> flag
    assert not g.inspect("Implemented the handler in r.py.") # real -> quiet
