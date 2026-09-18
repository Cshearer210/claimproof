# claimproof 0.16.0 — release draft

**This is a draft. Nothing is published until you reply `release`.**

What it is: the public version on PyPI is **0.15.0**, from 29 August. This is
what has been built since. Releasing means anyone running `pip install
claimproof` gets this version instead.

**Do item 3 first** — merge pull request #47 — or this would publish code the
public repository does not contain.

---

## What a stranger gets that they did not have before

### Three new checks, each ported from something that caught a real incident

**Merge dropped a side.** Catches a claim that two things were combined sitting
next to a receipt showing one side was taken whole and the other thrown away.
It needs both halves before it fires, because either one alone is ordinary work.
A genuine merge anywhere in the same turn clears it.

**Wrong file name.** Catches a claim citing a file by a name that the output
itself spells differently. It only fires on a near miss, so a file simply not
shown stays a different check's question — one problem never produces two
complaints.

**Claimed to have read it.** Catches a claim to have read a named file where the
only evidence is a search. "I searched X" is honest and is never flagged.

### `claimproof audit` — the check on the checks

This is the part worth talking about publicly. It proves each check's own tests
are load-bearing, by breaking the check on purpose: switch it off and every test
that should fire must break; jam it permanently on and every test that should
stay quiet must break. A test that survives both is proving nothing.

It also rejects a "should stay quiet" case that is too different from any "must
fire" case to demonstrate the check can tell them apart.

It finds the checks by walking the code, never from a typed list. An audit that
found no checks at all exits with "could not tell" rather than "clean" — a tool
that looked at nothing must never report success.

### `claimproof.Register` — findings stay red until something proves they are gone

One row per problem. Finding the same one again raises its count instead of
creating a second row. Closing one needs evidence and refuses bare claim-words,
and a problem that comes back goes red again.

The part that matters: it closes only what was inside the area actually
examined, and reports everything else as NOT RE-EXAMINED. From outside,
"fixed" and "nobody looked" are identical, and treating them the same is how a
board goes green while the problems are still there.

---

## Bugs fixed, including two the library had in itself

**A check could pass its own proof without being tested.** Two checks built
their internal test by naming their own class directly, so a modified version
tested the ORIGINAL's behaviour and reported itself proven. Found by a test that
tried to break one and could not.

**A sentence was being cut at a dot inside a filename.** "Merged tools.py and
tools_old.py" was truncated at `tools.` and the second file vanished, so the
check could not see that two things were being combined.

**A command-line flag worked from a terminal and silently did nothing when
called from code**, because it read the process arguments instead of its own.

**Auditing the whole package reported its own test fixtures as findings.** It
now excludes itself, by identity rather than by name.

**Loading a folder of checks broke on any file that imported a sibling.** A
folder is now loaded as a package rather than as loose files.

---

## Suggested release text, ready to paste

> **claimproof 0.16.0**
>
> Adds `claimproof audit`, which checks the checks: it breaks each gate on
> purpose in both directions and fails any whose own test cases survive, because
> a test that cannot fail proves nothing.
>
> Also adds a persistent register — findings stay red until something proves
> they are gone, and it reports what was never re-examined separately from what
> was fixed, because from outside those look the same.
>
> Three new gates, and two fixes to cases where a gate could pass its own proof
> without being tested.

---

## What I need from you

**Reply `release`** and I publish it.

**Reply `hold`** and it sits here.

**Reply with a change** and I will rewrite it — the release text above is the
part that goes out under your name, so it should sound like you.
