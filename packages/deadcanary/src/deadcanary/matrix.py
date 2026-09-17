"""Which test caught which corruption -- and which corruption only ONE test caught.

`render()` answers "how many tests cannot fail". That is the headline, and it is
the least the data can say. Every run already records, per corruption, exactly
which tests failed because of it (`corruptions[].caught_by`), and that table
answers questions a count cannot:

* **A corruption only one test catches is a single point of failure.** Delete
  that test -- or let it go green for an unrelated reason -- and real damage
  stops being detected, while the dead-canary count does not move at all.
* **A corruption five tests catch is redundancy**, which is fine, but it means
  five tests are telling you one thing and the suite is narrower than its size
  suggests.
* **A test that only ever catches what three other tests also catch** is not
  dead, so nothing flags it, and it is still carrying no weight of its own.

None of that is visible in "6 of 20 tests are dead canaries", and all of it is
already in the report.
"""
from __future__ import annotations

import dataclasses

__all__ = ["Matrix", "kill_matrix", "render_matrix", "count_without_examples"]


@dataclasses.dataclass(frozen=True)
class Matrix:
    """The kill matrix, already interpreted. Counting is the caller's job nowhere."""

    #: corruption name -> the tests that caught it (sorted)
    caught_by: dict[str, list[str]]
    #: test -> the corruptions it caught (sorted)
    catches: dict[str, list[str]]
    #: corruptions exactly one test caught -> that test
    single_point: dict[str, str]
    #: corruptions nothing caught
    uncaught: list[str]
    #: green tests that caught nothing at all
    dead: list[str]
    #: tests whose every catch is also caught by another test
    no_unique_catch: list[str]

    @property
    def measured(self) -> int:
        """The denominator. A verdict without one is not checkable."""
        return len(self.caught_by)


def _label(corruption: dict) -> str:
    """One corruption's identity: its name AND what it was applied to.

    Keying on the name alone was wrong and it under-reported badly -- a real run
    applied `blank_required` to four different columns, four genuinely different
    questions put to the suite, and the matrix collapsed them into one row. It
    reported 7 corruptions where the run had applied 14, which is the shrinking
    denominator this project argues against, committed by its own report.
    """
    where = ".".join(str(corruption.get(k) or "") for k in ("table", "column")).strip(".")
    return "%s on %s" % (corruption["name"], where) if where else corruption["name"]


def kill_matrix(report: dict) -> Matrix:
    """Build the matrix from a report `hunt()` produced.

    Only corruptions that were actually APPLIED count. A corruption that changed
    no rows, or that a rebuild wiped before any test ran, was never a question
    put to the suite -- including it would credit tests for surviving something
    that never happened.
    """
    caught_by: dict[str, list[str]] = {}
    for c in report.get("corruptions", []):
        if c.get("verdict") not in ("killed", "survived", "KILLED", "SURVIVED"):
            continue
        caught_by[_label(c)] = sorted(c.get("caught_by") or [])

    catches: dict[str, list[str]] = {}
    for name, tests in caught_by.items():
        for t in tests:
            catches.setdefault(t, []).append(name)
    for t in catches:
        catches[t] = sorted(catches[t])

    single_point = {n: ts[0] for n, ts in caught_by.items() if len(ts) == 1}
    uncaught = sorted(n for n, ts in caught_by.items() if not ts)

    dead = sorted(report.get("dead_canaries") or report.get("dead_canaries_provisional") or [])

    # A test carries no unique weight when every corruption it catches is also
    # caught by somebody else. Not a defect -- but it is the honest answer to
    # "what would we lose by deleting this test", and nothing else reports it.
    no_unique = sorted(
        t for t, names in catches.items()
        if names and all(len(caught_by[n]) > 1 for n in names))

    return Matrix(caught_by=caught_by, catches=catches, single_point=single_point,
                  uncaught=uncaught, dead=dead, no_unique_catch=no_unique)


def render_matrix(report: dict, width: int = 46) -> str:
    m = kill_matrix(report)
    out: list[str] = []
    add = out.append

    if not m.measured:
        # Law: a verdict from a check that could not look is never a clean one.
        return ("\n  KILL MATRIX: nothing to show -- no corruption was actually applied, "
                "so no test was asked a question.")

    add("")
    add("  KILL MATRIX -- which test caught which corruption")
    add("  " + "-" * 70)
    for name in sorted(m.caught_by):
        tests = m.caught_by[name]
        if not tests:
            mark, who = "!", "NOTHING CAUGHT IT"
        elif len(tests) == 1:
            mark, who = "1", "%s  (only this one)" % tests[0]
        else:
            mark, who = str(len(tests)), ", ".join(tests[:3]) + (
                " +%d more" % (len(tests) - 3) if len(tests) > 3 else "")
        add("  %s  %-*s %s" % (mark, width, name[:width], who))

    add("")
    add("  %d corruption(s) measured, %d caught by exactly one test, %d caught by nothing."
        % (m.measured, len(m.single_point), len(m.uncaught)))

    if m.single_point:
        add("")
        add("  SINGLE POINTS OF FAILURE -- lose this test and this damage stops being seen:")
        for name, test in sorted(m.single_point.items()):
            add("    %s  is the only thing that catches  %s" % (test, name))

    if m.no_unique_catch:
        add("")
        add("  %d test(s) catch nothing that another test does not also catch:"
            % len(m.no_unique_catch))
        for t in m.no_unique_catch:
            add("    - %s" % t)
        add("  Not dead -- but deleting one would not change what this suite can detect.")

    return "\n".join(out)


def count_without_examples(text: str) -> list[str]:
    """Chris's own standing law, applied to this tool's own output.

    A count with no named examples cannot be checked by anyone reading it: a
    wrong count and a right count are the same shape, a number. A wrong EXAMPLE
    is obvious on sight. So a line claiming N dead canaries must be accompanied
    by the names, and this is what refuses one that is not.

    Returns the offending lines. Empty means the output carries its examples.
    """
    import re
    claim = re.compile(r"(?i)\b(\d+)\s+(?:of\s+\d+\s+)?[\w ]*?"
                       r"(dead canaries?|tests? (?:that )?cannot fail)")
    lines = text.splitlines()
    bad = []
    for i, line in enumerate(lines):
        m = claim.search(line)
        if not m or int(m.group(1)) == 0:
            continue
        # The names may follow within a short window -- a heading then a list is
        # the normal shape and must not be flagged.
        window = "\n".join(lines[i:i + 3 + int(m.group(1)) * 2])
        if re.search(r"(?m)^\s*[x!\-*]\s+\S", window) or "not_null" in window:
            continue
        bad.append(line.strip())
    return bad


def selftest() -> None:
    """Both directions. A matrix that can only ever say one thing proves nothing."""
    report = {
        "dead_canaries": ["sleepy_test"],
        "corruptions": [
            {"name": "null_out_customer_id", "verdict": "killed",
             "caught_by": ["not_null_customers_id"]},
            {"name": "duplicate_order_rows", "verdict": "killed",
             "caught_by": ["unique_orders_id", "row_count_orders"]},
            {"name": "blank_every_email", "verdict": "survived", "caught_by": []},
            {"name": "never_applied", "verdict": "noop", "caught_by": []},
        ],
    }
    m = kill_matrix(report)
    assert m.measured == 3, ("a noop corruption was never a question put to the suite", m.measured)
    assert m.single_point == {"null_out_customer_id": "not_null_customers_id"}, m.single_point
    assert m.uncaught == ["blank_every_email"], m.uncaught
    assert m.dead == ["sleepy_test"], m.dead
    assert m.no_unique_catch == ["row_count_orders", "unique_orders_id"], m.no_unique_catch

    # two corruptions sharing a NAME but hitting different columns are two
    # questions, not one -- the bug that under-reported a real run by half
    split = {"dead_canaries": [], "corruptions": [
        {"name": "blank_required", "table": "raw_orders", "column": "id",
         "verdict": "survived", "caught_by": []},
        {"name": "blank_required", "table": "raw_orders", "column": "amount",
         "verdict": "killed", "caught_by": ["not_null_amount"]},
    ]}
    sm = kill_matrix(split)
    assert sm.measured == 2, ("same name, different column, two questions", sm.measured)
    assert "blank_required on raw_orders.id" in sm.caught_by, sm.caught_by

    text = render_matrix(report)
    assert "SINGLE POINTS OF FAILURE" in text, text
    assert "NOTHING CAUGHT IT" in text, text
    assert "3 corruption(s) measured" in text, text

    # a run where nothing was applied must NOT render a confident empty matrix
    empty = render_matrix({"corruptions": [{"name": "x", "verdict": "noop", "caught_by": []}]})
    assert "nothing to show" in empty, empty

    # the named-examples rule, both directions
    bad = "  4 of 20 green tests are DEAD CANARIES (20%)\n  Moving on.\n"
    good = ("  4 of 20 green tests are DEAD CANARIES (20%)\n\n  Tests that cannot fail:\n"
            "    x not_null_a\n    x not_null_b\n")
    assert count_without_examples(bad), "a bare count must be refused"
    assert not count_without_examples(good), "a count WITH its names must pass"
    assert not count_without_examples("  0 dead canaries"), "zero needs no examples"

    print("matrix: selftest PASS (13 checks, both directions)")


if __name__ == "__main__":
    selftest()
