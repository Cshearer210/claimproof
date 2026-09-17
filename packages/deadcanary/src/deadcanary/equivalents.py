"""Corruptions that changed the data and that no correct test could have caught.

In mutation testing this is the *equivalent mutant* problem: a change that is
semantically identical to the original, so no test can distinguish it, and every
tool reports it as an escape forever. Deciding it automatically is undecidable in
general -- and no tool in this field does it -- so this is the manual version:
you declare one, in writing, with a reason.

⛔ **THE DANGER IS OBVIOUS AND THE DESIGN IS SHAPED BY IT.** A file that removes
findings from your own score is the single easiest way to manufacture a good one.
Three rules make that hard to do quietly:

1. **A declaration with no reason is refused.** Not a warning -- refused. "why"
   is the entire artefact; without it this is just a list of things to ignore.
2. **The raw number is always printed beside the adjusted one.** Nothing here
   ever replaces a count. "10 uncaught, 2 of them declared equivalent" is the
   shape; "8 uncaught" never appears alone.
3. **A declaration that matches nothing in the run is reported as STALE.** A
   file full of exclusions for corruptions that no longer exist is how a score
   stays green while the project moves underneath it.

The format is deliberately boring -- JSON, beside the project:

    {"blank_required on raw_orders.notes": {
        "why": "notes is free text with no downstream consumer; a null there is
                indistinguishable from an empty string by design",
        "declared_by": "chris", "declared_at": "2026-09-17"}}
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

__all__ = ["Equivalence", "EQUIVALENTS_NAME", "InvalidDeclaration", "load",
           "partition", "render_equivalents"]

#: Beside the project it describes, like the claims store.
EQUIVALENTS_NAME = "deadcanary-equivalents.json"


class InvalidDeclaration(ValueError):
    """A declaration that cannot be trusted, which is worse than none at all."""


@dataclasses.dataclass(frozen=True)
class Equivalence:
    key: str
    why: str
    declared_by: str = ""
    declared_at: str = ""

    def __str__(self) -> str:
        who = " -- %s" % self.declared_by if self.declared_by else ""
        when = ", %s" % self.declared_at if self.declared_at else ""
        return "%s%s%s\n      %s" % (self.key, who, when, self.why)


def load(root: Path | str, name: str = EQUIVALENTS_NAME) -> dict[str, Equivalence]:
    """Read the declarations. A missing file is simply none of them.

    Every parse failure raises rather than returning an empty dict: a file that
    exists and cannot be read must never look identical to no file at all --
    that is the same absent-versus-fine confusion this whole project is about.
    """
    path = Path(root) / name
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidDeclaration(
            "%s exists but cannot be read (%s). Refusing to treat an unreadable "
            "exclusion file as an empty one." % (path, exc)) from exc
    if not isinstance(raw, dict):
        raise InvalidDeclaration(
            "%s must hold an object mapping a corruption to its reason, found %s"
            % (path, type(raw).__name__))

    out: dict[str, Equivalence] = {}
    for key, body in raw.items():
        if isinstance(body, str):          # a bare string is a reason, and that is fine
            body = {"why": body}
        if not isinstance(body, dict):
            raise InvalidDeclaration(
                "%s: entry %r must be an object or a reason string" % (path, key))
        why = str(body.get("why") or "").strip()
        if len(why) < 15:
            raise InvalidDeclaration(
                "%s: %r is declared equivalent with no real reason given. A reason "
                "is the entire point of this file -- without one it is a list of "
                "findings to ignore." % (path, key))
        out[str(key)] = Equivalence(str(key), why,
                                    str(body.get("declared_by") or ""),
                                    str(body.get("declared_at") or ""))
    return out


def partition(report: dict, declared: dict[str, Equivalence]):
    """Split the uncaught corruptions into genuine escapes and declared equivalents.

    Returns (escapes, excluded, stale) -- all three, because reporting only the
    first would be exactly the quiet shrinking this module is built to prevent.
    """
    from deadcanary.matrix import kill_matrix

    m = kill_matrix(report)
    uncaught = list(m.uncaught)
    excluded = [declared[k] for k in uncaught if k in declared]
    escapes = [k for k in uncaught if k not in declared]
    seen = set(m.caught_by)
    stale = [e for k, e in declared.items() if k not in seen]
    return escapes, excluded, stale


def render_equivalents(report: dict, declared: dict[str, Equivalence]) -> str:
    escapes, excluded, stale = partition(report, declared)
    total = len(escapes) + len(excluded)
    out = ["", "  UNCAUGHT CORRUPTIONS, after declared equivalents", "  " + "-" * 70]
    # The raw number first, always. Nothing here replaces a count.
    out.append("  %d corruption(s) nothing caught. %d declared semantically equivalent, "
               "so %d remain unexplained." % (total, len(excluded), len(escapes)))
    if excluded:
        out.append("")
        out.append("  Declared equivalent -- excluded from the score, on the record:")
        for e in excluded:
            out.append("    ~ %s" % e)
    if escapes:
        out.append("")
        out.append("  Still unexplained:")
        for k in escapes:
            out.append("    ! %s" % k)
    if stale:
        out.append("")
        out.append("  %d declaration(s) match nothing in this run -- STALE, and a stale "
                   "exclusion is how a score stays green while the project moves:"
                   % len(stale))
        for e in stale:
            out.append("    ? %s" % e.key)
    return "\n".join(out)


def selftest() -> None:
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="deadcanary-equiv-"))
    report = {"corruptions": [
        {"name": "blank_required", "table": "raw", "column": "notes",
         "verdict": "survived", "caught_by": []},
        {"name": "drop_rows", "table": "raw", "column": "id",
         "verdict": "survived", "caught_by": []},
        {"name": "duplicate_key", "table": "raw", "column": "id",
         "verdict": "killed", "caught_by": ["unique_raw_id"]},
    ]}

    assert load(d) == {}, "no file means no declarations"

    good = {"blank_required on raw.notes": {
        "why": "notes is free text with no downstream consumer, so a null and an "
               "empty string are indistinguishable by design",
        "declared_by": "chris", "declared_at": "2026-09-17"}}
    (d / EQUIVALENTS_NAME).write_text(json.dumps(good), encoding="utf-8")
    declared = load(d)
    escapes, excluded, stale = partition(report, declared)
    assert escapes == ["drop_rows on raw.id"], escapes
    assert len(excluded) == 1 and not stale, (excluded, stale)

    text = render_equivalents(report, declared)
    assert "2 corruption(s) nothing caught" in text, text   # the RAW number survives
    assert "1 remain unexplained" in text, text

    # a reason-free declaration is REFUSED, not warned about
    (d / EQUIVALENTS_NAME).write_text(json.dumps({"drop_rows on raw.id": {"why": "n/a"}}),
                                      encoding="utf-8")
    try:
        load(d)
        raise AssertionError("a declaration with no real reason must be refused")
    except InvalidDeclaration as exc:
        assert "no real reason" in str(exc), exc

    # an unreadable file is never an empty one
    (d / EQUIVALENTS_NAME).write_text("{not json", encoding="utf-8")
    try:
        load(d)
        raise AssertionError("an unreadable exclusion file must not read as none")
    except InvalidDeclaration:
        pass

    # a declaration matching nothing is STALE and is said out loud
    (d / EQUIVALENTS_NAME).write_text(json.dumps({"blank_required on gone.column": {
        "why": "this column was removed from the warehouse months ago"}}), encoding="utf-8")
    _, _, stale = partition(report, load(d))
    assert len(stale) == 1, stale
    assert "STALE" in render_equivalents(report, load(d))

    print("equivalents: selftest PASS (10 checks, incl. 3 refusals)")


if __name__ == "__main__":
    selftest()
