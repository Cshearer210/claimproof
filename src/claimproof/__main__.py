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

_SUBS = {"demo", "audit", "register", "check"}
_HELP = {"--help", "-h", "help"}

USAGE = """claimproof -- agents claim work is done that isn't. This makes them prove it.

  python -m claimproof              the 30-second demo (a refused claim, then a backed one)
  python -m claimproof check        run every gate over a reply on stdin or a file
                                      exit 0 clean, 1 findings; --format text|json|sarif
  python -m claimproof audit        the check on the checks: is each gate PROVEN in both
                                      directions, or has it never been made to fail?
  python -m claimproof register     the finding register: a defect stays RED until
                                      something proves it is gone

  Library entry points the CLI does not cover: claimproof.hooks (Stop / PreToolUse /
  PostToolUse adapters), claimproof.claude_code install (one-command Claude Code wiring),
  claimproof.ledger (every ask recorded, closed only with evidence), claimproof.basis
  (a closed claim REOPENS when the evidence it cited moves).

  Docs: https://github.com/Cshearer210/claimproof
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _HELP:
        print(USAGE)
        return 0
    sub = argv[0] if argv and argv[0] in _SUBS else "demo"
    rest = argv[1:] if (argv and argv[0] in _SUBS) else argv

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
