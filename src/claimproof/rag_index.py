#!/usr/bin/env python3
# CALLED BY: claimproof's `check` (indexing stage) and the FULL-CIRCLE-OPTIMIZATION pipeline.
# FIRES WHEN: indexing a downloaded system -- learns how it labels concepts, then reports where a
#             LABEL and the BEHAVIOUR disagree (Chris's Telegram indexer table, 2026-09-23).
"""claimproof's RAG-style indexer.

It does two things Chris asked for:
  1. LEARNS the system's own labels/definitions per concept (via concepts.build_label_map) and
     surfaces SYNONYM SCATTER -- the many names one concept goes by -- so indexing/scanning can find
     a concept regardless of the target's naming.
  2. Reports LABEL-vs-BEHAVIOUR mismatches -- the silent class "labeled a gate but it doesn't gate /
     reports clean without looking." Two independent methods, so the corroborated ones are trustworthy
     on an unfamiliar system:
        constant-verdict  every return is a constant -> the verdict is fixed regardless of input
        input-ignored     no parameter is ever used  -> the verdict cannot depend on the input

A real predicate (`return bool(x)`) and a real gate (`if not x: raise`) fire NEITHER method, so they
are not flagged. AST only; never executes the target. ignored_label carries the misleading name.
"""
from __future__ import annotations

import ast
import os

try:
    from . import concepts
    from .finding import Finding, triangulate, Triangulated
except ImportError:
    import concepts  # type: ignore
    from finding import Finding, triangulate, Triangulated  # type: ignore

GATE_WORDS = {"gate", "guard", "validate", "enforce", "verify", "check", "ensure"}
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".tox", ".eggs",
         ".pytest_cache", "site-packages"}


def _params(fn):
    a = fn.args
    names = [p.arg for p in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return [n for n in names if n != "self"]


def gate_label_mismatches(root: str) -> list[Finding]:
    out = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        for f in fs:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dp, f)
            rel = os.path.relpath(path, root)
            try:
                tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                toks = set(concepts._norm(node.name).split())
                if not (toks & GATE_WORDS):
                    continue                                  # name does not claim to be a gate
                sig = concepts._func_signals(node)
                has_failpath = bool(sig & {"exit_nonzero", "guarded_raise", "raise", "assert"})
                if has_failpath:
                    continue                                  # it CAN signal failure -> a real gate
                params = _params(node)
                rets = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
                const_verdict = bool(rets) and all(
                    r.value is None or isinstance(r.value, ast.Constant) for r in rets)
                used = any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(node))
                input_ignored = bool(params) and not used
                idk = "gatelabel:%s:%s" % (rel, node.name)
                loc = "%s:%d" % (rel, node.lineno)
                if const_verdict:
                    out.append(Finding(
                        concept="gate", defect_class="labeled-gate-that-cannot-fail", location=loc,
                        signal="every return is a constant; the verdict is fixed",
                        evidence="%s is named like a gate but returns a constant regardless of input"
                                 % node.name,
                        method="constant-verdict", repo="claimproof", severity="high",
                        confidence=0.7, both_directions_proven=True, ignored_label=node.name,
                        extra={"id_key": idk}))
                if input_ignored:
                    out.append(Finding(
                        concept="gate", defect_class="labeled-gate-that-cannot-fail", location=loc,
                        signal="no parameter is used; the verdict cannot depend on the input",
                        evidence="%s is named like a gate but ignores its inputs" % node.name,
                        method="input-ignored", repo="claimproof", severity="high",
                        confidence=0.7, both_directions_proven=True, ignored_label=node.name,
                        extra={"id_key": idk}))
    return out


def index(root: str) -> dict:
    """The full index: the learned label map, synonym scatter, and the mismatch findings."""
    cm = concepts.build_label_map(root)
    scatter = {c: sorted(v) for c, v in cm.labels.items() if len(v) > 1}
    findings = triangulate(gate_label_mismatches(root))
    return {"label_map": cm, "synonym_scatter": scatter, "mismatches": findings}


def raw_findings(root: str) -> list[Finding]:
    return gate_label_mismatches(root)


def selftest() -> int:
    import tempfile, shutil
    ok = True

    def write(root, rel, body):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        open(p, "w", encoding="utf-8").write(body)

    d = tempfile.mkdtemp(prefix="rag_")
    try:
        # PLANT: a gate that returns True ignoring its input -> BOTH methods -> corroborated
        write(d, "gate_bad.py", "def check_access(user):\n    return True\n")
        # a real gate that raises -> NOT flagged
        write(d, "gate_ok.py", "def validate_token(t):\n    if not t:\n        raise ValueError('no')\n    return t\n")
        # a real predicate whose caller gates on the bool -> NOT flagged
        write(d, "pred.py", "def verify_sig(sig):\n    return bool(sig) and len(sig) > 3\n")
        # a gate-named fn that uses its input but returns a constant -> single-method (constant-verdict)
        write(d, "gate_mixed.py", "def guard_write(path):\n    print(path)\n    return True\n")

        idx = index(d)
        by_key = {}
        for t in idx["mismatches"]:
            by_key[t.findings[0].extra["id_key"]] = t

        bad = by_key.get("gatelabel:gate_bad.py:check_access")
        if not bad or bad.corroboration != 2:
            print("FAIL: do-nothing gate should be corroborated ->", bad); ok = False
        if "gatelabel:gate_ok.py:validate_token" in by_key:
            print("FAIL: a real gate (raises) was flagged"); ok = False
        if "gatelabel:pred.py:verify_sig" in by_key:
            print("FAIL: a real predicate was flagged"); ok = False
        mixed = by_key.get("gatelabel:gate_mixed.py:guard_write")
        if not mixed or mixed.corroboration != 1 or "constant-verdict" not in mixed.methods:
            print("FAIL: input-using constant gate should be single-method ->", mixed); ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(selftest())
    idx = index(sys.argv[1])
    print("claimproof RAG index of", sys.argv[1])
    print("  synonym scatter (a concept under many labels):")
    for c, labels in idx["synonym_scatter"].items():
        print("    %-11s %s" % (c, ", ".join(labels[:8])))
    print("  label/behaviour mismatches: %d" % len(idx["mismatches"]))
    for t in idx["mismatches"]:
        print("    [%s] %s  methods=%s" % (t.trust, t.location, ",".join(t.methods)))
    sys.exit(0)
