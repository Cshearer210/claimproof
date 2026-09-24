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
            if dotted.endswith("exit"):                     # sys.exit / os._exit / exit
                arg0 = node.args[0] if node.args else None
                # nonzero or non-constant exit code = a gate signalling failure
                if arg0 is None or not (isinstance(arg0, ast.Constant) and arg0.value in (0, None)):
                    sig.add("exit_nonzero")
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
            rel = os.path.relpath(path, root)
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

        # --- mutation-hardening additions (concepts.py survivors) ---
        # L72/L75/L88: has_if init/set + "has_if and raise" guard
        raise_only_src = (
            "def only_raises(x):\n"
            "    raise ValueError('bad')\n"
        )
        fn_ro = ast.parse(raise_only_src).body[0]
        if classify_function(fn_ro) is not None:
            print("FAIL: unconditional raise wrongly classified ->", classify_function(fn_ro)); ok = False

        guarded_raise_src = (
            "def only_guarded_raise(x):\n"
            "    if not x:\n"
            "        raise ValueError('bad')\n"
        )
        fn_gr = ast.parse(guarded_raise_src).body[0]
        if classify_function(fn_gr) != "gate":
            print("FAIL: if-guarded raise should classify as gate ->", classify_function(fn_gr)); ok = False

        # L105: assert AND exit_nonzero -> gate, never test
        gate_assert_src = (
            "import sys\n"
            "def gate_with_assert(x):\n"
            "    assert x is not None\n"
            "    if not x:\n"
            "        sys.exit(1)\n"
            "    return True\n"
        )
        fn_ga = ast.parse(gate_assert_src).body[1]
        if classify_function(fn_ga) != "gate":
            print("FAIL: assert+exit_nonzero should classify as gate, not test ->", classify_function(fn_ga)); ok = False

        # L86: sys.exit(None) (explicit) must NOT count as a failing exit
        exit_none_src = (
            "import sys\n"
            "def maybe_exit_none(x):\n"
            "    if not x:\n"
            "        sys.exit(None)\n"
            "    return True\n"
        )
        fn_en = ast.parse(exit_none_src).body[1]
        if classify_function(fn_en) is not None:
            print("FAIL: sys.exit(None) should not count as a failing gate ->", classify_function(fn_en)); ok = False

        # L118: a claim-like word in a string too long (>=120 chars) must NOT be captured
        long_claim_src = "x = " + repr("done " * 30) + "\n"
        claims_long = _claim_strings(ast.parse(long_claim_src))
        if claims_long:
            print("FAIL: over-length claim-like string wrongly captured ->", claims_long); ok = False

        short_claim_src = "y = 'all tests pass'\n"
        claims_short = _claim_strings(ast.parse(short_claim_src))
        if not any("all tests pass" in c.lower() for c in claims_short):
            print("FAIL: short claim string not captured"); ok = False

        # L58: to_json must be sort_keys=True (top-level "examples" < "labels" alphabetically)
        cm_json = ConceptMap().to_json()
        if cm_json.index('"examples"') > cm_json.index('"labels"'):
            print("FAIL: to_json is not sort_keys=True (examples should precede labels)"); ok = False
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
