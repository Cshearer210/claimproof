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
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
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
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            try:
                tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    yield rel, node


def _reraises(h) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(h))


def _pass_only(h) -> bool:
    body = [s for s in h.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                      and isinstance(s.value.value, str))]  # ignore a docstring
    return len(body) == 1 and isinstance(body[0], (ast.Pass,))


def _returns_clean(h) -> bool:
    return any(isinstance(n, ast.Return) and n.value is not None and _clean_const(n.value)
               for n in ast.walk(h))


def method_silent_swallow(root: str) -> list[Finding]:
    """The handler does nothing observable: pass-only, or returns a clean value, and never re-raises."""
    out = []
    for rel, h in _handlers(root):
        if _reraises(h):
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
        if _reraises(h):
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


METHODS = {
    "test-cannot-fail": [method_weak_oracle, method_return_ignored],
    "swallowed-exception": [method_silent_swallow, method_returns_success_in_except],
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
