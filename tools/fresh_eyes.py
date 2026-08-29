#!/usr/bin/env python3
"""Be the stranger who just found this repo, not the person who wrote it.

    python tools/fresh_eyes.py              # the whole rehearsal
    python tools/fresh_eyes.py --selftest   # prove this rehearsal can fail
    python tools/fresh_eyes.py --act 2      # one act, while working on it

CALLED BY: .github/workflows/ci.yml (job `fresh-eyes`) and CONTRIBUTING.md

`verify_wheel.py` already proves the PACKAGE works from a clean install: it runs
the test suite from outside the source tree. That is the code being right.

This asks the different question, and it is the one that decides whether anybody
keeps the library: **does the published product work when you do what it says?**
The two fail independently. Documentation rots on its own schedule -- a README
example can reference a keyword argument that was renamed two releases ago while
every test passes, and nothing in this repo would notice, because nothing in
this repo has ever executed the README.

Four acts, each a thing a real first-time user does in their first ten minutes:

  1. Install it the way a stranger does -- from the built artifact, into an
     empty environment, with the source tree NOT importable.
  2. Do exactly what the README says, top to bottom, in that environment.
  3. Point it at somebody else's code. Every gate here has only ever been aimed
     at this project's own fixtures, which were written to suit it.
  4. Run the headline one-command integration in a throwaway project and make it
     actually refuse a turn.

Exit 0 only if a newcomer would have had all four work.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from verify_wheel import clean_install, step  # noqa: E402  - the shared clean environment

README = REPO / "README.md"

#: A ```python block in the README must carry one of these on the line before it.
#: An unmarked block FAILS act 2 rather than being skipped, so a block added next
#: month cannot quietly fall out of coverage -- the same reason `Coverage` refuses
#: to call an unexamined member a pass.
RUN = "<!-- fresh-eyes: run -->"
SHOW = "<!-- fresh-eyes: illustration -->"

#: Above this share of a foreign codebase, a source gate is not finding a real
#: pattern, it is describing normal code. An over-firing gate does not look
#: broken -- it looks like a discovery -- so the ceiling is stated, not felt.
OVER_FIRING = 0.25

FAILURES: list[str] = []


def say(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  {'ok   ' if ok else 'FAIL '} {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


# --------------------------------------------------------------- act 2
def readme_blocks(text: str) -> tuple[list[tuple[str, int]], list[str]]:
    """Every ```python block, split into (body, expected_exit) and the unmarked ones.

    `run exit=1` is for an example whose whole point is a non-zero exit -- the
    Harness one ends `raise SystemExit(h.run())` and a BROKE check exits 1.
    Demanding 0 there would have forced a correct example to be marked as
    decoration, which is how coverage quietly shrinks.
    """
    runnable, unmarked = [], []
    pattern = r"(?:<!-- fresh-eyes: (run|illustration)( exit=\d+)? -->\s*\n)?```python\n(.*?)```"
    for m in re.finditer(pattern, text, re.S):
        kind, exit_spec, body = m.group(1), m.group(2), m.group(3)
        if kind == "run":
            runnable.append((body, int(exit_spec.split("=")[1]) if exit_spec else 0))
        elif kind != "illustration":
            first = body.strip().splitlines()[0] if body.strip() else "<empty>"
            unmarked.append(first[:70])
    return runnable, unmarked


def act_readme(py: Path, room: Path) -> None:
    print("\n2. Do what the README says, in that environment.")
    text = README.read_text(encoding="utf-8")
    runnable, unmarked = readme_blocks(text)

    if not say(not unmarked, "every python block in the README declares whether it runs",
               f"{len(unmarked)} unmarked: {'; '.join(unmarked[:3])}" if unmarked else ""):
        print(f"        add {RUN} or {SHOW} on the line above each one")

    say(bool(runnable), "the README has runnable examples at all", f"{len(runnable)} found")

    work = room / "readme"
    work.mkdir(exist_ok=True)
    for i, (body, want_exit) in enumerate(runnable, 1):
        script = work / f"block_{i}.py"
        script.write_text(body, encoding="utf-8")
        r = subprocess.run([str(py), str(script)], cwd=str(work), capture_output=True,
                           text=True, timeout=300)
        first = body.strip().splitlines()[0][:56]
        if not say(r.returncode == want_exit, f"README block {i} runs: {first}",
                   f"exit {r.returncode}, wanted {want_exit}"):
            print((r.stderr or "")[-700:])


# --------------------------------------------------------------- act 3
FOREIGN_PROBE = r'''
import pathlib, sys, json
from claimproof.gates import TypedScope, SilentSkip

root = pathlib.Path(sys.argv[1])
files = sorted(p for p in root.glob("*.py") if p.stat().st_size < 200_000)[:250]
out = {}
for gate in (TypedScope(), SilentSkip()):
    gate.verify()
    hits, examples = 0, []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = gate.inspect(text)
        if found:
            hits += 1
            if len(examples) < 3:
                examples.append(f"{p.name}: {found[0]}")
    out[gate.name] = {"files": len(files), "hits": hits, "examples": examples}
print(json.dumps(out))
'''


def act_foreign(py: Path, room: Path) -> None:
    print("\n3. Point it at somebody else's code.")
    corpus = Path(sysconfig.get_paths()["stdlib"])
    if not say(corpus.is_dir(), "a foreign codebase to aim at", str(corpus)):
        return

    probe = room / "probe.py"
    probe.write_text(FOREIGN_PROBE, encoding="utf-8")
    r = subprocess.run([str(py), str(probe), str(corpus)], cwd=str(room),
                       capture_output=True, text=True, timeout=900)
    if not say(r.returncode == 0, "the gates run against unfamiliar code without crashing",
               (r.stderr or "")[-200:]):
        return

    for name, d in json.loads(r.stdout).items():
        rate = d["hits"] / d["files"] if d["files"] else 0.0
        say(rate <= OVER_FIRING,
            f"{name} is not describing normal code",
            f"{d['hits']} of {d['files']} files ({rate:.1%}), ceiling {OVER_FIRING:.0%}")
        for ex in d["examples"]:
            print(f"          e.g. {ex}")


# --------------------------------------------------------------- act 4
def act_headline(py: Path, room: Path) -> None:
    print("\n4. The one-command integration, end to end.")
    project = room / "someones-project"
    (project / ".claude").mkdir(parents=True, exist_ok=True)

    r = subprocess.run([str(py), "-m", "claimproof.claude_code", "install"],
                       cwd=str(project), capture_output=True, text=True, timeout=300)
    if not say(r.returncode == 0, "`python -m claimproof.claude_code install` succeeds",
               (r.stderr or "")[-200:]):
        return

    settings = project / ".claude" / "settings.json"
    if not say(settings.is_file(), "it wrote a settings file where Claude Code reads one"):
        return
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        say(False, "the settings file it wrote is valid JSON", str(exc))
        return
    say("claimproof.claude_code" in json.dumps(data),
        "the installed hook names claimproof, not the old package name")

    # A real Stop payload points at a transcript file. The fixture has to look
    # like a turn that DID something: the gate deliberately ignores turns with no
    # tool calls, because a hook that nags small talk gets uninstalled and then
    # catches nothing. The first draft of this rehearsal wrote a bare text turn,
    # got "allowed", and would have reported a working library as broken.
    def turn(text: str, *, worked: bool = True) -> str:
        lines = []
        if worked:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": "core.py", "new_string": "x = 1"}}]},
            }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }))
        # sha1, NOT hash(). Python randomises hash() per process (PYTHONHASHSEED), so the same
        # transcript text produced a DIFFERENT filename on every run -- the fixture could never
        # be written twice to the same place, and a rerun left a second copy behind instead of
        # replacing the first. Nothing parses this name, so the format is free to change.
        import hashlib as _hl
        _stem = _hl.sha1(text.encode("utf-8")).hexdigest()[:10]
        path = room / f"t{_stem}{'w' if worked else 'q'}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    # The unbacked claim must name NO file. A filename is evidence -- "a file and
    # line" is one of the things the gate accepts -- so a fixture saying "I edited
    # core.py and fixed it" is correctly allowed, and reads as the library being
    # broken when it is the fixture that is wrong. This rehearsal made that exact
    # mistake twice before the text below was measured rather than assumed.
    worked = "I fixed the parser bug. All tests pass."
    backed = worked + "\n```\n316 passed in 14.2s\n```\n"

    probe = room / "decide.py"
    probe.write_text(
        "import json, sys\n"
        "from claimproof.claude_code import decide\n"
        "print(json.dumps(decide({'transcript_path': sys.argv[1], 'stop_hook_active': False})))\n",
        encoding="utf-8")

    cases = (
        ("refuses an unbacked claim", turn(worked), True),
        ("allows the same claim with its receipt", turn(backed), False),
        # The guard case, and the reason anybody keeps the hook installed.
        ("leaves a turn that did no work alone", turn(worked, worked=False), False),
    )
    for label, transcript, want_block in cases:
        r = subprocess.run([str(py), str(probe), transcript], cwd=str(room),
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            say(False, label, (r.stderr or "")[-300:])
            continue
        verdict = json.loads(r.stdout or "null")
        blocked = bool(verdict)
        say(blocked == want_block, label,
            "blocked" if blocked else "allowed")


# --------------------------------------------------------------- selftest
def selftest() -> int:
    """Break each act on purpose. A rehearsal that cannot fail proves nothing."""
    print("fresh_eyes selftest\n")
    ok = True

    runnable, unmarked = readme_blocks(f"{RUN}\n```python\nprint(1)\n```\n")
    ok &= say(runnable == [("print(1)\n", 0)] and not unmarked,
              "a marked block is collected to run, expecting exit 0")

    runnable, _ = readme_blocks("<!-- fresh-eyes: run exit=1 -->\n```python\nraise SystemExit(1)\n```\n")
    ok &= say(runnable == [("raise SystemExit(1)\n", 1)],
              "an example that exits non-zero ON PURPOSE keeps its expected code")

    runnable, unmarked = readme_blocks("```python\nprint(1)\n```\n")
    ok &= say(not runnable and bool(unmarked),
              "an UNMARKED block is reported, never skipped quietly")

    runnable, unmarked = readme_blocks(f"{SHOW}\n```python\nthis is not python\n```\n")
    ok &= say(not runnable and not unmarked, "an illustration is neither run nor complained about")

    # The guard case: a bash block is not a python block, and must not be dragged in.
    runnable, unmarked = readme_blocks("```bash\npip install claimproof\n```\n")
    ok &= say(not runnable and not unmarked, "a bash block is left alone")

    before = len(FAILURES)
    say(False, "a deliberately failed check is recorded")
    ok &= say(len(FAILURES) == before + 1, "...and it lands in the failure list")
    FAILURES.clear()

    print("\n" + ("selftest PASSED" if ok else "selftest FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="prove this rehearsal can fail")
    ap.add_argument("--act", type=int, choices=(2, 3, 4), help="run one act only")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print(f"claimproof through fresh eyes, {sys.version.split()[0]}")
    print("Nothing below imports the source tree.\n")
    print("1. Install it the way a stranger does.")

    with tempfile.TemporaryDirectory() as tmp:
        room = Path(tmp)
        py = clean_install(room, extras=())
        if py is None:
            return 1

        r = subprocess.run([str(py), "-c",
                            "import claimproof,sys;"
                            "sys.exit(0 if 'site-packages' in claimproof.__file__ else 1)"],
                           cwd=str(room), capture_output=True, text=True, timeout=300)
        say(r.returncode == 0, "the installed copy is what gets imported, not the checkout")

        acts = {2: act_readme, 3: act_foreign, 4: act_headline}
        for n, fn in acts.items():
            if args.act in (None, n):
                fn(py, room)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} thing(s) a newcomer would have hit:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    if args.act:
        print(f"Act {args.act} is clean. The other acts did not run, so this is not a verdict.")
    else:
        print("A stranger following the README gets a working library.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
