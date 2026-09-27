#!/usr/bin/env python3
# CALLED BY: fullcircle.pipeline (the drop-in adapter, step D1) and FULL-RESET-GRAPH's mapping stage
#            (step A2/A3). Copied into FULL-RESET-GRAPH so it stands alone.
# FIRES WHEN: a target system is first indexed -- to learn how IT labels each concept, so every
#             downstream detector finds a concept regardless of the target's naming.
"""The portability core: classify code by BEHAVIOUR into shared CONCEPTS, then learn the target
system's own LABELS for each concept and store them, so the synonym tool can detect a concept under
any name (Chris, 2026-09-23: "generate the labels and definitions ... then uses the synonym tool to
detect them during the indexing stages").

WHY THIS IS THE LOAD-BEARING PIECE: a detector that keys on names only works on systems shaped like
the ones it was written against. This classifies by what the code DOES (AST behaviour), then RECORDS
the names it observed so a system that calls its gates "guards" or its tests "specs" is still mapped
correctly. Proven by the renamed-fixture test in selftest(): rename every symbol and the
classification does not move.

No third-party deps. AST only, so it never executes the target's code.
"""
from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field

# The shared concepts (must match finding.py). A target's own labels are LEARNED, not assumed;
# the seed below is only a starting hint for the synonym tool, extended by what is observed.
CONCEPTS = ("gate", "test", "claim", "wire", "definition", "schedule", "instruction",
            "population", "read", "artifact")

# A small seed of label tokens people commonly use per concept. The map GROWS with observed names;
# the seed is never the sole basis for a match -- structural classification is.
SYNONYM_SEED = {
    "gate":  {"gate", "guard", "check", "hook", "validate", "enforce", "assert_ok", "verify"},
    "test":  {"test", "spec", "check", "selftest", "verify", "assert"},
    "claim": {"done", "complete", "finished", "pass", "ok", "success", "shipped"},
    "schedule": {"cron", "timer", "schedule", "job", "loop", "watch", "daily", "nightly"},
}

_CLAIM_WORDS = ("done", "complete", "finished", "all pass", "passes", "tests pass", "suite is green",
                "success", "shipped", "ready")


def rel_id(path: str, root: str) -> str:
    """A path used as an IDENTIFIER: relative to `root`, and always forward-slashed.

    ⛔ WHY THIS IS NOT `os.path.relpath`, and it cost three CI rounds on 2026-09-27. On Windows
    relpath returns `pkg\\test_rel.py`, and anything that KEYS, COMPARES or PUBLISHES that string
    assumes `pkg/test_rel.py`. claimproof's own multi-method selftest keyed its expectations by
    forward slash, so a lookup returned None on Windows and only on Windows -- the test failed
    there while every Linux run stayed green.

    THE DISTINCTION THAT DECIDES WHICH TO USE: a path you are about to OPEN is a filesystem path
    and belongs to the platform -- use `os.path.join`/`relpath` and leave it alone. A path you
    store, key, diff, or write into SARIF is an IDENTIFIER, and an identifier that changes shape
    per platform breaks every reader at once. SARIF requires `/` in a uri regardless of platform,
    so forward slash is the correct answer rather than a convenience for the tests.

    Lives here because `concepts.py` is the contract these repos share, so the definition travels
    with it instead of being re-typed per module (nothing-ships-unwired.md 13-15).
    """
    return os.path.relpath(path, root).replace(os.sep, "/").replace("\\", "/")


@dataclass
class ConceptMap:
    """How ONE target system labels each concept, learned from behaviour."""
    labels: dict[str, set[str]] = field(default_factory=lambda: {c: set() for c in CONCEPTS})
    examples: dict[str, list[str]] = field(default_factory=lambda: {c: [] for c in CONCEPTS})

    def add(self, concept: str, name: str, where: str) -> None:
        self.labels[concept].add(_norm(name))
        if len(self.examples[concept]) < 12:
            self.examples[concept].append("%s (%s)" % (name, where))

    def to_json(self) -> str:
        return json.dumps(
            {"labels": {c: sorted(v) for c, v in self.labels.items()},
             "examples": self.examples}, indent=2, sort_keys=True)


def _norm(name: str) -> str:
    """A comparable label token: split snake/camel, lowercase, drop common affixes."""
    import re
    parts = re.split(r"[_\W]+|(?<=[a-z])(?=[A-Z])", name)
    return " ".join(p.lower() for p in parts if p)


# ---------------------------------------------------------------- behavioural classification
def _func_signals(fn: ast.AST) -> set[str]:
    """The behavioural signals a function body exhibits -- NAME IS NEVER READ."""
    sig = set()
    has_if = False
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            has_if = True
        elif isinstance(node, ast.Assert):
            sig.add("assert")
        elif isinstance(node, ast.Raise):
            sig.add("raise")
        elif isinstance(node, ast.Call):
            tgt = node.func
            dotted = _dotted(tgt)
            # UNDRIFTED 2026-09-26: this was `dotted.endswith("exit")`, which matched ANY call
            # whose dotted name ends in those four letters -- `graceful_exit()`, `on_exit()`,
            # `cleanup_and_exit()`, `runner.exit()` -- so an ordinary shutdown helper was read as a
            # gate signalling failure and misclassified. The same defect also treated a bare
            # `exit()` with no arguments as a nonzero exit, when `exit()` is exit(0), a success.
            #
            # Both were already fixed in the full-circle-optimization copy of this file and never
            # ported back. That is the copy-instead-of-extend failure the repo's own laws name:
            # one shared contract, two versions, the fix living in only one of them. Measured
            # 2026-09-26 by hashing the two files -- 28 lines and 3,819 bytes apart.
            if dotted in ("sys.exit", "os._exit", "os.abort", "exit"):   # real exits only
                if node.args:
                    arg0 = node.args[0]
                    # nonzero or non-constant exit code = a gate signalling failure
                    if not (isinstance(arg0, ast.Constant) and arg0.value in (0, None)):
                        sig.add("exit_nonzero")
                # a bare exit() carries no code, which is exit(0) -- success, not a gate signal
    if has_if and "raise" in sig:
        sig.add("guarded_raise")
    return sig


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + "." + node.attr
    return ""


def classify_function(fn: ast.AST) -> str | None:
    """Return the concept this function's BEHAVIOUR indicates, or None. Name is never inspected."""
    sig = _func_signals(fn)
    # a function that asserts is a test -- unless it is clearly a gate (exits nonzero to signal fail)
    if "assert" in sig and "exit_nonzero" not in sig:
        return "test"
    if "exit_nonzero" in sig or "guarded_raise" in sig:
        return "gate"
    return None


def _claim_strings(tree: ast.AST) -> list[str]:
    """String literals whose content reads as a completion CLAIM (the silent-defect surface)."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if any(w in low for w in _CLAIM_WORDS) and len(node.value) < 120:
                out.append(node.value.strip())
    return out


def build_label_map(root: str) -> ConceptMap:  # nopop: walks an arbitrary TARGET repo passed as arg,
    """Walk a target repo and learn its labels per concept from behaviour."""  # not this system
    cm = ConceptMap()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv",
                   "venv", "build", "dist", ".tox", ".eggs", ".pytest_cache", "site-packages")
                   and not d.endswith(".egg-info")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = rel_id(path, root)
            try:
                src = open(path, encoding="utf-8", errors="replace").read()
                tree = ast.parse(src)
            except (SyntaxError, ValueError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    concept = classify_function(node)
                    if concept:
                        cm.add(concept, node.name, rel)
                elif isinstance(node, ast.Assign):
                    # module-level UPPER_CASE constant = a definition
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 2:
                            cm.add("definition", t.id, rel)
            for s in _claim_strings(tree):
                cm.add("claim", s, rel)
    return cm


def concept_of_label(cm: ConceptMap, label: str) -> str | None:
    """The synonym tool: given a label the target uses, which concept is it? Uses the LEARNED labels
    first (this system's own naming), then the seed. This is what lets indexing find a concept under
    an unfamiliar name."""
    nl = _norm(label)
    for c in CONCEPTS:
        if nl in cm.labels.get(c, set()):
            return c
    for c, seed in SYNONYM_SEED.items():
        if any(tok in nl.split() for tok in seed):
            return c
    return None


# ---------------------------------------------------------------- proof
def selftest() -> int:
    import tempfile, shutil
    ok = True

    def write(root, rel, body):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        open(p, "w", encoding="utf-8").write(body)

    # a synthetic target: a gate (exits nonzero), a test (asserts), a constant, a claim string.
    def make(root, gate_name, test_name):
        write(root, "app/%s.py" % gate_name, (
            "import sys\n"
            "def %s(x):\n"
            "    if not x:\n"
            "        sys.exit(1)\n"
            "    return True\n" % gate_name))
        write(root, "app/%s.py" % test_name, (
            "from app import core\n"
            "def %s():\n"
            "    assert core.go() == 1\n" % test_name))
        write(root, "app/core.py", "MAX_RETRIES = 5\ndef go():\n    print('All tests pass')\n    return 1\n")

    d1 = tempfile.mkdtemp(prefix="cm_a_")
    d2 = tempfile.mkdtemp(prefix="cm_b_")
    try:
        make(d1, "enforce_policy", "verify_widget")     # ordinary labels
        make(d2, "zqx", "wpq")                           # nonsense labels, same behaviour
        m1 = build_label_map(d1)
        m2 = build_label_map(d2)

        # 1. behaviour classified correctly under ordinary names
        if "enforce policy" not in m1.labels["gate"]:
            print("FAIL: gate not learned ->", m1.labels["gate"]); ok = False
        if "verify widget" not in m1.labels["test"]:
            print("FAIL: test not learned ->", m1.labels["test"]); ok = False
        if "max retries" not in m1.labels["definition"]:
            print("FAIL: definition not learned ->", m1.labels["definition"]); ok = False
        if not any("all tests pass" in c.lower() for c in m1.examples["claim"]):
            print("FAIL: claim not learned ->", m1.examples["claim"]); ok = False

        # 2. LABEL-INDEPENDENCE: renamed everything, classification must not move
        if "zqx" not in m2.labels["gate"] or "wpq" not in m2.labels["test"]:
            print("FAIL: renamed target misclassified -> gate=%s test=%s"
                  % (m2.labels["gate"], m2.labels["test"])); ok = False

        # 3. the count of gates/tests is identical across the two despite different names
        if len(m1.labels["gate"]) != len(m2.labels["gate"]) or \
           len(m1.labels["test"]) != len(m2.labels["test"]):
            print("FAIL: catch rate moved when names changed"); ok = False

        # 4. synonym tool: a label THIS system used maps back to its concept
        if concept_of_label(m1, "enforce_policy") != "gate":
            print("FAIL: learned label not resolved"); ok = False
        # 5. synonym seed: an unseen-but-common word resolves without being in the target
        if concept_of_label(m1, "nightly_job") != "schedule":
            print("FAIL: seed synonym not resolved"); ok = False
        # 6. a plainly-unrelated label resolves to nothing (no over-match)
        if concept_of_label(m1, "banana_smoothie") is not None:
            print("FAIL: over-matched an unrelated label"); ok = False
    finally:
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)

    # ------------------------------------------------------------------ mutation hardening
    # ⭐ MERGED 2026-09-27, on Chris's instruction, and this block is the reason the merge was worth
    # doing. This file is described in both repos as the ONE SHARED CONTRACT, copied verbatim -- and
    # the two copies had drifted 28 lines apart, each holding guard cases the other lacked. Neither
    # was "the good one": claimproof carried the sys.exit(None), over-length-claim, to_json ordering
    # and name-ends-in-exit guards; full-circle carried the bare sys.exit(), short-non-claim,
    # pruned-directory and UPPER_CASE-vs-lowercase guards. Picking a survivor would have DELETED
    # four real guard cases, which is why build-it-right-once law 8 says merge the good parts of
    # EACH rather than choosing.
    #
    # ⛔ AND IT WAS MOVED OUT OF THE `finally:` CLAUSE IT USED TO SIT INSIDE. It ran, so nothing was
    # red -- but assertions about `classify_function` have nothing to do with tearing down two temp
    # directories, and anything that made the try body raise would have run them during unwinding.
    # The full-circle copy already had them at function level; that is the shape kept.
    #
    # Every case below is a MUTANT KILLER: it names the one-character change it would catch. A test
    # that only checks the happy path leaves those mutants alive, and a detector with live mutants
    # is one that can silently stop detecting.

    # --- has_if: the initialiser, the in-branch assignment, and the `and` that joins them
    fn_ro = ast.parse("def only_raises(x):\n    raise ValueError('bad')\n").body[0]
    if classify_function(fn_ro) is not None:
        print("FAIL: unconditional raise wrongly classified ->", classify_function(fn_ro)); ok = False

    fn_gr = ast.parse(
        "def only_guarded_raise(x):\n    if not x:\n        raise ValueError('bad')\n").body[0]
    if classify_function(fn_gr) != "gate":
        print("FAIL: if-guarded raise should classify as gate ->", classify_function(fn_gr)); ok = False

    # an `if` with no raise/assert/exit is not a gate -- kills `has_if and "raise" in sig` -> `or`
    fn_io = ast.parse("def pick(x):\n    if x:\n        return 1\n    return 0\n").body[0]
    if classify_function(fn_io) is not None:
        print("FAIL: an if-only function (no raise) must not classify ->",
              classify_function(fn_io)); ok = False

    # --- assert AND exit_nonzero is a gate, never a test. Kills the `and` -> `or` in the verdict.
    fn_ga = ast.parse("import sys\ndef gate_with_assert(x):\n    assert x is not None\n"
                      "    if not x:\n        sys.exit(1)\n    return True\n").body[1]
    if classify_function(fn_ga) != "gate":
        print("FAIL: assert+exit_nonzero should classify as gate, not test ->",
              classify_function(fn_ga)); ok = False

    # --- what counts as a FAILING exit. Four shapes, and only one of them is a gate.
    fn_en = ast.parse("import sys\ndef maybe_exit_none(x):\n    if not x:\n"
                      "        sys.exit(None)\n    return True\n").body[1]
    if classify_function(fn_en) is not None:
        print("FAIL: sys.exit(None) should not count as a failing gate ->",
              classify_function(fn_en)); ok = False

    # a bare sys.exit() has no code, so it is exit(0). Ported from the full-circle copy: before the
    # undrift, arg0 was set to None here and read as a nonzero exit.
    fn_bse = ast.parse("import sys\ndef f():\n    print('done')\n    sys.exit()\n").body[1]
    if classify_function(fn_bse) is not None:
        print("FAIL: bare sys.exit() wrongly classified as gate ->",
              classify_function(fn_bse)); ok = False

    fn_be = ast.parse("def done(x):\n    if x:\n        exit()\n    return True\n").body[0]
    if classify_function(fn_be) is not None:
        print("FAIL: bare exit() is exit(0) and must not classify as a gate ->",
              classify_function(fn_be)); ok = False

    # MUST-FIRE CONTROL: a real failing exit still classifies, so none of the guards above can be
    # satisfied by a detector that simply stopped looking.
    fn_re = ast.parse("import sys\ndef guard(x):\n    if not x:\n"
                      "        sys.exit(2)\n    return True\n").body[1]
    if classify_function(fn_re) != "gate":
        print("FAIL: sys.exit(2) must still classify as a gate ->", classify_function(fn_re)); ok = False

    # --- A NAME THAT MERELY ENDS IN "exit" IS NOT AN EXIT. This is the case the old
    # `dotted.endswith("exit")` got wrong: it matched 191 call sites across this machine, including
    # argparse's own `parser.exit()`. Four shapes, because the fix must hold for all of them.
    for src, label in (("def shutdown(x):\n    if not x:\n        graceful_exit()\n    return True\n",
                       "graceful_exit()"),
                      ("def stop(runner):\n    if runner:\n        runner.exit()\n    return True\n",
                       "runner.exit() is a method call, not a process exit"),
                      ("def cleanup():\n    on_exit('normal shutdown')\n", "on_exit() callback"),
                      ("def cleanup():\n    handle_exit()\n", "handle_exit() callback")):
        fn_x = ast.parse(src).body[0]
        if classify_function(fn_x) is not None:
            print("FAIL: %s is not an exit and must not classify as a gate ->" % label,
                  classify_function(fn_x)); ok = False

    # --- claim strings: long ones are excluded, short real ones are kept, short plain ones are not.
    # Kills the `and len < 120` -> `or`, in BOTH directions.
    claims_long = _claim_strings(ast.parse("x = " + repr("done " * 30) + "\n"))
    if claims_long:
        print("FAIL: over-length claim-like string wrongly captured ->", claims_long); ok = False

    claims_short = _claim_strings(ast.parse("y = 'all tests pass'\n"))
    if not any("all tests pass" in c.lower() for c in claims_short):
        print("FAIL: short claim string not captured"); ok = False

    plain = _claim_strings(ast.parse('label = "just a short plain name"\n'))
    if any("just a short plain name" in c for c in plain):
        print("FAIL: short non-claim string collected as claim ->", plain); ok = False

    # --- to_json must sort its keys, or two runs over one system produce different bytes
    cm_json = ConceptMap().to_json()
    if cm_json.index('"examples"') > cm_json.index('"labels"'):
        print("FAIL: to_json is not sort_keys=True (examples should precede labels)"); ok = False

    # --- VENDORED DIRECTORIES ARE PRUNED. Ported from the full-circle copy, and it is the only
    # assertion here that exercises the real directory walk. Kills the `and not endswith` -> `or`
    # that would let .venv, node_modules and site-packages be scanned as if they were the target's
    # own code -- which reads as a richer result rather than as a bug.
    d3 = tempfile.mkdtemp(prefix="cm_prune_")
    try:
        os.makedirs(os.path.join(d3, ".venv"), exist_ok=True)
        os.makedirs(os.path.join(d3, "app"), exist_ok=True)
        with open(os.path.join(d3, ".venv", "vend.py"), "w", encoding="utf-8") as f:
            f.write("import sys\ndef vendored_gate(x):\n    if not x:\n        sys.exit(1)\n")
        with open(os.path.join(d3, "app", "real.py"), "w", encoding="utf-8") as f:
            f.write("import sys\ndef real_gate(x):\n    if not x:\n        sys.exit(1)\n")
        m3 = build_label_map(d3)
        if "vendored gate" in m3.labels["gate"]:
            print("FAIL: pruned dir (.venv) was scanned ->", m3.labels["gate"]); ok = False
        if "real gate" not in m3.labels["gate"]:
            print("FAIL: the un-pruned dir was not scanned either, so pruning proves nothing ->",
                  m3.labels["gate"]); ok = False
    finally:
        shutil.rmtree(d3, ignore_errors=True)

    # --- a DEFINITION is an UPPER_CASE module-level name. Both directions, ported from full-circle.
    d4 = tempfile.mkdtemp(prefix="cm_def_")
    try:
        os.makedirs(os.path.join(d4, "app"), exist_ok=True)
        with open(os.path.join(d4, "app", "m.py"), "w", encoding="utf-8") as f:
            f.write("GOOD_CONST = 9\nlower_case = 5\n")
        m4 = build_label_map(d4)
        if "good const" not in m4.labels["definition"]:
            print("FAIL: UPPER_CASE constant not learned ->", m4.labels["definition"]); ok = False
        if "lower case" in m4.labels["definition"]:
            print("FAIL: lowercase name wrongly learned as definition ->",
                  m4.labels["definition"]); ok = False
    finally:
        shutil.rmtree(d4, ignore_errors=True)

    # --- rel_id is an IDENTIFIER builder, so it is forward-slashed on every platform. This is the
    # guard for the defect that cost three CI rounds on 2026-09-27.
    if rel_id(os.path.join("pkg", "sub", "mod.py"), ".") != "pkg/sub/mod.py":
        print("FAIL: rel_id leaked a platform separator ->",
              rel_id(os.path.join("pkg", "sub", "mod.py"), ".")); ok = False

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
