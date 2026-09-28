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

__all__ = ["GroundTruth", "Runtime"]

# Directory names and suffixes marking a copy that is NOT the one that runs. Editing one of these
# while claiming to have patched the plain name is the wrong-copy-edited class.
_NOT_LIVE_DIRS = {".archive", "archive", "archives", "backup", "backups", "_backup", "old",
                  "_old", ".old", "dist", "build", "vendor", "node_modules", "site-packages",
                  ".venv", "venv", ".trash", "trash", "migration-backup", "_moved"}
_NOT_LIVE_SUFFIX = (".bak", ".orig", ".old", ".save", ".copy", ".backup")
#: a verb asserting an EDIT to something that already exists, as opposed to creating it
_EDITED = re.compile(r"\b(patch|fix|edit|updat|chang|modif|correct|amend|tweak)\w*\b", re.I)
#: a verb asserting something was TAKEN OUT
_REMOVED = re.compile(r"\b(remov|delet|strip|drop|took\s+out|taken\s+out|cleared|"
                      r"got\s+rid\s+of)\w*\b", re.I)
#: a cited exit code, in the shapes a turn actually writes one
_CLAIMED_EXIT = re.compile(r"\bexit(?:\s*code|\s*status|ed)?\s*[=:]?\s*(\d+)", re.I)
#: words too common to identify what a claim was about
_STOPWORDS = frozenset("""the a an and or of to from in on at for with by is are was were be been
    it its this that these those i we you he she they them my our your all any some no not
    have has had do does did will would can could should may might must then than so if
    but as into out up down over under again more most other same such only own now
    code codes line lines file files path paths change changes work working done fix fixed
    removed remove removing added add adding""".split())

# a path-like token: a separator-bearing or extensioned path, quoted or bare.
#
# ⛔ BOTH SEPARATORS, AND THE DRIVE LETTER, SINCE 2026-09-27 -- this was `(?:~?/)?(?:[\w.-]+/)*`,
# forward slashes only, and it made this gate BLIND ON WINDOWS in the exact way this library exists
# to argue against. Given a claim citing a Windows path -- a drive letter, then backslash-separated
# directories, then the file -- it could not span the backslashes, so it captured the bare basename
# `handler.py`, resolved that against the project root instead of the real directory, found nothing,
# and returned NO FINDING. Not an error: a clean result. Every cited artifact with a directory in it
# was invisible on Windows.
#
# (This comment deliberately DESCRIBES that path rather than writing one. The first draft spelled it
# out and `test_no_private_paths` refused the file -- correctly, since a drive-letter home directory
# is exactly the shape it stops reaching a public repo. The test caught its own author.)
#
# Caught by CI's own matrix on PR #49: 3 failed / 488 passed on windows-latest across py3.10-3.13
# while every ubuntu job was green, with the must-fire case "bad: implemented, but body is a
# placeholder" reported as PASSING. That matrix exists because of a previous instance of this same
# class -- `ci.yml` says so: "a checker whose paths only existed on Linux: on Windows it scanned
# nothing, reported CLEAN, and exited 0 for months."
# ⚠ AND THE TILDE IS NOT OPTIONAL EITHER, which the first attempt at this fix got wrong.
# Windows hands out 8.3 SHORT NAMES, and a tilde sits in the MIDDLE of the directory name:
# measured off the CI log, the runner's temp directory is `...\Users\RUNNER~1\AppData\Local\Temp\...`.
# A character class of `[\w.-]` breaks the chain at that tilde, so the drive-letter fix alone still
# captured nothing and windows stayed red on the same case. `os.path.expanduser` only expands a
# LEADING tilde, so carrying it in the class costs nothing and a real short name resolves.
_PATH = re.compile(
    r"[`'\"]?("
    r"(?:[A-Za-z]:)?"                 # optional Windows drive, C:
    r"(?:[\\/])?"                     # optional leading separator -- POSIX /abs, or C:\
    r"(?:[\w.~-]+[\\/])*"             # directories, EITHER separator, tilde allowed (8.3 names)
    r"[\w.~-]+\.[A-Za-z0-9]{1,6}"     # basename.ext
    r")[`'\"]?")
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
    @staticmethod
    def _native(tok: str) -> str:
        """A cited path may use either separator, whoever wrote the reply and whatever OS reads it.

        A reply written on Windows carries backslashes and is read here; one written on Linux
        carries forward slashes and is read on Windows. Both must resolve, so the separator is
        normalised to this machine's before anything touches the filesystem -- `os.path.isabs`,
        `os.path.join` and `os.path.basename` all answer for the HOST, so a foreign separator makes
        every one of them quietly wrong rather than raising.

        A literal backslash is a legal character in a POSIX filename, so this is a deliberate
        trade: treating it as a separator is right for a CITED PATH in prose, and the alternative --
        what this code did until 2026-09-27 -- is missing every Windows path in silence.
        """
        return tok.replace("\\", os.sep).replace("/", os.sep)

    def _abs(self, tok: str) -> str:
        tok = os.path.expanduser(self._native(tok))
        return tok if os.path.isabs(tok) else os.path.join(self.root, tok)

    def _basename_exists_elsewhere(self, tok: str) -> bool:
        base = os.path.basename(self._native(tok))
        # only search within the root (or the token's own parent's parent) -- cheap, bounded
        base_dir = self.root
        for dirpath, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".git")]
            if base in files:
                return True
        return False

    # ------------------------------------------------------------- wrong copy
    @staticmethod
    def _not_live(tok: str) -> bool:
        """True when a cited path is a copy that is not the one that runs."""
        parts = [p.lower() for p in re.split(r"[\\/]+", tok) if p]
        if any(p in _NOT_LIVE_DIRS for p in parts[:-1]):
            return True
        last = parts[-1] if parts else ""
        return last.endswith(_NOT_LIVE_SUFFIX)

    def _wrong_copy(self, text: str) -> list[Finding]:
        """A claim to have patched a file, where the only edit shown is to a NON-LIVE copy of it.

        ⛔ THE FAILURE, and this system has paid for it more than once: the fix is real, the
        command ran, the file changed -- and the file that changed was the copy in `.archive/`,
        `backup/` or `dist/`. The live one is untouched. Nothing errors, the turn shows a genuine
        receipt, and the bug is still there when somebody looks again.

        ⭐ THIS NEEDS NO RUNTIME, which is why it is here rather than in the runtime adapter. The
        contradiction is entirely inside the turn: the CLAIM names a bare filename and the
        RECEIPT names a path under a directory whose whole purpose is to not be live.

        ⚠ TWO GUARDS, both because the honest version of this turn must stay quiet. If the claim
        itself names the archive path -- "patched .archive/2026-01/server.js" -- nothing is
        hidden and it is not flagged. And if the same basename is ALSO edited at a live path in
        the same turn, both copies were touched and the live one is covered.
        """
        out: list[Finding] = []
        reported: set[str] = set()
        cited: dict[str, list[str]] = {}
        for m in _PATH.finditer(text):
            tok = m.group(1)
            base = os.path.basename(self._native(tok)).lower()
            backup = base.endswith(_NOT_LIVE_SUFFIX)
            # ⚠ A BACKUP SIBLING HAS NO SEPARATOR AND A DIFFERENT BASENAME, and requiring one of
            # each is how `settings.py.bak` beside a claim about `settings.py` went unnoticed --
            # caught by this gate's own must-fire case. So a backup-suffixed token needs no
            # directory, and is ALSO indexed under the name with the suffix stripped, which is the
            # name the claim will use.
            if not ("/" in tok or "\\" in tok) and not backup:
                continue
            cited.setdefault(base, []).append(tok)
            if backup:
                cited.setdefault(base.rsplit(".", 1)[0], []).append(tok)
        for ln, line in enumerate(text.splitlines(), 1):
            if not _EDITED.search(line):
                continue
            for bm in re.finditer(r"[`'\"]?([\w.~-]+\.[A-Za-z0-9]{1,6})[`'\"]?", line):
                base = bm.group(1)
                # ⚠ LOOK AT THE CHARACTER BEFORE THE MATCH, not inside it. This regex matches the
                # basename WITHIN a longer path, so `group(0)` of `.archive/2026-01/server.js` is
                # just `server.js` and carries no separator -- which made the gate flag a claim
                # that honestly named the archive path. Its own guard case caught it.
                before = line[:bm.start(1)]
                if before.endswith(("/", "\\")):
                    continue                      # the claim names a full path: nothing hidden
                key = base.lower()
                if key in reported or key not in cited:
                    continue
                paths = cited[key]
                if not paths or not all(self._not_live(p) for p in paths):
                    continue                      # a live copy was edited too -- covered
                reported.add(key)
                out.append(Finding(
                    message=("claims %r was patched, but the only edit shown in this turn is to "
                             "%s -- a copy that is not the one that runs (wrong-copy-edited)"
                             % (base, ", ".join(paths[:2]))),
                    line=ln, excerpt=line.strip()[:80]))
        return out

    # ------------------------------------------------------------------ inspect
    def inspect(self, text: str) -> list[Finding]:
        findings: list[Finding] = list(self._wrong_copy(text))
        seen: set[str] = set()
        for ln, line in enumerate(text.splitlines(), 1):
            made = _MADE.search(line)
            impl = _DONE_IMPL.search(line)
            if not (made or impl):
                continue
            for m in _PATH.finditer(line):
                tok = m.group(1)
                if tok in seen or not ("/" in tok or "\\" in tok or "." in tok):
                    continue
                # ignore command-ish tokens and obvious non-artifacts
                if tok.endswith((".", "/", "\\")) or " " in tok:
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
            # ⛔ THE WINDOWS CASE, AND IT RUNS ON EVERY OS ON PURPOSE.
            # Until 2026-09-27 `_PATH` matched forward slashes only, so a cited path with
            # backslashes collapsed to its bare basename, resolved against the wrong directory, and
            # produced NO FINDING -- a clean result rather than an error. CI's windows jobs caught
            # it; nothing on Linux could have. Writing the case with the separators SWAPPED means
            # the ubuntu jobs now fail too if that regex or `_native` regresses, instead of leaving
            # the whole class to a platform most local runs never exercise.
            Case(text="Implemented the handler in %s."
                      % placeholder.replace(os.sep, "\\" if os.sep == "/" else "/"),
                 expect_flagged=True,
                 name="bad: placeholder body cited with the OTHER separator (windows-shaped path)"),
            Case(text="The results are in %s."
                      % present.replace(os.sep, "\\" if os.sep == "/" else "/"),
                 expect_flagged=False,
                 name="guard: existing file cited with the OTHER separator stays quiet"),
            # ---- wrong-copy-edited: the fix landed in a copy that is not the one that runs
            Case(text="Patched server.js -- the fix is in.\n"
                      "$ sed -i 's/a/b/' .archive/2026-01/server.js",
                 expect_flagged=True, name="bad: patched the archived copy, claimed the live name"),
            Case(text="Fixed the handler in cli.py.\n$ python3 -c \"...\" dist/cli.py",
                 expect_flagged=True, name="bad: edited the built copy under dist/"),
            Case(text="Updated settings.py.\n$ vim settings.py.bak",
                 expect_flagged=True, name="bad: edited a .bak of it"),
            Case(text="Patched .archive/2026-01/server.js, which is the one I meant.",
                 expect_flagged=False,
                 name="guard: the claim names the archive path -- nothing is hidden"),
            Case(text="Patched server.js.\n$ sed -i 's/a/b/' src/server.js\n"
                      "$ sed -i 's/a/b/' .archive/2026-01/server.js",
                 expect_flagged=False,
                 name="guard: the LIVE copy was edited too, so it is covered"),
            Case(text="Fixed the parser and the tests pass.",
                 expect_flagged=False, name="guard: an edit claim naming no file at all"),
        ]

    # ----------------------------------------------------------- runtime adapter
    def runtime_report(self, text: str, runtime) -> tuple[list[Finding], list[str]]:
        """(findings, unchecked) for the classes that need a LIVE runtime.

        ⛔ WHY THIS RETURNS TWO LISTS AND `runtime_findings` DID NOT. A class this gate could not
        check and a class it checked and found clean are both an empty finding list, and those are
        not the same answer. An adapter with no git access reported exactly what a repository with
        an honest diff reports -- nothing -- so a caller could print "no problems" having looked at
        one class out of three. `unchecked` is the third outcome: could not tell, never clean.

        ⚠ AND CAPABILITY IS DECLARED, NOT SNIFFED. This used `hasattr` on the adapter, which makes
        absent-and-fine indistinguishable from present-and-fine -- the exact shape the rule against
        guarding a measurement behind `hasattr` exists to stop. An adapter now says what it can see
        via `capabilities()`, and anything it does not claim lands in `unchecked`.

        ⛔ NOTHING HERE RUNS A COMMAND OUT OF THE REPLY. A reply is untrusted text; executing what
        it claims to have run would be the worst imaginable way to verify it. The CALLER measures
        -- a Stop hook already holds the turn's real exit codes, and a real `git diff` is one
        read-only command away -- and this only compares.
        """
        if runtime is None:
            return [], ["fabricated-exit-code", "contradicted-by-git-diff", "stale-number-cited"]
        caps = set(runtime.capabilities()) if hasattr(runtime, "capabilities") else {"exit"}
        findings: list[Finding] = []
        unchecked: list[str] = []

        # ---- a fabricated exit code
        if "exit" in caps:
            claimed = runtime.claimed_exit(text)
            real = runtime.real_exit()
            if claimed is not None and real is not None and claimed != real:
                findings.append(Finding(
                    message="claims exit=%s but the real captured exit was %s "
                            "(fabricated-exit-code)" % (claimed, real)))
        else:
            unchecked.append("fabricated-exit-code")

        # ---- a claim the real diff does not support
        if "diff" in caps:
            diff = runtime.real_diff()
            if diff is None:
                unchecked.append("contradicted-by-git-diff")
            else:
                removed = "\n".join(l[1:].lower() for l in diff.splitlines()
                                    if l.startswith("-") and not l.startswith("---"))
                for ln, line in enumerate(text.splitlines(), 1):
                    if not _REMOVED.search(line):
                        continue
                    subject = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", line.lower())
                               if w not in _STOPWORDS and not _REMOVED.fullmatch(w)]
                    if not subject:
                        continue
                    if any(w in removed for w in subject):
                        continue                  # the diff really does take one of them out
                    findings.append(Finding(
                        message=("claims something was removed (%s) and the real diff takes none "
                                 "of it out (contradicted-by-git-diff)"
                                 % ", ".join(subject[:3])),
                        line=ln, excerpt=line.strip()[:80]))
        else:
            unchecked.append("contradicted-by-git-diff")

        # ---- a number that was true once
        if "measure" in caps:
            for label, real_value in (runtime.measurements() or {}).items():
                for m in re.finditer(r"\b(\d[\d,]*)\b", text):
                    n = int(m.group(1).replace(",", ""))
                    window = text[max(0, m.start() - 60):m.end() + 60].lower()
                    if label.lower() not in window or n == real_value:
                        continue
                    findings.append(Finding(
                        message=("cites %d for %r; re-measuring it now gives %s "
                                 "(stale-number-cited)" % (n, label, real_value)),
                        line=text.count("\n", 0, m.start()) + 1,
                        excerpt=" ".join(window.split())[:80]))
        else:
            unchecked.append("stale-number-cited")

        return findings, unchecked

    def runtime_findings(self, text: str, runtime) -> list[Finding]:
        """The findings half of `runtime_report`, kept for callers that only want findings.

        ⚠ A CALLER USING THIS CANNOT TELL CLEAN FROM COULD-NOT-CHECK. Prefer `runtime_report`.
        """
        return self.runtime_report(text, runtime)[0]


class Runtime:
    """Real observations from a turn, carried to `GroundTruth.runtime_report`.

    THE WHOLE CONTRACT IS THAT THE CALLER MEASURED THESE. A Stop hook already holds the turn's
    real exit codes; a real `git diff` is one read-only command away; a re-measurement is whatever
    the caller can count again now. This class carries what was measured and declares what it
    could not see -- it measures nothing itself and, deliberately, runs nothing.

    ⛔ IT NEVER EXECUTES A COMMAND FOUND IN THE REPLY. A reply is untrusted text. Running what it
    claims to have run would hand an arbitrary command line to a shell in order to check whether
    that command line was honest, which is not a trade anybody should take.

    `capabilities()` is a DECLARATION, not a sniff: whatever is not declared is reported as
    UNCHECKED by the gate rather than silently passing. Pass only what you actually measured.

        Runtime(real_exit=1)                       -> only the exit class is checked
        Runtime(diff=real_diff_text)               -> only the diff class is checked
        Runtime(measurements={"open items": 598})  -> only the number class is checked
    """

    def __init__(self, real_exit=None, diff=None, measurements=None):
        self._exit = real_exit
        self._diff = diff
        self._measurements = measurements
        self._caps = set()
        if real_exit is not None:
            self._caps.add("exit")
        if diff is not None:
            self._caps.add("diff")
        if measurements is not None:
            self._caps.add("measure")

    def capabilities(self) -> set:
        return set(self._caps)

    @staticmethod
    def claimed_exit(text: str):
        """The exit code the TEXT claims, or None. Parsing the claim is not a measurement."""
        m = _CLAIMED_EXIT.search(text)
        return int(m.group(1)) if m else None

    def real_exit(self):
        return self._exit

    def real_diff(self):
        return self._diff

    def measurements(self) -> dict:
        return dict(self._measurements or {})
