#!/usr/bin/env python3
"""Two gates that read code instead of prose. Run it: python source_gates.py

`UnbackedClaims` reads what an agent is about to SAY. These two read what it is
about to WRITE, which is the difference between catching a bad pattern in review
and never letting it land.

Nothing here touches your filesystem. It builds two small source strings in
memory and runs them through the pre-tool-use hook exactly as a runtime would.
"""
import sys

from agentattest.gates import SilentSkip, TypedScope
from agentattest.hooks import gate_invariant, pre_tool_use_hook

# A tool that decides for itself what to look at. It reads as responsible, which
# is why this keeps happening. Its completeness is capped by what the author
# remembered, and a scan of 2 roots prints the same shape of output as a scan of 40.
TYPED_POPULATION = (
    "def audit():\n"
    "    roots = [" + ", ".join(repr("/srv/" + n) for n in ("app", "data")) + "]\n"  # noscope: the example's own bad fixture
    "    return [problem for r in roots for problem in walk(r)]\n"
)

# A check that swallows its own failure. The run stays green and the output is
# identical to the output it produced back when it worked.
SWALLOWED_CHECK = (
    "def check_certificates():\n"
    "    try:\n"
    "        return verify_chain()\n"
    "    except Exception:\n"
    "        return True\n"
)

# The same two ideas, written correctly. A gate that cannot tell these apart from
# the two above gets switched off, and a switched-off gate protects nothing.
FINE = (
    "LOGFILE = '/var/log/app.log'\n"
    "def audit():\n"
    "    roots = discover_roots()\n"
    "    return [problem for r in roots for problem in walk(r)]\n"
    "def check_certificates():\n"
    "    try:\n"
    "        return verify_chain()\n"
    "    except Exception as e:\n"
    "        return None, str(e)\n"
)


def attempt(label: str, filename: str, content: str) -> int:
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": filename, "content": content}}
    invariants = [gate_invariant(TypedScope(), suffixes=(".py",)),
                  gate_invariant(SilentSkip(), suffixes=(".py",))]
    code, message = pre_tool_use_hook(payload, invariants)

    print(f"\n{label}")
    print("-" * len(label))
    for line in content.rstrip().splitlines():
        print(f"  | {line}")
    print()
    if code:
        print(f"  -> REFUSED (exit {code})")
        for line in message.splitlines():
            print(f"     {line}")
    else:
        print("  -> allowed (exit 0)")
    return code


def main() -> int:
    refused_scope = attempt("1. A tool that types its own list of places to look",
                            "audit.py", TYPED_POPULATION)
    refused_skip = attempt("2. A check that reports success when it fails",
                           "certs.py", SWALLOWED_CHECK)
    allowed = attempt("3. The same two ideas, written correctly", "fine.py", FINE)

    print("\nThe third one matters most. Both patterns above have an innocent")
    print("twin that appears in ordinary code constantly: one absolute path is a")
    print("config value, and try/except is how you handle an optional file. A")
    print("gate that cannot tell them apart gets switched off within a week, and")
    print("then everyone still believes it is running.")

    ok = refused_scope and refused_skip and not allowed
    if not ok:                       # a demo whose prose outran its output
        print("\nTHIS SHOULD NOT HAPPEN: the gates did not behave as described.")
        return 1
    return 0


if __name__ == "__main__":
    code = main()
    print(f"\nexit {code}")
    sys.exit(code)
