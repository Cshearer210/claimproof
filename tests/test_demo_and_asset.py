"""The demo is the README's hero image, so it is a shipped artefact, not a toy.

Two things go wrong with an asset generated from a demo, and neither looks
wrong: the demo loses an act and the image quietly shows a story that no longer
runs, or the demo GAINS acts and the image keeps showing the same fraction while
its caption says something that is no longer true. The renderer already refused
the first. These cover the second.
"""
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RENDERER = REPO / "tools" / "render_demo_svg.py"

sys.path.insert(0, str(RENDERER.parent))


def _demo_output():
    p = subprocess.run([sys.executable, "-m", "claimproof.demo"],
                       cwd=REPO, capture_output=True, text=True, timeout=300,
                       env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin",
                            "HOME": str(pathlib.Path.home())})
    return p.returncode, p.stdout


def test_the_demo_runs_clean():
    """Every act asserts against the real code, so a non-zero exit is a real defect."""
    code, out = _demo_output()
    assert code == 0, out[-2000:]
    assert "Nothing above was mocked" in out


def test_the_demo_still_shows_every_capability_it_claims_to():
    """A capability that falls out of the demo stops being demonstrated silently."""
    _, out = _demo_output()
    for phrase in ("checked against what was actually asked",   # the ledger
                   "never been made to fail",                   # the gate contract
                   "UNKNOWN is not a pass",                     # the harness
                   "still prove nothing",                       # the audit
                   "stays red until something proves it is gone"):   # the register
        assert phrase in out, f"the demo no longer shows: {phrase!r}"


def test_the_readme_caption_names_the_real_number_of_acts():
    """The caption is the sentence a reader believes, and it goes stale in silence."""
    import render_demo_svg as r

    _, out = _demo_output()
    total = r.act_total(out.splitlines())
    assert total >= 8, f"the demo prints only {total} acts"
    why = r.caption_disagrees(REPO / "README.md", total)
    assert not why, why


def test_the_caption_check_fires_on_a_stale_caption(tmp_path):
    """The other direction, against a synthetic README rather than the real one."""
    import render_demo_svg as r

    stale = tmp_path / "README.md"
    stale.write_text("*The first four acts of `python -m claimproof.demo`, drawn live.*\n")
    assert r.caption_disagrees(stale, 8), "a caption naming no total was accepted"

    right = tmp_path / "ok.md"
    right.write_text("*The first four of eight acts of `python -m claimproof.demo`.*\n")
    assert not r.caption_disagrees(right, 8), "a correct caption was rejected"


def test_a_demo_with_no_numbered_acts_is_not_policed():
    """deadcanary's demo has no acts; the check must not invent a requirement."""
    import render_demo_svg as r

    assert r.act_total(["some line", "another"]) == 0
    assert not r.caption_disagrees(REPO / "README.md", 0)


@pytest.mark.parametrize("lines,expected", [
    (["1. a", "2. b", "3. c"], 3),
    (["1. a", "1. a again", "2. b"], 2),          # the same act twice is one act
    (["not an act", "  1. indented is not an act"], 0),
    (["1.no space after the dot"], 0),
])
def test_act_counting_is_exact(lines, expected):
    import render_demo_svg as r

    assert r.act_total(lines) == expected


def test_the_committed_svg_matches_a_fresh_render():
    """An asset that has drifted from the code is the defect this repo is about."""
    import render_demo_svg as r

    svg = REPO / "assets" / "demo.svg"
    assert svg.exists(), "the README's hero image is not on disk"
    before = svg.read_text(encoding="utf-8")
    code = r.main([])
    assert code == 0, "the renderer refused; the asset cannot be trusted"
    assert svg.read_text(encoding="utf-8") == before, (
        "assets/demo.svg is stale -- run tools/render_demo_svg.py and commit the result")
