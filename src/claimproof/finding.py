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
    source_span: str = ""        # the EXACT code span the finding points at ("file:start-end" or a
                                 # short snippet) -- tighter than `location`, so a grader can re-open
                                 # and diff it (bookmark #6: source-span-grounded findings)
    evidence_strength: str = "unspecified"  # measured | cited | circumstantial | unspecified;
                                 # "cited" = evidence is only a comment/docstring (the weak
                                 # CITED-IS-CODE case) so a grader can discount it
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


def _sarif_locations(location: str) -> list[dict]:
    """A finding's `location` carries THREE shapes (see the Finding.location docstring): a plain
    file:line, a pipe-joined duplicate path-set ("a/util.py | b/util.py"), or a structural locator
    ("call-graph:orphan:mod.f"). Only the first is a real file position -- the other two must never
    be emitted as a physicalLocation.uri, or the annotation points at a path that does not exist."""
    if " | " in location:
        # a duplicate found across more than one path -- one physicalLocation per real path.
        paths = [p.strip() for p in location.split(" | ") if p.strip()]
        return [{"physicalLocation": {"artifactLocation": {"uri": p}}} for p in paths]
    path, sep, rest = location.partition(":")
    if sep and rest.isdigit():
        return [{"physicalLocation": {
            "artifactLocation": {"uri": path},
            "region": {"startLine": int(rest)}}}]
    # a structural locator (no single file:line shape) -- a logical location, never a fabricated uri.
    return [{"logicalLocations": [{"fullyQualifiedName": location}]}]


def to_sarif(tri: list[Triangulated], tool_name: str) -> dict:
    """The ONE SARIF 2.1.0 emitter for every repo (one definition, many readers). Findings annotate
    code inline in GitHub's UI; corroboration is carried in the message so a reviewer sees how many
    independent methods agreed. A corroborated finding is an error; a single-method lead is a warning."""
    rules: dict[str, None] = {}
    results = []
    for t in tri:
        rules[t.defect_class] = None
        results.append({
            "ruleId": t.defect_class,
            "level": "warning" if t.trust == "single-method" else "error",
            "message": {"text": "%s [%s] found by %d method(s): %s"
                        % (t.defect_class, t.trust, t.corroboration, ", ".join(t.methods))},
            "locations": _sarif_locations(t.location),
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

    # 4b. source-span schema (bookmark #6): the two new fields round-trip through to_json, and the
    # defaults are safe for every finding that does not set them.
    fs = Finding("read", "swallowed-exception", "svc.py:12", "except: pass swallows all",
                 method="ast", source_span="svc.py:12-14", evidence_strength="measured")
    d = json.loads(fs.to_json())
    if d.get("source_span") != "svc.py:12-14" or d.get("evidence_strength") != "measured":
        print("FAIL: source_span/evidence_strength must round-trip ->", d); ok = False
    if json.loads(f_other.to_json()).get("evidence_strength") != "unspecified":
        print("FAIL: evidence_strength must default to 'unspecified'"); ok = False

    # 5. method_disagreements: one method flags a spot, another clears it -> a finding.
    flag = Finding("test", "dead-canary", "t_a.py:1", "mutation survived", method="mutation")
    clr = Finding("test", "clean-verdict", "t_a.py:1", "asserts on real return", method="ast")
    dis = method_disagreements([flag, clr])
    #    and it names the RIGHT direction: mutation flagged it, ast cleared it (not the reverse).
    if len(dis) != 1 or "flagged by {mutation}" not in dis[0] or "called clean by {ast}" not in dis[0]:
        print("FAIL: a flag+clear on one location should disagree, naming who flagged vs cleared ->", dis); ok = False

    # 6. two methods that BOTH flag (no clear) do NOT count as a disagreement
    dis2 = method_disagreements([f_ast, f_mut])
    if dis2:
        print("FAIL: two flags is agreement, not disagreement ->", dis2); ok = False

    # 7. concept must be a known concept (portability contract)
    if f_ast.concept not in CONCEPTS:
        print("FAIL: concept not in the shared list"); ok = False

    # 8. corroboration >=2 but NO method proved both directions -> 'multi-method', NOT corroborated.
    #    This is the whole trust ladder: two methods AGREEING is only trustworthy once at least one
    #    of them proved it fires on known-bad and stays quiet on known-good (both_directions).
    g1 = Finding("wire", "function-unwired", "m.py:5", "no caller", method="ast")
    g2 = Finding("wire", "function-unwired", "m.py:5", "no caller", method="callgraph")
    t8 = triangulate([g1, g2])
    if t8[0].corroboration != 2 or t8[0].trust != "multi-method":
        print("FAIL: 2 methods, neither proven, must be multi-method not corroborated ->",
              t8[0].trust); ok = False

    # 9. triangulate sorts most-corroborated FIRST (a reader trusts the lead).
    t9 = triangulate([g1, g2, f_other])
    if t9[0].corroboration != 2 or t9[-1].corroboration != 1:
        print("FAIL: triangulate must sort most-corroborated first ->",
              [x.corroboration for x in t9]); ok = False

    # 10. to_json serialises faithfully AND deterministically (sorted keys -> stable diffs).
    d = json.loads(f_ast.to_json())
    if d.get("defect_class") != "no-clean-without-looking" or "concept" not in d \
            or d.get("both_directions_proven") is not True:
        print("FAIL: to_json must serialise the finding faithfully ->", d); ok = False
    if not f_ast.to_json().startswith('{"both_directions_proven"'):
        print("FAIL: to_json must sort keys (stable output)"); ok = False

    # 11. SARIF: a corroborated finding is an error, a single-method lead is a warning, rules listed.
    sar = to_sarif(triangulate([f_ast, f_mut, f_other]), "test-tool")
    #    check the level attaches to the RIGHT finding (a swapped mapping keeps the level SET
    #    identical, so asserting the set alone cannot catch it) -- key off each message's trust word.
    lvl = {}
    for r in sar["runs"][0]["results"]:
        for word in ("corroborated", "single-method"):
            if word in r["message"]["text"]:
                lvl[word] = r["level"]
    if lvl.get("corroborated") != "error" or lvl.get("single-method") != "warning":
        print("FAIL: SARIF level must follow trust (corroborated=error, single-method=warning) ->",
              lvl); ok = False
    if not sar["runs"][0]["tool"]["driver"]["rules"]:
        print("FAIL: SARIF must list the rule ids"); ok = False

    # 12. SARIF must never fabricate a physicalLocation for a non-file:line location -- a
    #     pipe-joined duplicate path-set becomes one physicalLocation per real path, and a
    #     structural locator becomes a logicalLocation, never a truncated/garbled uri.
    f_pipe = Finding("read", "same-content-duplicate", "a/util.py | b/util.py", "",
                      method="same-content", both_directions_proven=True, severity="high")
    f_struct = Finding("wire", "function-unwired", "call-graph:orphan:mod.f", "no caller",
                        method="callgraph")
    sar2 = to_sarif(triangulate([f_pipe]), "test-tool")
    locs = sar2["runs"][0]["results"][0]["locations"]
    uris = [l.get("physicalLocation", {}).get("artifactLocation", {}).get("uri") for l in locs]
    if uris != ["a/util.py", "b/util.py"]:
        print("FAIL: pipe-joined location must become one physicalLocation per real path ->",
              locs); ok = False

    sar3 = to_sarif(triangulate([f_struct]), "test-tool")
    locs3 = sar3["runs"][0]["results"][0]["locations"]
    if "physicalLocation" in locs3[0] or \
            locs3[0].get("logicalLocations", [{}])[0].get("fullyQualifiedName") != "call-graph:orphan:mod.f":
        print("FAIL: a structural locator must become a logicalLocation, never a fabricated uri ->",
              locs3); ok = False

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
