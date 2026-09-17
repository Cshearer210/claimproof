"""Refuse to corrupt anything that looks live.

This tool's method is to damage real data on purpose and see whether the checks
notice. Pointed at the wrong warehouse, that is not a test -- it is an incident.
The rule "only ever run this against a development warehouse" was written in the
documentation and nowhere else, which makes it a rule that holds right up until
somebody is in a hurry.

⚠ **THIS EXISTS BECAUSE THE FAILURE IS REAL, not hypothetical.** In the system
this pattern was taken from, a break-on-purpose test reached a live customer
spreadsheet. The fix there was the same as the fix here: stop asking people to
remember, and refuse at the door.

**Calibrated to refuse rarely.** A pre-flight that blocks ordinary development
gets removed within the week, and a removed check protects nothing -- so only
unambiguous signals count, and the reason is always named and always overridable
by someone who has read it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["LooksLive", "OVERRIDE_ENV", "live_reasons", "assert_not_live"]

#: Set this to run anyway. Deliberately long and awkward to type: an override
#: that is easy to reach for is an override nobody thinks about.
OVERRIDE_ENV = "DEADCANARY_I_KNOW_THIS_IS_NOT_PRODUCTION"

#: Target/profile names that mean production in every project anyone has met.
LIVE_TARGETS = {"prod", "production", "live", "prd"}

#: Path segments that say the same thing. Word-bounded on purpose: a project at
#: `~/code/reproduction-cases/` is not production, and matching it would be the
#: over-firing that gets this deleted.
LIVE_PATH = re.compile(r"(?i)(?:^|[^a-z])(prod|production|live|prd)(?:[^a-z]|$)")


class LooksLive(RuntimeError):
    """Refused before anything was touched. Never raised after a corruption."""


def _profile_target(root: Path) -> str | None:
    """The target name the project's own profile selects, or None if unknown.

    Unknown is not "development": it simply contributes no signal, and the other
    checks stand on their own.
    """
    profiles = root / "profiles.yml"
    if not profiles.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(profiles.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    for body in data.values():
        if isinstance(body, dict) and body.get("target"):
            return str(body["target"])
    return None


def live_reasons(root: Path | str, database: Path | str) -> list[str]:
    """Every reason this looks like production. Empty means no signal fired.

    Returns reasons rather than a boolean so the refusal can say WHICH one, and
    so a caller can show them. A refusal nobody can act on gets overridden
    blindly, which is the same as not having one.
    """
    root, database = Path(root), Path(database)
    reasons: list[str] = []

    target = _profile_target(root)
    if target and target.strip().lower() in LIVE_TARGETS:
        reasons.append(
            "the project's profile selects the %r target, and this corrupts real "
            "rows in whatever it is pointed at" % target)

    m = LIVE_PATH.search(str(database))
    if m:
        reasons.append(
            "the warehouse path names %r (%s)" % (m.group(1), database))

    return reasons


def assert_not_live(root: Path | str, database: Path | str) -> None:
    """Raise `LooksLive` unless this is safe, or the override is set.

    Called before the first corruption and never after one -- a refusal that
    arrives once damage is done is not a refusal.
    """
    if os.environ.get(OVERRIDE_ENV):
        return
    reasons = live_reasons(root, database)
    if not reasons:
        return
    raise LooksLive(
        "refusing to corrupt what looks like a production warehouse.\n  "
        + "\n  ".join("- " + r for r in reasons)
        + "\n\nThis tool damages real rows on purpose to see whether your checks "
          "notice. Against production that is an incident, not a test.\n"
          "If this really is a development copy, set %s=1 and run again."
        % OVERRIDE_ENV)


def selftest() -> None:
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="deadcanary-safety-"))
    dev = d / "dev.duckdb"
    dev.touch()

    # quiet on an ordinary development project -- the direction that matters most,
    # because a check that fires on normal work is one that gets deleted
    assert live_reasons(d, dev) == [], live_reasons(d, dev)
    assert_not_live(d, dev)

    # a production-looking path
    prod = d / "warehouse_prod.duckdb"
    prod.touch()
    assert live_reasons(d, prod), "a path naming prod must be caught"

    # a profile selecting prod
    (d / "profiles.yml").write_text("my_project:\n  target: prod\n  outputs:\n    prod:\n"
                                    "      type: duckdb\n", encoding="utf-8")
    reasons = live_reasons(d, dev)
    assert any("target" in r for r in reasons), reasons

    # and it REFUSES, before anything is touched
    try:
        assert_not_live(d, dev)
        raise AssertionError("it must refuse when the profile says prod")
    except LooksLive as exc:
        assert "production" in str(exc)

    # the override works, and is the only way through
    os.environ[OVERRIDE_ENV] = "1"
    try:
        assert_not_live(d, dev)
    finally:
        del os.environ[OVERRIDE_ENV]

    # words that merely CONTAIN a live word are not live -- the over-fire that
    # would get this removed
    for safe in ("reproduction-cases", "productivity", "aliveness", "prodigy"):
        p = d / ("%s.duckdb" % safe)
        assert not LIVE_PATH.search(str(p)), safe

    print("safety: selftest PASS (9 checks, incl. 4 that must NOT fire)")


if __name__ == "__main__":
    selftest()
