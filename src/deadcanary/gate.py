"""Where deadcanary joins claimproof: "the data tests pass" is a claim, not proof.

CALLED BY: `deadcanary.__main__` (the `--attest` flag), and by anyone wiring
`GreenTestsUnproven` into a claimproof harness or a Claude Code hook.

claimproof exists for one sentence: *a check nobody has ever made fail is not a
check.* It enforces that on gates -- a `Gate` is refused at construction unless
its selftest carries both a case it must catch and a guard case it must leave
alone.

deadcanary asks the same question about somebody's whole dbt test suite, and
answers it by breaking real data instead of using fixtures. So the two fit
together at exactly one seam, and this module is that seam:

    "all 20 dbt tests pass"        <- a claim
    a complete deadcanary run       <- the only thing that makes it mean anything

Two pieces, and the second is the one neither tool has alone:

`GreenTestsUnproven`
    A claimproof gate. Reads a message somebody is about to send, and refuses a
    claim of data-test health when nothing has ever shown those tests can fail.

`attest()`
    Records the proof as a claimproof claim, fingerprinted against the SUITE --
    which tests exist, what they check, which sources feed them. deadcanary
    answers "can these tests fail?" for the suite as it stood at that moment. Add
    a test tomorrow and that answer covers a suite that no longer exists. Nothing
    anywhere would say so; now claimproof reopens the claim and asks for a fresh
    measurement.

The fingerprint deliberately ignores dbt's own run metadata. `manifest.json`
carries a new timestamp and invocation id on every single build, so hashing the
file would reopen the claim after every run -- a checker crying wolf, which gets
switched off within a week, and after that it catches nothing at all.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from claimproof import Case, ClaimBasis, Finding, Gate
from claimproof.basis import Evidence

#: The report deadcanary writes beside the project it measured.
REPORT_NAME = "deadcanary-report.json"

#: How the suite fingerprint is named inside a claimproof claim. One definition,
#: read by `attest`, `current_values` and `recheck` -- a second spelling of this
#: string in any one of them would silently make the claim unjudgeable forever.
SUITE_REF = "dbt:test-suite"

# The claim family this gate polices, and it is deliberately narrow. It has to
# name DATA testing specifically: "all the tests pass" about a Python suite is
# somebody else's business, and a gate that reaches into it would be flagging
# correct work within a day.
_SUBJECT = re.compile(
    r"\b(?:dbt|data\s+test|data\s+tests|data[\s-]quality|data\s+checks?)\b", re.I)

_HEALTH = re.compile(
    r"\b(?:pass|passes|passed|passing|green|clean|healthy|covered|"
    r"no\s+failures|all\s+good|fine)\b", re.I)

# Honest uncertainty is left alone, exactly as claimproof leaves it alone. A gate
# that punishes an admitted hedge teaches people to be vague instead of accurate,
# which costs more than the claim it caught.
_HEDGE = re.compile(
    r"\b(?:should|would|might|may|probably|likely|i\s+think|i\s+believe|"
    r"appears?|seems?|looks\s+like|hopefully|presumably|not\s+checked)\b", re.I)

# The sentence is asking the question rather than answering it. "whether the dbt
# tests can fail" is the reason this tool exists, not a claim to refuse.
_ASKING = re.compile(
    r"\b(?:whether|if|can|could|does|do|is|are)\b[^.!?]{0,60}\b(?:fail|catch|work)\b", re.I)


def suite_fingerprint(manifest: dict) -> str:
    """A fingerprint of what the suite actually TESTS, and nothing else.

    Included: every test's name and what kind of test it is, every model it hangs
    off, and every source. Those are the things whose change invalidates a
    previous measurement.

    Excluded: dbt's run metadata, compiled SQL, timings, invocation ids -- all of
    which move on every build while the suite stays identical.

    Sorted, so two manifests describing the same suite fingerprint the same. dbt
    does not promise key order between versions, and a digest that moves when
    nothing did is the same cry-wolf failure as hashing the timestamp.
    """
    tests, sources = [], []
    for node in (manifest.get("nodes") or {}).values():
        if node.get("resource_type") != "test":
            continue
        kind = (node.get("test_metadata") or {}).get("name", "")
        on = sorted((node.get("depends_on") or {}).get("nodes", []))
        tests.append(f"{node.get('name', '')}|{kind}|{','.join(on)}")
    for node in (manifest.get("sources") or {}).values():
        sources.append(str(node.get("name", "")))

    body = "\n".join(["TESTS"] + sorted(tests) + ["SOURCES"] + sorted(sources))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class GreenTestsUnproven(Gate):
    """Refuse "the data tests pass" until something showed they can fail.

    A data test that has been green every morning for two years is green for one
    of two reasons: the data is healthy, or the test cannot fail. Nobody can tell
    those apart by looking, and the claim reads identically either way.

    >>> GreenTestsUnproven(project=".").inspect("All 316 unit tests pass.")
    []
    """

    name = "GreenTestsUnproven"

    def __init__(self, project: str | Path | None = None,
                 report: str | Path | None = None) -> None:
        super().__init__()
        self.project = Path(project) if project is not None else None
        self._report = Path(report) if report is not None else None

    # -- where the proof would be, if there were any ------------------------
    def report_path(self) -> Path | None:
        if self._report is not None:
            return self._report
        if self.project is not None:
            return self.project / REPORT_NAME
        return None

    def inspect(self, text: str) -> list[Finding]:
        for line_no, line in enumerate(text.splitlines() or [""], start=1):
            if not (_SUBJECT.search(line) and _HEALTH.search(line)):
                continue
            if _HEDGE.search(line) or _ASKING.search(line):
                continue
            problem = self._why_it_is_not_proved()
            if problem:
                return [Finding(problem, line=line_no, excerpt=line.strip()[:90])]
        return []

    def _why_it_is_not_proved(self) -> str:
        """The plain-English reason, or "" when the claim is genuinely backed."""
        path = self.report_path()
        if path is None or not path.is_file():
            return ("these data tests have never been proved able to fail -- no deadcanary "
                    "run backs this. Green is also what a test that cannot fail looks like. "
                    "Run: python -m deadcanary <project>")

        report = _read(path)
        if report is None:
            return (f"{path.name} exists but could not be read, so nothing here proves "
                    f"anything. A report that cannot be parsed is not a measurement.")

        if not report.get("coverage_complete"):
            provisional = report.get("dead_canaries_provisional") or []
            extra = f" ({len(provisional)} look dead so far)" if provisional else ""
            return (f"the deadcanary run did not cover every source{extra}, so it names no "
                    f"dead canaries -- which is not the same as finding none. A partial "
                    f"measurement cannot support this claim.")

        dead = report.get("dead_canaries") or []
        if dead:
            shown = ", ".join(dead[:3]) + (f" and {len(dead) - 3} more" if len(dead) > 3 else "")
            return (f"{len(dead)} of these tests cannot be made to fail by any corruption: "
                    f"{shown}. They are green every morning and protecting nothing.")

        return ""

    # -- proving the gate itself -------------------------------------------
    def selftest_cases(self) -> list[Case]:
        return [
            Case(text="All 20 dbt tests pass. Data quality is covered.",
                 expect_flagged=True, name="green data tests, nothing proving them"),
            Case(text="dbt test: all green, no failures.",
                 expect_flagged=True, name="the same claim in tool-output clothing"),
            Case(text="All 316 unit tests pass. exit=0",
                 expect_flagged=False, name="GUARD: a normal test suite is not this gate's business"),
            Case(text="The dbt tests should pass, but I have not checked.",
                 expect_flagged=False, name="GUARD: an honest hedge is left alone"),
            Case(text="I need to find out whether the dbt tests can fail at all.",
                 expect_flagged=False, name="GUARD: asking the question is not claiming the answer"),
            Case(text="dbt run failed on stg_orders.",
                 expect_flagged=False, name="GUARD: reporting a failure is not claiming health"),
        ]


def attest(project: str | Path, store: str | Path | None = None,
           report: str | Path | None = None) -> ClaimBasis:
    """Record "these data tests were proved able to fail" as a claim that expires.

    The evidence is two things: the report itself, and a fingerprint of the test
    suite it measured. When somebody adds a test, changes what a test checks, or
    wires in a new source, the fingerprint moves and claimproof reopens the claim
    -- because the old measurement now describes a suite that no longer exists.

    Raises when there is no report. Recording a claim against proof that is not
    there would create one nothing can ever re-verify, which is the failure one
    layer below this.
    """
    root = Path(project).resolve()
    report_path = Path(report) if report is not None else root / REPORT_NAME
    if not report_path.is_file():
        raise FileNotFoundError(
            f"no {report_path.name} in {root}. Nothing has measured this project, so "
            f"there is no proof to record. Run: python -m deadcanary {root}")

    manifest = _read(root / "target" / "manifest.json") or {}
    body = _read(report_path) or {}

    basis = ClaimBasis(store, root=root)
    basis.record(
        f"the data tests in {root.name} were proved able to fail "
        f"({body.get('tests_green', '?')} green, {len(body.get('dead_canaries') or [])} dead)",
        evidence=[
            str(report_path.relative_to(root) if report_path.is_relative_to(root)
                else report_path),
            Evidence.value(SUITE_REF, suite_fingerprint(manifest)),
        ],
        claim_id=f"deadcanary:{root.name}",
    )
    return basis


def current_values(project: str | Path) -> dict[str, str]:
    """Today's value for the non-file evidence, read off the project right now.

    claimproof re-checks file evidence itself, but it cannot know what a VALUE is
    supposed to be today -- so a value nobody supplies is reported UNKNOWN rather
    than assumed to hold. This supplies it, and it is the reason `recheck()`
    below exists rather than leaving callers to remember.
    """
    root = Path(project).resolve()
    manifest = _read(root / "target" / "manifest.json") or {}
    return {SUITE_REF: suite_fingerprint(manifest)}


def recheck(project: str | Path, store: str | Path | None = None, echo: bool = True) -> int:
    """Does the proof recorded earlier still describe the suite that exists now?

    **0** it holds -- what was measured is still what is there.
    **1** reopened -- a test, a source, or the report itself has moved since, so
    the old answer covers a suite that no longer exists. Measure again.
    **2** cannot tell.

    This is the half neither tool has alone. deadcanary knows whether the tests
    could fail on the day it ran; claimproof knows when the ground under a claim
    has shifted. Wire this into CI and a new untested source stops being silent.
    """
    root = Path(project).resolve()
    return ClaimBasis(store, root=root).run(values=current_values(root), echo=echo)
