"""evidence.path_for: a session id arrives from someone else's runtime, so it must become a
filename and never a path. This is a security branch (path traversal) and it was untested."""
import os

from claimproof import evidence


def test_path_for_sanitises_a_traversal_session_id():
    p = evidence.path_for("../../.bashrc")
    base = os.path.basename(p)
    # the traversal is defeated by removing the SEPARATORS -- leftover dots in a filename
    # cannot escape a directory without a "/".
    assert "/" not in base and os.sep not in base
    assert p == os.path.join(evidence.store_dir(), base)


def test_path_for_empty_id_becomes_unknown():
    p = evidence.path_for("")                       # kills the `or "unknown"` fallback
    assert os.path.basename(p) == "unknown.receipts"
