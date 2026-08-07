"""The rename must break nobody: `agentattest` forwards to `claimproof`.

Code written against the old name -- including hooks installed in other
people's settings before the rename -- keeps working, or the rename shipped
a silent outage to every existing user.
"""
import json
import subprocess
import sys

import claimproof
from claimproof.claude_code import MARKER, OLD_MARKER, install, uninstall


def test_old_package_forwards_to_new():
    import agentattest
    assert agentattest.__version__ == claimproof.__version__
    assert agentattest.Harness is claimproof.Harness


def test_old_submodule_imports_are_the_same_objects():
    from agentattest.gates import UnbackedClaims as old
    from claimproof.gates import UnbackedClaims as new
    assert old is new

    from agentattest.ledger import Ledger as old_l
    from claimproof.ledger import Ledger as new_l
    assert old_l is new_l


def test_a_hook_installed_under_the_old_name_still_runs():
    """`python -m agentattest.claude_code` sits in real settings files."""
    r = subprocess.run(
        [sys.executable, "-m", "agentattest.claude_code"],
        input="not json", capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    assert "gate did not run" in r.stderr  # announced fail-open = it executed


def test_install_upgrades_a_pre_rename_entry_instead_of_doubling(tmp_path):
    path = tmp_path / "settings.json"
    old = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": f'"python" {OLD_MARKER}'}]}]}}
    path.write_text(json.dumps(old), encoding="utf-8")

    msg = install(path)
    assert "upgraded 1 pre-rename entry" in msg
    text = path.read_text(encoding="utf-8")
    assert MARKER in text
    assert OLD_MARKER not in text
    data = json.loads(text)
    assert len(data["hooks"]["Stop"]) == 1  # upgraded, not doubled


def test_uninstall_also_removes_a_pre_rename_entry(tmp_path):
    path = tmp_path / "settings.json"
    old = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": f'"python" {OLD_MARKER}'}]}]}}
    path.write_text(json.dumps(old), encoding="utf-8")

    assert "uninstalled" in uninstall(path)
    assert "hooks" not in json.loads(path.read_text(encoding="utf-8"))
