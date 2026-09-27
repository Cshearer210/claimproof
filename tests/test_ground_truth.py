"""GroundTruth proven in BOTH directions: it fires on a fabricated artifact and stays quiet on a
real one -- and its own selftest is hermetic (an absolute temp world), so it needs no project."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from claimproof.ground_truth import GroundTruth


def test_selftest_passes_both_directions():
    assert len(GroundTruth().verify()) == 7   # 3 bad, 4 guard, no SelftestError


def test_a_cited_path_resolves_whichever_separator_it_was_written_with():
    """The bug this pins was invisible on Linux and broke every Windows run.

    `_PATH` matched forward slashes only, so a claim citing a backslash path collapsed to its bare
    basename, resolved against the wrong directory, found nothing, and reported CLEAN -- the silent
    direction this library exists to argue against. CI failed 3 of 491 on every windows job while
    every ubuntu job was green.

    Asserted on the REGEX and on RESOLUTION, so it holds on either OS instead of relying on a
    platform most local runs never exercise. Hermetic: a temp world, no project, no network.
    """
    from claimproof.ground_truth import _PATH

    win = r"C:\work\proj\src\handler.py"
    assert [m.group(1) for m in _PATH.finditer("Implemented it in %s." % win)] == [win], \
        "a Windows path must be captured whole, not collapsed to its basename"
    posix = "/work/proj/src/handler.py"
    assert [m.group(1) for m in _PATH.finditer("Implemented it in %s." % posix)] == [posix]

    # THE 8.3 SHORT NAME, taken verbatim from the shape a GitHub Windows runner actually hands out.
    # The tilde sits MID-NAME, so a character class without it breaks the directory chain and the
    # whole path collapses -- which is precisely how the first attempt at this fix still left every
    # windows job red on the same case.
    short = r"C:\Users\RUNNER~1\AppData\Local\Temp\cpS_zioxve92\handler.py"  # synthetic-path: CI runner shape, not a person's machine
    assert [m.group(1) for m in _PATH.finditer("Implemented it in %s." % short)] == [short], \
        "an 8.3 short name (RUNNER~1) must not break the path"

    # ...and resolution normalises the separator, so a foreign one still finds the real file
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "h.py"), "w") as fh:
            fh.write("def h():\n    raise NotImplementedError\n")
        g = GroundTruth(root=d)
        foreign = "sub\\h.py" if os.sep == "/" else "sub/h.py"
        assert g.inspect("Implemented the handler in %s." % foreign), \
            "a path written with the other separator must still resolve, and flag"


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
