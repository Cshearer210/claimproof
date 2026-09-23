#!/usr/bin/env python3
# CALLED BY: fullcircle.pipeline (the FULL-CIRCLE-OPTIMIZATION orchestrator), and copied verbatim
#            into claimproof, FULL-RESET-GRAPH and SANDBOX-FAN-OUT as their one shared contract.
# FIRES WHEN: any repo emits a finding, and when the orchestrator merges findings from all repos.
"""The one shared contract for the 4 portfolio repos, and the triangulation engine.

WHY THIS IS THE SPINE (Chris, 2026-09-23): "one tool finds things that another missed when looking
in different methods." A finding is identified by WHAT IS WRONG WHERE -- independent of which METHOD
found it -- so two methods that find the same defect collapse to ONE finding with two methods
attached, and a defect only one method saw is visibly less corroborated. That is the product: silent
bugs survive because a single check has one blind spot; several independent methods triangulate them.

THE PORTABILITY RULE (works on unfamiliar systems): a finding keys on a CONCEPT and a behavioural
SIGNAL, never on a label the target system happens to use. `concept` is the abstract thing (a gate,
a test, a claim, a wire); `signal` is the behaviour that proves it (an exit code, a mutation
survived, an empty output store). Rename everything in the target and the finding is unchanged.

No third-party deps on purpose: each repo copies this file, so each stands alone for a recruiter to
run. The SCHEMA is the shared thing, not a shared install.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any

# The abstract concepts every Claude-style system has, however it labels them. A detector maps the
# target's own methods onto these, so a "gate" that the target calls a "guard"/"check"/"hook" is
# still the same concept and still findable.
CONCEPTS = ("gate", "test", "claim", "wire", "definition", "schedule", "instruction",
            "population", "read", "artifact")

# The three honest outcomes -- never let "could not look" read as "clean" (how-we-work law 4).
CLEAN, FOUND, UNKNOWN = 0, 1, 2


@dataclass
class Finding:
    """One defect, identified independently of the method that found it."""
    concept: str                 # one of CONCEPTS -- the abstract thing that is wrong
    defect_class: str            # a class from DEFECT-CLASSES.md (e.g. "absent-looks-like-clean")
    location: str                # file:line, or a structural locator ("call-graph:orphan:mod.f")
    signal: str                  # the BEHAVIOUR keyed on, not a label ("mutation survived")
    evidence: str = ""           # the measured fact, in plain words
    method: str = "unnamed"      # which detection method found it (for triangulation)
    repo: str = ""               # claimproof | full-reset-graph | sandbox-fan-out
    severity: str = "med"        # low | med | high
    confidence: float = 0.5      # this ONE method's confidence, 0..1
    both_directions_proven: bool = False   # fired on known-bad AND stayed quiet on known-good
    ignored_label: str = ""      # a label this detector deliberately did NOT rely on (portability proof)
    fixable_by: str = ""         # which repo/stage can fix it, "" = human decision
    status: str = "found"        # found | verified | fixed | regressed
    extra: dict[str, Any] = field(default_factory=dict)

    def identity(self) -> str:
        """Stable id from WHAT/WHERE, NOT from method -- so two methods dedupe to one finding and
        loop-until-dry re-runs converge instead of re-reporting the same defect forever.

        A detector may set extra['id_key'] when the natural identity of a defect is NOT its location
        string -- e.g. a duplicate whose identity is the DUPLICATED CONTENT, found by two methods
        that list different path-sets. Both then share one id_key and triangulate correctly."""
        idk = self.extra.get("id_key")
        key = ("K\x1f%s\x1f%s" % (self.defect_class, idk)) if idk else \
              ("%s\x1f%s\x1f%s" % (self.concept, self.defect_class, self.location))
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class Triangulated:
    """One defect, with every method that independently found it."""
    identity: str
    concept: str
    defect_class: str
    location: str
    methods: list[str]
    max_confidence: float
    corroboration: int           # how many INDEPENDENT methods found it
    both_directions_any: bool
    findings: list[Finding]

    @property
    def trust(self) -> str:
        # corroboration is the product: >=2 independent methods is the "found what another missed"
        # story; 1 method is a lead to confirm, not yet a claim.
        if self.corroboration >= 2 and self.both_directions_any:
            return "corroborated"
        if self.corroboration >= 2:
            return "multi-method"
        return "single-method"


def triangulate(findings: list[Finding]) -> list[Triangulated]:
    """Collapse findings to defects, attaching every method that found each. The overlap IS the
    value: a defect several methods agree on is trustworthy on an unfamiliar system precisely
    because no single blind spot could hide it."""
    by_id: dict[str, list[Finding]] = {}
    for f in findings:
        by_id.setdefault(f.identity(), []).append(f)
    out = []
    for ident, group in by_id.items():
        methods = sorted({g.method for g in group})
        out.append(Triangulated(
            identity=ident,
            concept=group[0].concept,
            defect_class=group[0].defect_class,
            location=group[0].location,
            methods=methods,
            max_confidence=max(g.confidence for g in group),
            corroboration=len(methods),          # distinct METHODS, not distinct finding objects
            both_directions_any=any(g.both_directions_proven for g in group),
            findings=group,
        ))
    # most-corroborated first -- the ones a reader should trust most lead
    out.sort(key=lambda t: (t.corroboration, t.max_confidence), reverse=True)
    return out


def method_disagreements(findings: list[Finding]) -> list[str]:
    """A location one method flags and another method, run on the same location, calls clean is
    ITSELF a finding (Chris's own law: disagreement between two counts of one population is the
    finding). Callers pass in clean-verdicts as Findings with defect_class='clean-verdict'."""
    flagged: dict[str, set[str]] = {}
    cleared: dict[str, set[str]] = {}
    for f in findings:
        (cleared if f.defect_class == "clean-verdict" else flagged).setdefault(
            f.location, set()).add(f.method)
    out = []
    for loc, methods in flagged.items():
        clearers = cleared.get(loc, set()) - methods
        if clearers:
            out.append("%s: flagged by {%s} but called clean by {%s} -- disagreement is a finding"
                       % (loc, ",".join(sorted(methods)), ",".join(sorted(clearers))))
    return out


def to_sarif(tri: list[Triangulated], tool_name: str) -> dict:
    """The ONE SARIF 2.1.0 emitter for every repo (one definition, many readers). Findings annotate
    code inline in GitHub's UI; corroboration is carried in the message so a reviewer sees how many
    independent methods agreed. A corroborated finding is an error; a single-method lead is a warning."""
    rules: dict[str, None] = {}
    results = []
    for t in tri:
        rules[t.defect_class] = None
        path, _, line = t.location.partition(":")
        results.append({
            "ruleId": t.defect_class,
            "level": "warning" if t.trust == "single-method" else "error",
            "message": {"text": "%s [%s] found by %d method(s): %s"
                        % (t.defect_class, t.trust, t.corroboration, ", ".join(t.methods))},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": path},
                "region": {"startLine": int(line) if line.split("|")[0].strip().isdigit() else 1}}}],
        })
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": tool_name,
                      "rules": [{"id": r} for r in sorted(rules)]}}, "results": results}]}


def selftest() -> int:
    ok = True

    # 1. Two DIFFERENT methods finding the SAME defect must collapse to one, corroboration 2.
    f_ast = Finding("gate", "no-clean-without-looking", "guard.py:40",
                    "verdict path has no read of the live thing", method="ast-controlflow",
                    both_directions_proven=True)
    f_mut = Finding("gate", "no-clean-without-looking", "guard.py:40",
                    "mutating the guarded value did not change the verdict", method="mutation")
    tri = triangulate([f_ast, f_mut])
    if len(tri) != 1 or tri[0].corroboration != 2 or tri[0].trust != "corroborated":
        print("FAIL: two methods, one defect should corroborate ->", tri); ok = False

    # 2. Identity ignores METHOD -- same what/where, different method = same id.
    if f_ast.identity() != f_mut.identity():
        print("FAIL: identity must not depend on method"); ok = False

    # 3. A different LOCATION is a different finding.
    f_other = Finding("gate", "no-clean-without-looking", "guard.py:99",
                      "x", method="mutation")
    if f_other.identity() == f_ast.identity():
        print("FAIL: different location must be a different identity"); ok = False

    # 4. Single-method finding is 'single-method', not corroborated.
    tri2 = triangulate([f_other])
    if tri2[0].trust != "single-method":
        print("FAIL: one method should be single-method ->", tri2[0].trust); ok = False

    # 5. method_disagreements: one method flags a spot, another clears it -> a finding.
    flag = Finding("test", "dead-canary", "t_a.py:1", "mutation survived", method="mutation")
    clr = Finding("test", "clean-verdict", "t_a.py:1", "asserts on real return", method="ast")
    dis = method_disagreements([flag, clr])
    if len(dis) != 1:
        print("FAIL: a flag+clear on one location should disagree ->", dis); ok = False

    # 6. two methods that BOTH flag (no clear) do NOT count as a disagreement
    dis2 = method_disagreements([f_ast, f_mut])
    if dis2:
        print("FAIL: two flags is agreement, not disagreement ->", dis2); ok = False

    # 7. concept must be a known concept (portability contract)
    if f_ast.concept not in CONCEPTS:
        print("FAIL: concept not in the shared list"); ok = False

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
