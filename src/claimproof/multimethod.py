#!/usr/bin/env python3
# CALLED BY: claimproof.report (the `check` subcommand) and the FULL-CIRCLE-OPTIMIZATION pipeline.
# FIRES WHEN: claimproof scans a target for SILENT defects -- runs several independent methods per
#             class so one catches what another misses (Chris, 2026-09-23: corroboration is the point).
"""claimproof's multi-method silent-defect engine.

THE PRODUCT (Chris, 2026-09-23): "one tool finds things that another missed when looking in
different methods." Each silent-defect class is judged by SEVERAL independent methods. A defect two
methods agree on is CORROBORATED (trustworthy on an unfamiliar system, because no single blind spot
could hide it); a defect one method saw is a lead to confirm.

First class: "a test that cannot fail" (green forever, protects nothing). Two independent methods:

  weak-oracle      the test has no assertion, or asserts only on compile-time constants
  return-ignored   the test calls project code but discards every return value

They are independent (ORACLE vs USAGE) and overlap on the classic dead test that calls code and
checks nothing. A third method -- MUTATION (change the code, the test must go red) -- is the
strongest and needs a runtime; it is next on the plan (B2).

WHAT COUNTS AS A TEST, honestly: a function the TEST RUNNER would collect -- pytest (a `test_*`
function in a `test_*.py`/`*_test.py`, or a `test*` method of a `Test*`/`*TestCase` class) or
unittest. This is convention-bound on purpose: "a test" IS "what the runner runs", so a `test_*`
function that no runner would collect is a different defect (an unwired test), not this one. A helper
that merely calls project code is NOT a test and must not be flagged -- that over-fire was measured
on the real carrot-sandbox (`_score` in fanout_scoreboard.py) and is what this definition fixes.
Custom runners with non-standard names are learned by the concept/label map (concepts.py), not here.

AST only; never executes the target. `ignored_label` records that the FAILURE SIGNAL is behavioural.
"""
from __future__ import annotations

import ast
import os

try:
    from .finding import Finding, triangulate, Triangulated, to_sarif
except ImportError:                                  # run directly for --selftest
    from finding import Finding, triangulate, Triangulated, to_sarif  # type: ignore

_TEST_FILE = ("test_", "_test")


def _is_test_file(rel: str) -> bool:
    base = os.path.basename(rel)
    return base.startswith("test_") or base[:-3].endswith("_test")


def _local_modules(root: str) -> set[str]:
    names = set()
    try:
        entries = os.listdir(root)
    except OSError:
        return names
    for entry in entries:
        p = os.path.join(root, entry)
        if entry.endswith(".py") and entry != "__init__.py":
            names.add(entry[:-3])
        elif os.path.isdir(p) and os.path.exists(os.path.join(p, "__init__.py")):
            names.add(entry)
    return names


def _project_imported_names(tree, local_mods):
    names, mod_aliases = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[0]
            if base in local_mods or (node.level and node.level > 0):
                for a in node.names:
                    names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in local_mods:
                    mod_aliases.add(a.asname or a.name.split(".")[0])
    return names, mod_aliases


def _calls_project(fn, names, mod_aliases):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in names:
                out.append(node)
            elif isinstance(f, ast.Attribute):
                root = f
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and (root.id in mod_aliases or root.id in names):
                    out.append(node)
    return out


def _is_testcase_class(cls: ast.ClassDef) -> bool:
    for b in cls.bases:
        name = b.attr if isinstance(b, ast.Attribute) else (b.id if isinstance(b, ast.Name) else "")
        if name.endswith("TestCase"):
            return True
    return False


def _collectable_tests(root: str):
    """Yield (rel, funcnode, project_calls) for every function a standard runner would collect."""
    seen = set()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_M and not d.endswith(".egg-info")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rp = os.path.realpath(path)
            if rp in seen:                                # dedupe symlinked mirrors (by-kind/, etc.)
                continue
            seen.add(rp)
            rel = os.path.relpath(path, root)
            try:
                tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError, OSError):
                continue
            names, mod_aliases = _project_imported_names(tree, _local_modules(root))
            testfile = _is_test_file(rel)
            for node in ast.walk(tree):
                # pytest: module-level test_* in a test file
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        node.name.startswith("test") and testfile:
                    yield rel, node, _calls_project(node, names, mod_aliases)
                # unittest: test* method of a *TestCase class (any file)
                elif isinstance(node, ast.ClassDef) and _is_testcase_class(node):
                    for m in node.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                                m.name.startswith("test"):
                            yield rel, m, _calls_project(m, names, mod_aliases)


def _asserts(fn):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]


def _uses_raises(fn) -> bool:
    """pytest.raises / assertRaises / self.assertRaises -- a legitimate non-assert oracle."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            d = node.func
            nm = d.attr if isinstance(d, ast.Attribute) else (d.id if isinstance(d, ast.Name) else "")
            if "raises" in nm.lower():
                return True
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                c = item.context_expr
                if isinstance(c, ast.Call):
                    d = c.func
                    nm = d.attr if isinstance(d, ast.Attribute) else (d.id if isinstance(d, ast.Name) else "")
                    if "raises" in nm.lower():
                        return True
    return False


def _is_constant_test(test) -> bool:
    if isinstance(test, ast.Constant):
        return True
    if isinstance(test, ast.Compare):
        return (isinstance(test.left, ast.Constant)
                and all(isinstance(c, ast.Constant) for c in test.comparators))
    return False


# ---------------------------------------------------------------- the two independent methods
def method_weak_oracle(root: str) -> list[Finding]:
    out = []
    for rel, fn, _calls in _collectable_tests(root):
        if _uses_raises(fn):
            continue
        asserts = _asserts(fn)
        if not asserts or all(_is_constant_test(a.test) for a in asserts):
            out.append(Finding(
                concept="test", defect_class="test-cannot-fail",
                location="%s:%d" % (rel, fn.lineno),
                signal="no assertion, or asserts only on compile-time constants",
                evidence="a collected test whose oracle cannot fail",
                method="weak-oracle", repo="claimproof", severity="high",
                confidence=0.7, ignored_label="the name 'test' proves collection, not correctness",
                both_directions_proven=True))
    return out


def method_return_ignored(root: str) -> list[Finding]:
    out = []
    for rel, fn, calls in _collectable_tests(root):
        if not calls or _uses_raises(fn):   # pytest.raises/assertRaises IS an oracle on the call
            continue
        bare = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and node.value in calls:
                bare.add(id(node.value))
        if all(id(c) in bare for c in calls):
            out.append(Finding(
                concept="test", defect_class="test-cannot-fail",
                location="%s:%d" % (rel, fn.lineno),
                signal="every call to project code discards its return value",
                evidence="a collected test that runs project code but inspects no result",
                method="return-ignored", repo="claimproof", severity="high",
                confidence=0.65, ignored_label="the name 'test' proves collection, not correctness",
                both_directions_proven=True))
    return out


# ---------------------------------------------------------------- swallowed-exception (absent-looks-clean)
def _clean_const(node) -> bool:
    """A value that disguises FAILURE as SUCCESS. True / 0 / '' / empty container. Deliberately NOT
    None or False -- returning those after an error is a common, legitimate signal, not a disguise."""
    if isinstance(node, ast.Constant):
        v = node.value
        return v is True or (isinstance(v, int) and not isinstance(v, bool) and v == 0) or v == ""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _handlers(root: str):
    seen = set()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_M and not d.endswith(".egg-info")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            rp = os.path.realpath(os.path.join(dirpath, fn))
            if rp in seen:
                continue
            seen.add(rp)
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            try:
                tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    yield rel, node


def _own_scope(node):
    """Like ast.walk, but does not descend into a nested function/lambda/comprehension --
    a return/raise defined THERE belongs to a different scope, not to NODE's own control
    flow (measured false positive/negative on a handler that only defines+calls a helper,
    2026-09-23)."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                                   ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            stack.append(child)


def _reraises(h) -> bool:
    return any(isinstance(n, ast.Raise) for n in _own_scope(h))


def _announces(h) -> bool:
    """A handler that PRINTS or LOGS the error before continuing is an ANNOUNCED fail-open, not a
    SILENT swallow. Chris's defect is the SILENT one. Announced fail-open (e.g. a hook that prints
    'gate did not run; allowing the turn' to stderr) is legitimate and must not be flagged (measured
    FP on claimproof's own code + the hook layer, 2026-09-23)."""
    _LOG = {"error", "warning", "warn", "exception", "critical", "info", "debug", "log", "print"}
    for n in ast.walk(h):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nm in _LOG:
                return True
            # sys.stderr.write(...) / self.stderr.write(...)
            if nm == "write":
                d = f
                while isinstance(d, ast.Attribute):
                    if d.attr == "stderr" or (isinstance(d.value, ast.Name) and d.value.id in ("sys",)):
                        return True
                    d = d.value
    return False


def _is_broad(h) -> bool:
    """Only a BROAD catch (bare except, or Exception/BaseException) is the dangerous swallow.
    `except OSError: return []` and other SPECIFIC catches returning a default are idiomatic and
    must not be flagged (measured FP on real code 2026-09-23)."""
    t = h.type
    if t is None:
        return True
    if isinstance(t, ast.Name):
        return t.id in ("Exception", "BaseException")
    if isinstance(t, ast.Attribute):
        return t.attr in ("Exception", "BaseException")
    if isinstance(t, ast.Tuple):
        for elt in t.elts:
            if isinstance(elt, ast.Name) and elt.id in ("Exception", "BaseException"):
                return True
            if isinstance(elt, ast.Attribute) and elt.attr in ("Exception", "BaseException"):
                return True
        return False
    return False


def _pass_only(h) -> bool:
    body = [s for s in h.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                      and isinstance(s.value.value, str))]  # ignore a docstring
    return len(body) == 1 and isinstance(body[0], (ast.Pass,))


def _returns_clean(h) -> bool:
    return any(isinstance(n, ast.Return) and n.value is not None and _clean_const(n.value)
               for n in _own_scope(h))


def method_silent_swallow(root: str) -> list[Finding]:
    """The handler does nothing observable: pass-only, or returns a clean value, and never re-raises."""
    out = []
    for rel, h in _handlers(root):
        if _reraises(h) or not _is_broad(h) or _announces(h):
            continue
        if _pass_only(h) or _returns_clean(h):
            out.append(Finding(
                concept="read", defect_class="swallowed-exception",
                location="%s:%d" % (rel, h.lineno),
                signal="except handler swallows the error and continues (no re-raise)",
                evidence="a failure here is turned into a normal-looking outcome",
                method="silent-swallow", repo="claimproof", severity="high", confidence=0.7,
                both_directions_proven=True, extra={"id_key": "swallow:%s:%d" % (rel, h.lineno)}))
    return out


def method_returns_success_in_except(root: str) -> list[Finding]:
    """The handler returns a value that reads as SUCCESS (True/0/''/empty), disguising the failure."""
    out = []
    for rel, h in _handlers(root):
        if _reraises(h) or not _is_broad(h) or _announces(h):
            continue
        if _returns_clean(h):
            out.append(Finding(
                concept="read", defect_class="swallowed-exception",
                location="%s:%d" % (rel, h.lineno),
                signal="except handler returns a success-looking value (True/0/''/empty)",
                evidence="the caller cannot tell this failed",
                method="returns-success", repo="claimproof", severity="high", confidence=0.7,
                both_directions_proven=True, extra={"id_key": "swallow:%s:%d" % (rel, h.lineno)}))
    return out


import re as _re

_SKIP_M = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".tox",
           ".eggs", ".pytest_cache", "site-packages"}


def _iter_py(root):
    seen = set()
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_M and not d.endswith(".egg-info")]
        for f in fs:
            if not f.endswith(".py"):
                continue
            rp = os.path.realpath(os.path.join(dp, f))
            if rp in seen:
                continue
            seen.add(rp)
            rel = os.path.relpath(os.path.join(dp, f), root)
            try:
                yield rel, ast.parse(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError, OSError):
                continue


def method_assert_constant_prod(root: str) -> list[Finding]:
    """A truthy CONSTANT assertion in production code (`assert True`, `assert "msg"`) -- it always
    passes, so it looks like a guard but checks nothing. (In a test file this is test-cannot-fail's
    job; here it is production code lying about a check.) Fix: assert the real condition; or if it is
    a typo for `assert x, "msg"`, add the condition."""
    out = []
    for rel, tree in _iter_py(root):
        if _is_test_file(rel):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant) and bool(node.test.value):
                out.append(Finding(
                    concept="claim", defect_class="assert-constant-in-production",
                    location="%s:%d" % (rel, node.lineno),
                    signal="assert on a truthy constant -- it can never fail",
                    evidence="this reads as a guard but checks nothing",
                    method="constant-assert", repo="claimproof", severity="med", confidence=0.8,
                    both_directions_proven=True, extra={"id_key": "assertconst:%s:%d" % (rel, node.lineno)}))
    return out


def method_unreachable_except(root: str) -> list[Finding]:
    """An except handler that can never run because a broader one (Exception/BaseException/bare)
    appears before it in the same try -- the specific handling is dead. Fix: reorder so specific
    handlers precede the broad one; or remove the dead handler."""
    out = []
    for rel, tree in _iter_py(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for i, h in enumerate(node.handlers[:-1]):
                    t = h.type
                    broad = (t is None or (isinstance(t, ast.Name) and t.id in ("Exception", "BaseException"))
                             or (isinstance(t, ast.Attribute) and t.attr in ("Exception", "BaseException")))
                    if broad:
                        nxt = node.handlers[i + 1]
                        out.append(Finding(
                            concept="read", defect_class="unreachable-except",
                            location="%s:%d" % (rel, nxt.lineno),
                            signal="a broad except precedes this handler, so it can never run",
                            evidence="this error is not actually being handled",
                            method="broad-before-specific", repo="claimproof", severity="med",
                            confidence=0.85, both_directions_proven=True,
                            extra={"id_key": "unreachexc:%s:%d" % (rel, nxt.lineno)}))
                        break
    return out


def _terminates(stmt) -> bool:
    """True when STMT exits every reachable path via return/raise -- recursing into an
    exhaustive if/else or a try/except so a predicate ending in one is not wrongly judged
    to fall through to implicit None (measured over-fire on ordinary if/else predicates,
    2026-09-23)."""
    if isinstance(stmt, (ast.Return, ast.Raise)):
        return True
    if isinstance(stmt, ast.If) and stmt.orelse:
        return (bool(stmt.body) and _terminates(stmt.body[-1])
                and bool(stmt.orelse) and _terminates(stmt.orelse[-1]))
    if isinstance(stmt, ast.Try):
        branches = [stmt.body] + [h.body for h in stmt.handlers]
        if stmt.orelse:
            branches.append(stmt.orelse)
        if stmt.finalbody and stmt.finalbody[-1] and _terminates(stmt.finalbody[-1]):
            return True
        return bool(branches) and all(b and _terminates(b[-1]) for b in branches)
    return False


def method_predicate_returns_none(root: str) -> list[Finding]:
    """A predicate (is_/has_/can_/should_) that returns a real value on one path but can fall through
    to an implicit None -- None is falsy but is not False, so a caller doing `if not is_x()` behaves
    differently than intended. Fix: return False on the fall-through path; make all paths return bool."""
    out = []
    pred = _re.compile(r"^(is|has|can|should)_")
    for rel, tree in _iter_py(root):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and pred.match(node.name):
                returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
                returns_value = any(r.value is not None for r in returns)
                bare_return = any(r.value is None for r in returns)
                last = node.body[-1] if node.body else None
                falls_through = last is None or not _terminates(last)
                if returns_value and (bare_return or falls_through):
                    out.append(Finding(
                        concept="claim", defect_class="predicate-returns-none",
                        location="%s:%d" % (rel, node.lineno),
                        signal="a predicate can fall through to None instead of returning a bool",
                        evidence="%s returns a value on one path but None on another" % node.name,
                        method="predicate-falls-through", repo="claimproof", severity="low",
                        confidence=0.65, both_directions_proven=True,
                        extra={"id_key": "prednone:%s:%s" % (rel, node.name)}, ignored_label=node.name))
    return out


METHODS = {
    "test-cannot-fail": [method_weak_oracle, method_return_ignored],
    "swallowed-exception": [method_silent_swallow, method_returns_success_in_except],
    "assert-constant-in-production": [method_assert_constant_prod],
    "unreachable-except": [method_unreachable_except],
    "predicate-returns-none": [method_predicate_returns_none],
}


def raw_findings(root: str) -> list[Finding]:
    out: list[Finding] = []
    for methods in METHODS.values():
        for m in methods:
            out.extend(m(root))
    return out


def scan(root: str) -> list[Triangulated]:
    return triangulate(raw_findings(root))


# SARIF is emitted by the shared contract (finding.to_sarif) -- one definition, many readers.


# ---------------------------------------------------------------- proof
def selftest() -> int:
    import tempfile, shutil
    ok = True

    def write(root, rel, body):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        open(p, "w", encoding="utf-8").write(body)

    d = tempfile.mkdtemp(prefix="cp_mm_")
    try:
        write(d, "core.py", "def go():\n    return 1\n")
        # 1. classic dead test: collected, calls code, checks nothing -> BOTH methods -> corroborated
        write(d, "test_dead.py", "from core import go\ndef test_dead():\n    go()\n")
        # 2. constant-oracle test: collected, asserts True, result used -> weak-oracle ONLY
        write(d, "test_const.py",
              "from core import go\ndef test_const():\n    x = go()\n    assert True\n")
        # 3. good test: asserts on the real result -> NEITHER -> clean control
        write(d, "test_good.py", "from core import go\ndef test_good():\n    assert go() == 1\n")
        # 4. a HELPER that calls project code but is NOT a collected test -> must NOT be flagged
        #    (this is the false positive measured on carrot-sandbox's _score)
        write(d, "scoreboard.py", "from core import go\ndef _score(row):\n    go()\n    return True\n")
        # 5. a test using pytest.raises as its oracle -> legitimate, must NOT be flagged
        write(d, "test_raises.py",
              "import pytest\nfrom core import go\ndef test_raises():\n    with pytest.raises(ValueError):\n        go()\n")
        # 6. unittest TestCase with a constant-oracle method -> weak-oracle
        write(d, "test_unit.py",
              "import unittest\nfrom core import go\n"
              "class T(unittest.TestCase):\n    def test_x(self):\n        assert 1 == 1\n")

        tri = scan(d)
        by_file = {}
        for t in tri:
            by_file.setdefault(t.location.split(":")[0], t)

        dead = by_file.get("test_dead.py")
        if not dead or dead.corroboration != 2 or dead.trust != "corroborated":
            print("FAIL: dead test should be corroborated by 2 methods ->", dead); ok = False

        const = by_file.get("test_const.py")
        if not const or const.corroboration != 1 or "weak-oracle" not in const.methods:
            print("FAIL: const test should be single-method weak-oracle ->", const); ok = False

        if "test_good.py" in by_file:
            print("FAIL: good test flagged (false positive) ->", by_file["test_good.py"]); ok = False
        if "scoreboard.py" in by_file:
            print("FAIL: non-test helper flagged (the carrot-sandbox over-fire) ->",
                  by_file["scoreboard.py"]); ok = False
        if "test_raises.py" in by_file:
            print("FAIL: pytest.raises test flagged (false positive) ->", by_file["test_raises.py"]); ok = False
        if "test_unit.py" not in by_file:
            print("FAIL: unittest constant-oracle test missed"); ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # swallowed-exception: return-clean-in-except -> corroborated; pass-only -> single; re-raise and
    # legit fallback (return a variable / return None) -> NOT flagged
    d5 = tempfile.mkdtemp(prefix="cp_sw_")
    try:
        write(d5, "s.py",
              "def a():\n    try:\n        risky()\n    except Exception:\n        return True\n"      # corroborated
              "def b():\n    try:\n        risky()\n    except Exception:\n        pass\n"              # silent-swallow only
              "def c():\n    try:\n        risky()\n    except Exception as e:\n        raise\n"        # re-raises -> ok
              "def d():\n    try:\n        risky()\n    except Exception:\n        return None\n"        # None -> ok
              "def e(default):\n    try:\n        risky()\n    except Exception:\n        return default\n")  # fallback -> ok
        tri5 = scan(d5)
        sw = {t.location: t for t in tri5 if t.defect_class == "swallowed-exception"}
        corr = [t for t in sw.values() if t.corroboration == 2]
        single = [t for t in sw.values() if t.corroboration == 1]
        if not corr:
            print("FAIL: return-True-in-except should be corroborated ->", list(sw.values())); ok = False
        if not single:
            print("FAIL: pass-only except should be single-method ->", list(sw.values())); ok = False
        if len(sw) != 2:
            print("FAIL: re-raise / return-None / return-fallback must NOT be flagged ->", list(sw)); ok = False
    finally:
        shutil.rmtree(d5, ignore_errors=True)

    # ---- mutation-hardening BLOCK A: _local_modules / _project_imported_names / _is_testcase_class /
    #      _collectable_tests dir-prune / _uses_raises / _is_constant_test
    d = tempfile.mkdtemp(prefix="cp_a_")
    try:
        write(d, "core.py", "def go():\n    return 1\n")
        write(d, "pkg/__init__.py", "")
        write(d, "pkg/mod.py", "def h():\n    return 2\n")
        # L57 & L90-Or: ABSOLUTE import of a local PACKAGE dir, called + ignored -> corroborated
        write(d, "test_pkgabs.py", "from pkg import mod\ndef test_pkgabs():\n    mod.h()\n")
        # L59: a plain directory (no __init__) is NOT a local module -> not corroborated
        write(d, "plaindir/note.txt", "x")
        write(d, "test_plain.py", "import plaindir\ndef test_plain():\n    plaindir.x()\n")
        # L69-Gt: a relative import (node.level>0) counts as project -> corroborated
        write(d, "pkg/test_rel.py", "from . import mod\ndef test_rel():\n    mod.h()\n")
        # L90-And: a stdlib call must NOT count as project -> single weak-oracle only
        write(d, "test_ext.py", "import json\ndef test_ext():\n    json.dumps(1)\n")
        # L99: a unittest TestCase in a NON-test-named file must still be collected
        write(d, "suite.py", "import unittest\nfrom core import go\nclass T(unittest.TestCase):\n    def test_x(self):\n        assert 1 == 1\n")
        # L100: a plain (non-TestCase) class's test-named method must NOT be collected
        write(d, "widget.py", "class Widget:\n    def test_mode(self):\n        pass\n")
        # L107: a collectable test inside a SKIPPED dir must NOT be scanned
        write(d, "node_modules/test_nm.py", "def test_nm():\n    assert True\n")
        # L147: pytest raises used as a CALL (assertRaises) is a real oracle -> NOT flagged
        write(d, "test_ar.py", "import unittest\nfrom core import go\nclass R(unittest.TestCase):\n    def test_r(self):\n        self.assertRaises(ValueError, go)\n")
        # L165: an assert on a runtime CALL is a real oracle -> NOT weak
        write(d, "test_callassert.py", "from core import go\ndef test_ca():\n    assert go()\n")
        tri = scan(d)
        by = {}
        for t in tri:
            by.setdefault(t.location.split(":")[0], t)
        x = by.get("test_pkgabs.py")
        if not x or x.corroboration != 2:
            print("FAIL[L57/L90-Or]: absolute local-package call must corroborate ->", x); ok = False
        x = by.get("test_plain.py")
        if not x or x.corroboration != 1 or "return-ignored" in x.methods:
            print("FAIL[L59]: a plain dir must NOT count as a local module ->", x); ok = False
        x = by.get("pkg/test_rel.py")
        if not x or x.corroboration != 2:
            print("FAIL[L69-Gt]: relative-import (level>0) call must corroborate ->", x); ok = False
        x = by.get("test_ext.py")
        if not x or x.corroboration != 1 or "return-ignored" in x.methods:
            print("FAIL[L90-And]: a stdlib call must NOT count as project ->", x); ok = False
        if "suite.py" not in by:
            print("FAIL[L99]: unittest TestCase in a non-test file was not collected"); ok = False
        if "widget.py" in by:
            print("FAIL[L100]: a plain class's test-named method was wrongly collected ->", by["widget.py"]); ok = False
        if "node_modules/test_nm.py" in by:
            print("FAIL[L107]: a test inside a skipped dir was scanned ->", by["node_modules/test_nm.py"]); ok = False
        if "test_ar.py" in by:
            print("FAIL[L147]: assertRaises-as-call test flagged (false positive) ->", by["test_ar.py"]); ok = False
        if "test_callassert.py" in by:
            print("FAIL[L165]: assert on a runtime call flagged as weak (false positive) ->", by["test_callassert.py"]); ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---- mutation-hardening BLOCK B: both_directions_proven must survive triangulation as
    #      both_directions_any on a SINGLE-method finding (L183 weak-oracle, L204 return-ignored)
    d2 = tempfile.mkdtemp(prefix="cp_b_")
    try:
        write(d2, "core.py", "def go():\n    return 1\n")
        # weak-oracle ONLY (result used, constant assert) -> isolates L183's flag
        write(d2, "test_const.py", "from core import go\ndef test_const():\n    x = go()\n    assert True\n")
        # return-ignored ONLY (call ignored, but a real non-constant assert present) -> isolates L204
        write(d2, "test_ri.py", "from core import go\ndef test_ri():\n    go()\n    assert 1 == 1 + 0\n")
        tri2 = scan(d2)
        by2 = {t.location.split(":")[0]: t for t in tri2}
        x = by2.get("test_const.py")
        if not x or "weak-oracle" not in x.methods or not x.both_directions_any:
            print("FAIL[L183]: weak-oracle finding must carry both_directions_any=True ->", x); ok = False
        x = by2.get("test_ri.py")
        if not x or "return-ignored" not in x.methods or not x.both_directions_any:
            print("FAIL[L204]: return-ignored finding must carry both_directions_any=True ->", x); ok = False
    finally:
        shutil.rmtree(d2, ignore_errors=True)

    # ---- mutation-hardening BLOCK C: _clean_const / dir-prune in _handlers / _announces /
    #      _is_broad / the Or-guard in method_silent_swallow & method_returns_success_in_except
    d3 = tempfile.mkdtemp(prefix="cp_c_")
    try:
        # L214-Is & L274/L275: bare except returning True -> clean AND broad -> flagged, corroborated
        write(d3, "zTrue.py", "def a():\n    try:\n        risky()\n    except:\n        return True\n")
        # L214-Eq: return 0 is clean (flagged); return 5 is NOT clean (not flagged)
        write(d3, "z0.py", "def a():\n    try:\n        risky()\n    except Exception:\n        return 0\n")
        write(d3, "z5.py", "def a():\n    try:\n        risky()\n    except Exception:\n        return 5\n")
        # L225: a broad swallow inside a SKIPPED dir must NOT be scanned
        write(d3, "node_modules/swal.py", "def a():\n    try:\n        risky()\n    except Exception:\n        return True\n")
        # L258 & L298/L315-Or: a logging announce before returning clean -> NOT flagged
        write(d3, "zlog.py", "import logging\ndef a():\n    try:\n        risky()\n    except Exception:\n        logging.error(\'x\')\n        return True\n")
        # L260 & L263-Or: sys.stderr.write / self.stderr.write announce -> NOT flagged
        write(d3, "zstderr.py", "import sys\ndef a():\n    try:\n        risky()\n    except Exception:\n        sys.stderr.write(\'x\')\n        return True\n")
        write(d3, "zself.py", "class C:\n    def a(self):\n        try:\n            risky()\n        except Exception:\n            self.stderr.write(\'x\')\n            return True\n")
        # L260/L263-Eq: a NON-stderr .write() is not an announce -> MUST be flagged
        write(d3, "zwrite.py", "def a(buf):\n    try:\n        risky()\n    except Exception:\n        buf.write(\'x\')\n        return True\n")
        # L280: a TUPLE of specific exception types is not broad -> NOT flagged
        write(d3, "zbroadtuple.py", "def a():\n    try:\n        risky()\n    except (OSError, ValueError):\n        return True\n")
        # L276/L277: a single specific exception type is not broad -> NOT flagged
        write(d3, "zspecific.py", "def a():\n    try:\n        risky()\n    except OSError:\n        return True\n")
        # L298/L315-Or (reraise leg): a handler that re-raises must never be flagged even though it
        # also returns a clean-looking value on an earlier (unreachable) line
        write(d3, "r1.py", "def a():\n    try:\n        risky()\n    except Exception:\n        return True\n        raise\n")
        tri3 = scan(d3)
        by3 = {}
        for t in tri3:
            by3.setdefault(t.location.split(":")[0], t)
        x = by3.get("zTrue.py")
        if not x or x.corroboration != 2:
            print("FAIL[L214-Is/L274/L275]: bare-except return-True must be broad+clean+corroborated ->", x); ok = False
        x = by3.get("z0.py")
        if not x or x.corroboration != 2:
            print("FAIL[L214-Eq]: return 0 in a broad except must be treated as clean ->", x); ok = False
        if "z5.py" in by3:
            print("FAIL[L214-Eq]: return 5 must NOT be treated as a clean value ->", by3["z5.py"]); ok = False
        if "node_modules/swal.py" in by3:
            print("FAIL[L225]: a swallow inside a skipped dir was scanned ->", by3["node_modules/swal.py"]); ok = False
        if "zlog.py" in by3:
            print("FAIL[L258/L298/L315]: a logging-announced except was flagged ->", by3["zlog.py"]); ok = False
        if "zstderr.py" in by3:
            print("FAIL[L260/L263]: sys.stderr.write announce was flagged ->", by3["zstderr.py"]); ok = False
        if "zself.py" in by3:
            print("FAIL[L263-Or]: self.stderr.write announce was flagged ->", by3["zself.py"]); ok = False
        x = by3.get("zwrite.py")
        if not x:
            print("FAIL[L260/L263-Eq]: a non-stderr .write() must still be flagged ->", x); ok = False
        if "zbroadtuple.py" in by3:
            print("FAIL[L280]: a tuple of specific exception types was treated as broad ->", by3["zbroadtuple.py"]); ok = False
        if "zspecific.py" in by3:
            print("FAIL[L276/L277]: a single specific exception type was treated as broad ->", by3["zspecific.py"]); ok = False
        if "r1.py" in by3:
            print("FAIL[L298/L315-Or]: a re-raising handler was flagged despite raise ->", by3["r1.py"]); ok = False
    finally:
        shutil.rmtree(d3, ignore_errors=True)

    # ---- mutation-hardening BLOCK D: nested-scope leak in _reraises/_returns_clean
    #      (2026-09-23 confirmed defect #1)
    d4 = tempfile.mkdtemp(prefix="cp_d_")
    try:
        # a handler that only defines+calls a NESTED helper returning True must NOT be
        # flagged: the handler itself falls through to implicit None.
        write(d4, "nest.py",
              "def f():\n    try:\n        risky()\n    except Exception:\n"
              "        def helper():\n            return True\n        helper()\n")
        # the same shape for _reraises: a nested helper that raises must not count as
        # the OUTER handler re-raising.
        write(d4, "nestraise.py",
              "def f():\n    try:\n        risky()\n    except Exception:\n"
              "        def helper():\n            raise ValueError()\n        helper()\n"
              "        return True\n")
        tri4 = scan(d4)
        by4 = {t.location.split(":")[0]: t for t in tri4}
        if "nest.py" in by4:
            print("FAIL[nested-scope]: a handler with only a nested-return helper was "
                  "flagged as returning clean ->", by4["nest.py"]); ok = False
        if "nestraise.py" not in by4:
            print("FAIL[nested-scope]: a handler that itself returns True (nested raise "
                  "does not count as the outer handler re-raising) was not flagged"); ok = False
    finally:
        shutil.rmtree(d4, ignore_errors=True)

    # ---- mutation-hardening BLOCK E: redundant broad-tuple except clause
    #      (2026-09-23 confirmed defect #3)
    d6 = tempfile.mkdtemp(prefix="cp_e_")
    try:
        # a tuple that INCLUDES Exception is broad -- must be flagged like a bare except.
        write(d6, "broadtuple.py",
              "def a():\n    try:\n        risky()\n    except (Exception, ValueError):\n        pass\n")
        # a tuple of only SPECIFIC types is still not broad -- must not be flagged
        # (guards the existing zbroadtuple.py case from regressing).
        write(d6, "specifictuple.py",
              "def a():\n    try:\n        risky()\n    except (OSError, ValueError):\n        pass\n")
        tri6 = scan(d6)
        by6 = {t.location.split(":")[0]: t for t in tri6}
        if "broadtuple.py" not in by6:
            print("FAIL[broad-tuple]: except (Exception, ValueError) was not treated as "
                  "broad"); ok = False
        if "specifictuple.py" in by6:
            print("FAIL[broad-tuple]: a tuple of only specific types was wrongly treated "
                  "as broad ->", by6["specifictuple.py"]); ok = False
    finally:
        shutil.rmtree(d6, ignore_errors=True)

    # ---- mutation-hardening BLOCK F: exhaustive if/else must terminate a predicate
    #      (2026-09-23 confirmed defect #2)
    d7 = tempfile.mkdtemp(prefix="cp_f_")
    try:
        # an if/else whose every branch returns a bool must NOT be flagged -- it can
        # never fall through to None, even though its last statement is not itself a
        # Return node.
        write(d7, "ifelse.py",
              "def is_valid(x):\n    if x:\n        return True\n    else:\n        return False\n")
        # the genuinely-falling-through control (an if with NO else) must still fire.
        write(d7, "noelse.py",
              "def is_x(x):\n    if x:\n        return True\n")
        tri7 = scan(d7)
        by7 = {t.location.split(":")[0]: t for t in tri7}
        if "ifelse.py" in by7:
            print("FAIL[if-else-terminates]: an exhaustive if/else predicate was wrongly "
                  "flagged as falling through ->", by7["ifelse.py"]); ok = False
        if "noelse.py" not in by7:
            print("FAIL[if-else-terminates]: an if with no else must still be flagged as "
                  "falling through"); ok = False
    finally:
        shutil.rmtree(d7, ignore_errors=True)

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv) -> int:
    import json as _json
    if "--selftest" in argv:
        return selftest()
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print("usage: multimethod.py <target-dir> [--sarif out.sarif]"); return 2
    tri = scan(paths[0])
    corr = sum(1 for t in tri if t.trust != "single-method")
    print("claimproof multi-method: %d silent finding(s), %d corroborated by >=2 methods"
          % (len(tri), corr))
    for t in tri:
        print("  [%s] %s  methods=%s  %s" % (t.trust, t.location, ",".join(t.methods), t.defect_class))
    if "--sarif" in argv:
        out = argv[argv.index("--sarif") + 1]
        open(out, "w").write(_json.dumps(to_sarif(tri, "claimproof"), indent=2))
        print("SARIF written:", out)
    return 1 if tri else 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
