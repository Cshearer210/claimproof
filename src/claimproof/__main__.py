"""`python -m claimproof [demo|audit|register]`.

No argument runs the demo, which is what it has always done and what a link in
the README points at. The subcommands are additions, never a change to that.
"""
import sys

_SUBS = {"demo", "audit", "register"}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = argv[0] if argv and argv[0] in _SUBS else "demo"
    rest = argv[1:] if (argv and argv[0] in _SUBS) else argv

    if sub == "audit":
        from claimproof.audit import main as run
        return run(rest)
    if sub == "register":
        from claimproof.register import main as run
        return run(rest)
    from claimproof.demo import main as run
    return run()


if __name__ == "__main__":
    sys.exit(main())
