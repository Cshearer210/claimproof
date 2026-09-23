"""Ground truth: check a completion claim against REALITY, not just against the words near it.

Every other gate in claimproof reads the reply TEXT. That is enough to catch a claim with no
evidence, but it cannot catch a claim whose evidence is FABRICATED -- "Created config/settings.yaml"
next to no such file, "results are in output/summary.json" when the file is outputs/summary.json,
"Implemented the handler" when the handler's body is `raise NotImplementedError`. A competitor
(veridict) beats a text-only gate here, and Chris's own law is the fix: *query the thing; verify by
running, never by reading the description of it.*

This gate checks the two ground-truth classes a standalone, no-network, stdlib tool can settle from
the filesystem alone:

    cited-artifact-missing  a path the reply says it CREATED / WROTE / where results ARE, that does
                            not exist under the project root. A near-miss sibling (same basename in
                            another dir) makes it a slightly-wrong-filename; otherwise a not-written.
    placeholder-body        a claim to have IMPLEMENTED / FINISHED a named source file whose body is
                            still a placeholder (TODO / FIXME / pass-only / raise NotImplementedError).

The classes that need a live runtime -- a fabricated exit code, a claim contradicted by the real
git diff, a stale number -- are NOT guessed at here; they need the exit status / git / source the
Stop-hook runtime already holds, and are declared as the runtime adapter this gate leaves open
(see `runtime_findings`), rather than half-done in a way that reads as covered.

No network. Reads the filesystem; never writes to it.
"""
from __future__ import annotations

import os
import re
import tempfile

from claimproof.core import Case, Finding, Gate

__all__ = ["GroundTruth"]

# a path-like token: a slash-bearing or extensioned path, quoted or bare
_PATH = re.compile(r"[`'\"]?((?:~?/)?(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,6})[`'\"]?")
# a line that ASSERTS an artifact was PRODUCED. Deliberately only strong production verbs -- a bare
# "see X" or "in X" is a reference, not a claim of production, and flagging it is crying wolf (the
# guard case "See core.py:41." must stay quiet).
_MADE = re.compile(r"(creat|wrote|writ|generat|saved|produc|\boutput\b|"
                   r"results?\s+(?:are\s+|is\s+)?in\b)", re.I)
# a line that ASSERTS a named source is finished
_DONE_IMPL = re.compile(r"\b(implement|finish|complet|wrote|add(?:ed)?)\w*\b", re.I)
_PLACEHOLDER = re.compile(r"\bTODO\b|\bFIXME\b|raise NotImplementedError|^\s*pass\s*$|\.\.\.\s*$", re.M)


class GroundTruth(Gate):
    """Refuse a completion claim whose cited artifact is not really there.

    `root` is the project the claim is about (default: cwd). Cited ABSOLUTE paths are checked as
    given, so the selftest can point at a hermetic temp world and prove both directions without
    touching the project.
    """

    def __init__(self, root: str | None = None) -> None:
        super().__init__()
        self.root = root or os.getcwd()

    # ------------------------------------------------------------------ resolve
    def _abs(self, tok: str) -> str:
        tok = os.path.expanduser(tok)
        return tok if os.path.isabs(tok) else os.path.join(self.root, tok)

    def _basename_exists_elsewhere(self, tok: str) -> bool:
        base = os.path.basename(tok)
        # only search within the root (or the token's own parent's parent) -- cheap, bounded
        base_dir = self.root
        for dirpath, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".git")]
            if base in files:
                return True
        return False

    # ------------------------------------------------------------------ inspect
    def inspect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[str] = set()
        for ln, line in enumerate(text.splitlines(), 1):
            made = _MADE.search(line)
            impl = _DONE_IMPL.search(line)
            if not (made or impl):
                continue
            for m in _PATH.finditer(line):
                tok = m.group(1)
                if tok in seen or "/" not in tok and "." not in tok:
                    continue
                # ignore command-ish tokens and obvious non-artifacts
                if tok.endswith((".", "/")) or " " in tok:
                    continue
                # a file:line reference (core.py:41) is a code location, not an artifact claim
                after = line[m.end():m.end() + 2]
                if after[:1] == ":" and after[1:2].isdigit():
                    continue
                ap = self._abs(tok)
                exists = os.path.exists(ap)
                if made and not exists:
                    seen.add(tok)
                    if self._basename_exists_elsewhere(tok):
                        findings.append(Finding(
                            message="cited artifact %r does not exist; a file of that name exists "
                                    "elsewhere -- a near-miss path (slightly-wrong-filename)" % tok,
                            line=ln, excerpt=line.strip()[:80]))
                    else:
                        findings.append(Finding(
                            message="cited artifact %r was claimed created/produced but is not on "
                                    "disk (file-not-actually-written)" % tok,
                            line=ln, excerpt=line.strip()[:80]))
                elif impl and exists and tok.endswith(".py"):
                    try:
                        body = open(ap, encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    if _PLACEHOLDER.search(body) and len(body.strip()) < 400:
                        seen.add(tok)
                        findings.append(Finding(
                            message="claims %r is implemented, but its body is still a placeholder "
                                    "(TODO/pass/NotImplementedError)" % tok,
                            line=ln, excerpt=line.strip()[:80]))
        return findings

    # ------------------------------------------------------------------ selftest
    def selftest_cases(self) -> list[Case]:
        # a hermetic temp world: one real file, one placeholder file, and an absent path
        d = getattr(self, "_fx", None)
        if d is None:
            d = tempfile.mkdtemp(prefix="gt_selftest_")
            with open(os.path.join(d, "summary.json"), "w") as f:
                f.write("{}\n")
            with open(os.path.join(d, "handler.py"), "w") as f:
                f.write("def handle():\n    raise NotImplementedError  # TODO\n")
            with open(os.path.join(d, "real.py"), "w") as f:
                f.write("def handle():\n    return 42\n")
            self._fx = d
        missing = os.path.join(d, "settings.yaml")          # never created
        present = os.path.join(d, "summary.json")            # exists
        placeholder = os.path.join(d, "handler.py")          # exists, placeholder body
        real = os.path.join(d, "real.py")                    # exists, real body
        return [
            Case(text="Created %s with the production values." % missing,
                 expect_flagged=True, name="bad: created a file that is absent"),
            Case(text="Implemented the handler in %s." % placeholder,
                 expect_flagged=True, name="bad: implemented, but body is a placeholder"),
            Case(text="The results are in %s." % present,
                 expect_flagged=False, name="guard: cited file really exists"),
            Case(text="Implemented the handler in %s." % real,
                 expect_flagged=False, name="guard: implemented and the body is real"),
            Case(text="Fixed the parser and the tests pass.",
                 expect_flagged=False, name="guard: no path cited at all"),
        ]

    # ------------------------------------------------------- runtime adapter (declared, not faked)
    def runtime_findings(self, text: str, runtime) -> list[Finding]:
        """The ground-truth classes that need a LIVE runtime the reply text cannot supply -- a real
        exit code, a real git diff, a re-measured number. `runtime` is an adapter the Stop hook
        provides (it already holds the turn's real tool results). Returns [] when no adapter is
        given, so this gate never PRETENDS to have checked what it could not. Built out as the
        Stop-hook integration lands; declared here so the boundary is explicit, not silent."""
        if runtime is None:
            return []
        findings: list[Finding] = []
        claimed = runtime.claimed_exit(text) if hasattr(runtime, "claimed_exit") else None
        real = runtime.real_exit() if hasattr(runtime, "real_exit") else None
        if claimed is not None and real is not None and claimed != real:
            findings.append(Finding(
                message="claims exit=%s but the real captured exit was %s (fabricated-exit-code)"
                        % (claimed, real)))
        return findings
