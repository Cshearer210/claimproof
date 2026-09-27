"""ground_truth: the inspect() branches test_ground_truth.py did not reach, and runtime_findings
(the fabricated-exit-code detector) which had NO test at all -- a core claimproof feature.

Took ground_truth from 46% mutation. These are real logic branches, not equivalent mutants."""
from claimproof.ground_truth import GroundTruth


def test_file_line_reference_is_not_flagged(tmp_path):
    # core.py:41 is a code LOCATION, not an artifact claim -> quiet (kills the L92-93 skip)
    g = GroundTruth(root=str(tmp_path))
    assert not g.inspect("Created the fix in core.py:41 and it works.")


def test_token_without_a_separator_is_ignored(tmp_path):
    g = GroundTruth(root=str(tmp_path))
    assert not g.inspect("Created something today.")     # no path-shaped token


def test_same_missing_token_is_reported_once(tmp_path):
    g = GroundTruth(root=str(tmp_path))
    f = g.inspect("Created a/b.py. Also wrote a/b.py again.")
    assert len(f) == 1                                   # dedup: kills L86 'tok in seen'


def test_runtime_findings_catches_a_fabricated_exit_code():
    g = GroundTruth()

    class RT:
        def __init__(self, claimed, real):
            self._c, self._r = claimed, real
        def claimed_exit(self, text):
            return self._c
        def real_exit(self):
            return self._r

    assert g.runtime_findings("x", None) == []            # no adapter -> [] (L159)
    assert len(g.runtime_findings("claims exit 0", RT(0, 1))) == 1   # claimed != real (L164)
    assert g.runtime_findings("ok", RT(0, 0)) == []       # equal -> quiet
    assert g.runtime_findings("ok", RT(None, 1)) == []    # claimed unknown -> quiet
