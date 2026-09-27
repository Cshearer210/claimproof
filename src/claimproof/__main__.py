"""`python -m claimproof [demo|check|audit|register]`.

No argument runs the demo, which is what it has always done and what a link in
the README points at. The subcommands are additions, never a change to that.

`--help` lists them. That is not decoration: without it, a newcomer who types the
one flag every CLI answers gets the demo instead, and leaves believing the demo
is all there is. Measured 2026-09-26 on a clean install -- `check` and `audit`
were unreachable to anyone who had not read the README first, which is the wrong
way round for a tool whose whole argument is that evidence should be easy to
produce.
"""
import sys

_SUBS = {"demo", "audit", "register", "check", "doctor"}
_HELP = {"--help", "-h", "help"}

USAGE = """claimproof -- agents claim work is done that isn't. This makes them prove it.

  claimproof                        the 30-second demo (a refused claim, then a backed one)
  claimproof doctor                 verify THIS install actually works, before trusting it
  claimproof check                  run every gate over a reply on stdin or a file
                                      exit 0 clean, 1 findings; --format text|json|sarif
  claimproof audit                  the check on the checks: is each gate PROVEN in both
                                      directions, or has it never been made to fail?
  claimproof register               the finding register: a defect stays RED until
                                      something proves it is gone

  `python -m claimproof ...` does the same thing, and always has.

  Library entry points the CLI does not cover: claimproof.hooks (Stop / PreToolUse /
  PostToolUse adapters), claimproof.claude_code install (one-command Claude Code wiring),
  claimproof.ledger (every ask recorded, closed only with evidence), claimproof.basis
  (a closed claim REOPENS when the evidence it cited moves).

  Docs: https://github.com/Cshearer210/claimproof
"""

#: Optional extras. A gate that cannot be imported because ONE of these is absent is expected on a
#: plain install and is not a defect; anything else that fails to import is. Named individually,
#: never as a pattern, so a real import error can never hide behind one.
_OPTIONAL_DEPS = ("crewai", "deadcanary", "langchain", "autogen", "dbt")


def doctor(argv=None) -> int:
    """Verify the INSTALL, not the checkout. Names every check, then PASS or FAIL.

    ⛔ WHY A TOOL LIKE THIS NEEDS ONE MORE THAN MOST: its entire argument is that a fluent claim and
    a correct one feel identical, and that you should not be asked to take either on trust. A
    package making that argument cannot ask to be trusted on its word either. The tests live beside
    the source, not in the wheel, so nothing a stranger runs after `pip install` exercises anything.

    ⭐ CHECK 4 IS THE REAL ONE, and it uses this package's OWN audit machinery rather than a
    re-implementation: every gate it publishes must be PROVEN -- shown to fire on a case that must
    fire AND to stay quiet on a guard case. A gate never made to fail is indistinguishable from one
    that cannot.
    """
    checks, failed = [], 0

    def ck(name, fn):
        nonlocal failed
        try:
            detail = fn()
            checks.append(("ok", name, detail or ""))
        except Exception as exc:                                   # noqa: BLE001
            failed += 1
            checks.append(("FAIL", name, "%s: %s" % (type(exc).__name__, exc)))

    def _real_package():
        import claimproof
        f = getattr(claimproof, "__file__", None)
        if not f:
            raise RuntimeError("imported, but __file__ is None -- an empty namespace package, not a "
                               "real install")
        return f

    def _public_api():
        # the population is __all__ itself, never a typed list: a typed list goes stale the first
        # time a name is added, and it goes stale silently.
        import claimproof
        missing = [n for n in claimproof.__all__ if not hasattr(claimproof, n)]
        if missing:
            raise RuntimeError("promised by __all__ and absent from the install: %s"
                               % ", ".join(missing))
        return "%d public names, all resolvable" % len(claimproof.__all__)

    def _version_agrees():
        # The suite SKIPS this when the package is not installed, which is correct for a checkout and
        # useless to a stranger -- whose copy IS installed, and may be a stale one shadowing a newer
        # source tree. Here it is a real check.
        import claimproof
        from importlib.metadata import PackageNotFoundError, version
        try:
            installed = version("claimproof")
        except PackageNotFoundError:
            raise RuntimeError("no distribution metadata for 'claimproof' -- it was not installed, "
                               "so this is a source tree on sys.path rather than an install")
        if installed != claimproof.__version__:
            raise RuntimeError("the installed distribution says %s and the package says %s -- a "
                               "stale install is shadowing a newer source tree"
                               % (installed, claimproof.__version__))
        return "distribution and package agree: %s" % installed

    def _published_gates_are_proven():
        import claimproof
        from claimproof import audit_gates
        published = [getattr(claimproof, n) for n in claimproof.__all__
                     if isinstance(getattr(claimproof, n, None), type)
                     and issubclass(getattr(claimproof, n), claimproof.Gate)
                     and getattr(claimproof, n) is not claimproof.Gate]
        if not published:
            raise RuntimeError("this install publishes no gates at all")
        # a gate needing constructor arguments cannot be audited this way; that is a known limit and
        # it is NAMED rather than counted as a pass.
        auditable, needs_args = [], []
        for g in published:
            try:
                g()
            except TypeError:
                needs_args.append(g.__name__)
            else:
                auditable.append(g)
        if not auditable:
            raise RuntimeError("no published gate could be constructed, so none could be audited")
        bad = [(a.name, a.verdict) for a in audit_gates(auditable) if a.verdict != "proven"]
        if bad:
            raise RuntimeError("published gate(s) not proven in both directions: %s"
                               % ", ".join("%s=%s" % x for x in bad))
        return ("all %d auditable published gate(s) proven in both directions%s"
                % (len(auditable),
                   "; %d take constructor args and were not audited: %s"
                   % (len(needs_args), ", ".join(needs_args)) if needs_args else ""))

    def _discovery_is_complete_enough():
        from claimproof import discover_gates
        gates, problems = discover_gates("claimproof")
        if not gates:
            raise RuntimeError("no gates discovered at all -- UNKNOWN, and never clean")
        unexpected = [p for p in problems
                      if not any(("'%s'" % dep) in p or ("No module named %r" % dep) in p
                                 or dep in p for dep in _OPTIONAL_DEPS)]
        if unexpected:
            raise RuntimeError("%d discovery problem(s) not explained by a missing optional extra: "
                               "%s" % (len(unexpected), "; ".join(u[:90] for u in unexpected[:2])))
        return ("%d gate(s) discovered; %d unreadable and every one of those is an optional extra "
                "that is not installed" % (len(gates), len(problems)))

    ck("the installed package is real, not an empty namespace", _real_package)
    ck("every public name is importable from the install", _public_api)
    ck("the installed version is not a stale copy shadowing newer source", _version_agrees)
    ck("every published gate is PROVEN in both directions", _published_gates_are_proven)
    ck("gate discovery is complete, or its gaps are all optional extras",
       _discovery_is_complete_enough)

    for state, name, detail in checks:
        sys.stdout.write("  %-4s %s%s\n" % (state + ":", name, ("  -- " + detail) if detail else ""))
    sys.stdout.write("claimproof doctor: %s (%d check(s), %d failure(s))\n"
                     % ("PASS" if not failed else "FAIL", len(checks), failed))
    return 0 if not failed else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _HELP:
        print(USAGE)
        return 0
    sub = argv[0] if argv and argv[0] in _SUBS else "demo"
    rest = argv[1:] if (argv and argv[0] in _SUBS) else argv

    if sub == "doctor":
        return doctor(rest)
    if sub == "audit":
        from claimproof.audit import main as run
        return run(rest)
    if sub == "register":
        from claimproof.register import main as run
        return run(rest)
    if sub == "check":
        from claimproof.report import main as run
        return run(rest)
    from claimproof.demo import main as run
    return run()


if __name__ == "__main__":
    sys.exit(main())
