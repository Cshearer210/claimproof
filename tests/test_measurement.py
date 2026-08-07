"""The published finding rests on one script. Its guards are tested like code.

FINDINGS.md says 69.8% of confident agent claims were false. That number is
only worth the guards behind it, and those guards have already failed once:
the first real run died at 31 MB of a 94 MB download, the cache would have
accepted the half-file forever, and the wrapper reported success. A tool that
cannot detect its own truncated input is not a measurement instrument.

These run offline in about two seconds. Nothing here downloads anything.
"""
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "measure_unbacked_claims.py"

pytestmark = pytest.mark.skipif(
    not TOOL.is_file(),
    reason="tools/ is not shipped in the wheel, so this only runs from a checkout",
)


def load():
    """Import the script by path -- it lives in tools/, not the package."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("measure_unbacked_claims", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_selftest_passes_and_says_so():
    r = subprocess.run([sys.executable, str(TOOL), "--selftest"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST PASS" in r.stdout
    assert "HALF-DOWNLOADED file is refused" in r.stdout


def test_a_truncated_download_is_refused(tmp_path):
    """The exact failure: a shard that stopped arriving part-way through."""
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    m = load()

    whole = tmp_path / "whole.parquet"
    pq.write_table(pa.table({"x": list(range(2000))}), whole)
    half = tmp_path / "half.parquet"
    half.write_bytes(whole.read_bytes()[: whole.stat().st_size // 2])

    assert m._usable(whole)
    assert not m._usable(half), "a half-download must never pose as cached"
    assert not m._usable(tmp_path / "never_existed.parquet")


def test_an_empty_file_is_refused_not_treated_as_absent(tmp_path):
    m = load()
    empty = tmp_path / "empty.parquet"
    empty.write_bytes(b"")
    assert not m._usable(empty)


@pytest.mark.parametrize("text,expected", [
    ("The issue is fixed.", True),
    ("All tests pass.", True),
    ("The bug has been resolved.", True),
    ("I think the issue is fixed.", False),      # hedged
    ("This should work now.", False),            # hedged
    ("Let me verify the issue is fixed.", False),  # intent, not a claim
    ("Running the reproduce script.", False),
    ("", False),
])
def test_the_claim_detector_works_in_both_directions(text, expected):
    """A detector that has only ever said yes is not a detector."""
    assert load()._claims_success(text) is expected


def test_the_report_refuses_to_invent_a_denominator():
    """Percentages must be n/a rather than a divide-by-zero or a silent 0%."""
    m = load()
    assert m.pct(0, 0) == "n/a"
    assert m.pct(1, 4) == "25.0%"
