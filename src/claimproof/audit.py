"""`claimproof audit` -- is each gate in your project PROVEN, or only plausible?

`Gate.verify()` answers one question: do this gate's own cases agree with this
gate's own code? That is necessary and it is not sufficient, because the cases
are written by the same hand as the gate. A gate can pass verify() while its
proof rests on nothing:

  * Its must-fire case is caught by an accident -- remove the gate's logic
    entirely and the case still "fails", because something else in the pipeline
    flagged it. The case was never load-bearing.
  * Its guard case is empty text, or a sentence with nothing in common with the
    bad one. The gate has been shown to stay quiet on something it was never
    going to fire on, which proves nothing about the cases that matter.

Ported from ~/Tools/detector_guard.py, built after a day on which four numbers
collapsed at once: one new detector reported 342 unreachable modules where the
real number was 13, and another reported 108 where the real number was 15.
Neither looked broken. An over-firing detector does not look broken -- it looks
like a discovery, and a discovery becomes a plan, a task, and a week.

HOW THIS ANSWERS THAT, and it is a MUTATION, never an opinion:

    neuter the gate (inspect returns nothing)     every must-fire case MUST break
    jam the gate open (inspect always fires)      every guard case MUST break

A gate that survives either mutation has cases that do not depend on it. That
is measurable, deterministic, and impossible to argue with -- which is the only
kind of proof worth having about a proof.

    python -m claimproof audit claimproof.gates     # a module
    python -m claimproof audit ./src/myproject      # a package directory
    python -m claimproof audit . --quiet            # exit 1 if anything is unproven

EXIT CODES. 0 every gate proven, 1 at least one unproven, 2 could not tell --
which includes finding NO gates at all. A tool that looked at nothing and
reported clean is the exact failure this library exists for, so an empty
population is never a pass.
"""
from __future__ import annotations

import difflib
import importlib
import importlib.util
import os
import inspect as _inspect
import pkgutil
import sys
from dataclasses import dataclass
from pathlib import Path

from claimproof.core import Case, Finding, Gate, SelftestError

__all__ = ["GateAudit", "audit_gates", "discover_gates", "main",
           "PROVEN", "UNPROVEN", "BROKEN", "UNAUDITABLE", "EXEMPT",
           "GUARD_SIMILARITY_FLOOR"]

PROVEN = "proven"
UNPROVEN = "UNPROVEN"
BROKEN = "BROKEN"
#: The gate takes constructor arguments, so this audit cannot build one to
#: mutate. That is NOT a defect in the gate -- `NothingLeft(ledger)` and
#: `StillRed(register)` are built that way on purpose, because they answer
#: against live state. Calling them BROKEN would be exactly the over-firing this
#: module exists to catch, so they get their own verdict and a run containing one
#: exits 2: could not tell, never clean.
UNAUDITABLE = "unknown"
#: A gate may declare, about ITSELF, that it is not meant to pass an audit --
#: `audit_exempt = "why"` on the class. The demo ships a gate that cannot catch
#: its own case ON PURPOSE, because the demo exists to show one being refused.
#: The reason is printed, so an exemption is a statement somebody made and can be
#: read, never a list of names in this file that nobody maintains.
EXEMPT = "exempt"

#: How close a guard case has to be to some must-fire case before it counts as
#: proof that the gate DISCRIMINATES rather than merely stays quiet.
#:
#: This number is load-bearing, so it is proven by mutation in `selftest()`:
#: raising it far enough must make a known-good gate go WEAK, and lowering it to
#: zero must make a known-weak one pass. A threshold nobody has moved has never
#: been tested (see how-we-work law 8).
GUARD_SIMILARITY_FLOOR = 0.25


@dataclass(frozen=True)
class GateAudit:
    """What one gate's proof is actually worth."""

    name: str
    verdict: str
    detail: str
    cases: int = 0
    must_fire: int = 0
    guards: int = 0

    def line(self) -> str:
        counts = f"{self.cases} cases ({self.must_fire} must-fire, {self.guards} guard)"
        return f"  {self.verdict:8s} {self.name:28s} {counts}\n           {self.detail}"


# ---------------------------------------------------------------- discovery
def _gates_in_module(mod) -> list[type[Gate]]:
    """Concrete gates DEFINED in this module.

    This module is skipped entirely: `_Real` and `_FarGuard` below exist so the
    audit can prove itself, and an instrument that reports its own fixtures as
    findings is the oldest failure there is. Excluded by identity, not by name,
    so renaming a fixture cannot quietly put it back in the population.
    """
    if mod.__name__ == __name__:
        return []
    out = []
    for _n, obj in vars(mod).items():
        if (_inspect.isclass(obj) and issubclass(obj, Gate) and obj is not Gate
                and not _inspect.isabstract(obj)
                and obj.__module__ == mod.__name__):
            out.append(obj)
    return out


def discover_gates(target: str) -> tuple[list[type[Gate]], list[str]]:
    """Every concrete Gate reachable from `target`, and what could not be read.

    The population is DISCOVERED -- imported and walked -- never a list of class
    names somebody typed. A typed list is a list of what the author remembered,
    and the gate added last week is exactly the one missing from it.

    Returns (gates, problems). A non-empty `problems` means the answer is
    incomplete, and the caller must report UNKNOWN rather than a verdict.
    """
    gates: list[type[Gate]] = []
    problems: list[str] = []
    seen: set[type[Gate]] = set()

    def take(mod) -> None:
        for g in _gates_in_module(mod):
            if g not in seen:
                seen.add(g)
                gates.append(g)

    path = Path(target)
    if path.exists():
        # A directory or a file on disk: put its parent on the path and import
        # every module under it by name, so relative imports inside the package
        # still resolve.
        root = path if path.is_dir() else path.parent
        # A directory holding __init__.py is a PACKAGE. Loading its files one by
        # one gives each a top-level module name, so any relative import inside
        # it dies with "no known parent package" and that module drops silently
        # out of the population. Import it as a package instead.
        if path.is_dir() and (path / "__init__.py").exists():
            sys.path.insert(0, str(path.resolve().parent))
            return discover_gates(path.resolve().name)
        sys.path.insert(0, str(root.resolve().parent))
        sys.path.insert(0, str(root.resolve()))
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for f in files:
            if f.name.startswith("_") and f.name != "__init__.py":
                continue
            modname = f.stem
            try:
                spec = importlib.util.spec_from_file_location(modname, f)
                if spec is None or spec.loader is None:
                    problems.append(f"{f}: no import machinery could load it")
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules.setdefault(modname, mod)
                spec.loader.exec_module(mod)
            except Exception as exc:                       # noqa: BLE001
                problems.append(f"{f.name}: {type(exc).__name__}: {exc}")
                continue
            take(mod)
        return gates, problems

    if os.sep in target or (os.altsep and os.altsep in target):
        # It looks like a path and it is not there. Importing it as a module name
        # produces "No module named '/home/.../src/claimproof'", which sends the
        # reader looking for an import problem that does not exist.
        return [], [f"{target}: no such file or directory"]

    try:
        mod = importlib.import_module(target)
    except Exception as exc:                               # noqa: BLE001
        return [], [f"{target}: {type(exc).__name__}: {exc}"]
    take(mod)
    if hasattr(mod, "__path__"):                           # a package: walk it
        for info in pkgutil.walk_packages(mod.__path__, mod.__name__ + "."):
            try:
                take(importlib.import_module(info.name))
            except Exception as exc:                       # noqa: BLE001
                problems.append(f"{info.name}: {type(exc).__name__}: {exc}")
    return gates, problems


# ------------------------------------------------------------------- audit
def _survives(gate: Gate, replacement) -> bool:
    """Does this gate still pass its own cases with `replacement` for inspect()?

    If it does, the cases were never testing the gate.
    """
    gate.inspect = replacement          # type: ignore[method-assign]
    try:
        gate.verify()
        return True
    except SelftestError:
        return False
    except Exception:                                      # noqa: BLE001
        # A gate that explodes under mutation did not survive it.
        return False


def _guard_distance(cases: list[Case]) -> float:
    """How close the NEAREST guard gets to any must-fire case.

    A guard case that shares nothing with the bad ones proves the gate stays
    quiet on text it was never going to fire on. What proves discrimination is
    a guard that LOOKS like the bad case and is still left alone.
    """
    bad = [c.text for c in cases if c.expect_flagged]
    good = [c.text for c in cases if not c.expect_flagged]
    if not bad or not good:
        return 0.0
    return max(difflib.SequenceMatcher(None, g, b).ratio()
               for g in good for b in bad)


def audit_gate(cls: type[Gate]) -> GateAudit:
    """Audit one gate class. Never raises: a gate that explodes is a verdict."""
    try:
        probe = cls()
        cases = list(probe.selftest_cases() or [])
        name = probe.name
    except TypeError as exc:
        # It needs arguments. A gate that answers against live state is SUPPOSED
        # to take them -- this audit simply cannot supply one, which is a limit
        # of the audit and not a fault in the gate.
        return GateAudit(getattr(cls, "name", None) or cls.__name__, UNAUDITABLE,
                         f"takes constructor arguments ({exc}), so this audit cannot "
                         f"build one to mutate. It needs a fixture in its own tests; "
                         f"not reporting it either proven or broken")
    except Exception as exc:                               # noqa: BLE001
        return GateAudit(getattr(cls, "name", None) or cls.__name__, BROKEN,
                         f"could not even be constructed: {type(exc).__name__}: {exc}")

    declared = getattr(cls, "audit_exempt", "")
    if declared:
        return GateAudit(name, EXEMPT, "exempt by its own declaration: %s" % declared,
                         cases=len(cases),
                         must_fire=sum(1 for c in cases if c.expect_flagged),
                         guards=sum(1 for c in cases if not c.expect_flagged))

    n_fire = sum(1 for c in cases if c.expect_flagged)
    n_guard = len(cases) - n_fire
    base = dict(cases=len(cases), must_fire=n_fire, guards=n_guard)

    try:
        cls().verify()
    except SelftestError as exc:
        return GateAudit(name, BROKEN, str(exc), **base)
    except Exception as exc:                               # noqa: BLE001
        return GateAudit(name, BROKEN,
                         f"verify() raised {type(exc).__name__}: {exc}", **base)

    if _survives(cls(), lambda text: []):
        return GateAudit(name, UNPROVEN,
                         "passes its own cases with its logic removed entirely, so no "
                         "must-fire case actually depends on this gate", **base)

    if _survives(cls(), lambda text: [Finding("audit mutation")]):
        return GateAudit(name, UNPROVEN,
                         "passes its own cases while firing on everything, so no guard "
                         "case actually depends on this gate", **base)

    near = _guard_distance(cases)
    if near < GUARD_SIMILARITY_FLOOR:
        return GateAudit(name, UNPROVEN,
                         "its closest guard case is only %.2f similar to any must-fire "
                         "case (floor %.2f) -- it has been shown to stay quiet on text it "
                         "was never going to fire on"
                         % (near, GUARD_SIMILARITY_FLOOR), **base)

    return GateAudit(name, PROVEN,
                     "fails when neutered, fails when jammed open, and its closest guard "
                     "is %.2f similar to a must-fire case" % near, **base)


def audit_gates(gates) -> list[GateAudit]:
    return [audit_gate(g) for g in gates]


# -------------------------------------------------------------------- CLI
def report(target: str, rows: list[GateAudit], problems: list[str],
           quiet: bool = False) -> int:
    unproven = [r for r in rows if r.verdict in (UNPROVEN, BROKEN)]
    unknown = [r for r in rows if r.verdict == UNAUDITABLE]
    exempt = [r for r in rows if r.verdict == EXEMPT]

    if not quiet:
        for r in rows:
            print(r.line())

    # EMPTY IS NOT A FINDING. Nothing discovered means the audit could not look,
    # which is a different answer from "everything is fine".
    if not rows:
        print(f"\nUNKNOWN: no gate was found under {target!r}. "
              f"Not reporting clean -- an audit of nothing is not an audit.")
        for p in problems:
            print(f"  could not read: {p}")
        return 2

    print(f"\n{len(rows) - len(unproven) - len(unknown) - len(exempt)} of "
          f"{len(rows) - len(exempt)} auditable gate(s) proven under {target!r}"
          + (f", {len(exempt)} exempt by declaration" if exempt else ""))
    if unknown:
        print(f"{len(unknown)} could not be audited here (they take constructor "
              f"arguments); UNKNOWN is not a pass.")
    if problems:
        print(f"{len(problems)} module(s) could not be read, so this count is a FLOOR:")
        for p in problems:
            print(f"  {p}")
    if unproven:
        print("A gate whose proof does not depend on the gate is not a proof.")
        return 1
    if unknown or problems:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    # Read the flags off THIS list, never off sys.argv. An earlier version
    # consulted sys.argv for --selftest, so the flag worked from a shell and
    # silently did nothing when main() was called as a library -- a function
    # that behaves differently depending on who called it is untestable.
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return selftest()
    quiet = "--quiet" in args
    positional = [x for x in args if not x.startswith("-")]
    target = positional[0] if positional else "claimproof.gates"
    gates, problems = discover_gates(target)
    return report(target, audit_gates(gates), problems, quiet=quiet)


# --------------------------------------------------------------- selftest
class _Real(Gate):
    """A gate whose proof is genuine: the guard is a near miss of the bad case."""

    name = "fixture-real"

    def inspect(self, text):
        return [Finding("says done with no receipt")] if "done, no receipt" in text else []

    def selftest_cases(self):
        return [Case(text="the migration is done, no receipt at all", expect_flagged=True),
                Case(text="the migration is done, receipt attached", expect_flagged=False)]


class _FarGuard(Gate):
    """Fires and stays quiet, but its guard has nothing to do with the bad case."""

    name = "fixture-far-guard"

    def inspect(self, text):
        return [Finding("x")] if "done, no receipt" in text else []

    def selftest_cases(self):
        return [Case(text="the migration is done, no receipt at all", expect_flagged=True),
                Case(text="z", expect_flagged=False)]


def selftest() -> int:
    """Prove the audit itself, in both directions, against synthetic gates.

    Every fixture below is constructed here. Nothing reads live data, so a
    result cannot change because the repository did.
    """
    fails: list[str] = []

    real = audit_gate(_Real)
    if real.verdict != PROVEN:
        fails.append(f"a genuinely proven gate was reported {real.verdict}: {real.detail}")

    far = audit_gate(_FarGuard)
    if far.verdict != UNPROVEN:
        fails.append(f"a gate whose guard proves nothing was reported {far.verdict}")

    # MUTATION ON THE THRESHOLD ITSELF. A number nobody has moved has never been
    # tested: if the floor can be doubled with no change in verdict, the floor
    # was not doing the work.
    global GUARD_SIMILARITY_FLOOR
    keep = GUARD_SIMILARITY_FLOOR
    try:
        GUARD_SIMILARITY_FLOOR = 0.99
        if audit_gate(_Real).verdict == PROVEN:
            fails.append("raising the guard floor to 0.99 changed nothing -- "
                         "the threshold is not load-bearing")
        GUARD_SIMILARITY_FLOOR = 0.0
        if audit_gate(_FarGuard).verdict != PROVEN:
            fails.append("lowering the guard floor to 0.0 still rejected the far guard -- "
                         "the verdict is not coming from the threshold")
    finally:
        GUARD_SIMILARITY_FLOOR = keep

    # An empty population must be UNKNOWN, never clean.
    if report("nothing", [], [], quiet=True) != 2:
        fails.append("an audit that found no gates did not exit 2")

    # A real broken gate must be BROKEN, not merely unproven.
    class _Broken(Gate):
        name = "fixture-broken"

        def inspect(self, text):
            return []

        def selftest_cases(self):
            return [Case(text="anything", expect_flagged=True),
                    Case(text="anything else", expect_flagged=False)]

    if audit_gate(_Broken).verdict != BROKEN:
        fails.append("a gate that cannot flag its own bad case was not reported BROKEN")

    # A gate that takes an argument is NOT broken, and a run holding one is not clean.
    class _NeedsArg(Gate):
        name = "fixture-needs-arg"

        def __init__(self, thing):
            super().__init__()
            self.thing = thing

        def inspect(self, text):
            return []

        def selftest_cases(self):
            return [Case("a", True), Case("b", False)]

    needs = audit_gate(_NeedsArg)
    if needs.verdict != UNAUDITABLE:
        fails.append(f"a gate taking a constructor argument was reported {needs.verdict}, "
                     f"which is a false accusation against a working gate")
    if report("x", [GateAudit("a", PROVEN, ""), needs], [], quiet=True) != 2:
        fails.append("a run containing an unauditable gate did not exit 2")

    # Discovery must actually find the real gates in this package.
    found, probs = discover_gates("claimproof.gates")
    if len(found) < 8:
        fails.append(f"discovery found only {len(found)} gate(s) in claimproof.gates")
    if probs:
        fails.append(f"discovery could not read: {probs}")

    for f in fails:
        print("  FAIL " + f)
    if not fails:
        print("  ok:   proven/unproven/broken told apart, threshold proven by mutation, "
              "an empty population reports UNKNOWN")
    print("claimproof.audit selftest: %s" % ("PASS" if not fails else "FAIL"))
    return 1 if fails else 0


if __name__ == "__main__":   # pragma: no cover - module entry
    raise SystemExit(main())
