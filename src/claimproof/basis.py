"""A claim is only as true as the evidence it was measured against.

`Gate` asks whether a claim has evidence *right now*. This asks the harder
question nobody asks: **the evidence you cited has since changed, so is the claim
still true?**

The shape of the failure, stated once:

    A completion claim is validated against what could be seen at that moment.
    When the evidence moves, or the ability to see improves, the older claim
    quietly becomes false, and nothing reopens it.

Two ways that happens, and they are not the same thing:

* **The evidence moved.** You closed "auth refactor done" citing `src/auth.py`
  and `tests/test_auth.py`. Both have been rewritten since. Nobody re-checked.
* **The scope widened.** You closed "no open item is older than March" after
  looking at two sources. A third source was wired in later, and it carries
  older items. The measurement was honest; it is now wrong.

The response to either is the same and it is deliberately not "false". It is
**UNVERIFIED**: re-measure it. Re-measuring is cheap. A false "done" nobody
revisits is not.

Evidence and scope are treated differently on purpose:

* Evidence **vanishing** reopens a claim. It was the proof, and the proof cannot
  be re-read.
* A scope entry vanishing does **not** reopen anything. Somewhere you no longer
  look cannot contain evidence the claim missed, and a checker that cries wolf
  gets switched off, which is how the one real alarm gets ignored.

Fingerprints are content hashes, never timestamps. A file rewritten by a checkout
with identical bytes is not changed evidence, and a checker that says it is will
be ignored within a week.

    from claimproof.basis import ClaimBasis

    basis = ClaimBasis("claims.json")
    basis.record("auth refactor done", evidence=["src/auth.py", "tests/test_auth.py"])
    ...
    for stale in basis.reopened():
        print(stale.claim, "->", stale.why())

    raise SystemExit(basis.run())   # 0 all hold, 1 something reopened,
                                    # 2 could not tell (including: nothing recorded)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = [
    "HOLDS", "REOPENED", "UNKNOWN", "RETIRED", "ABSENT",
    "BasisError", "Evidence", "Claim", "Status", "ClaimBasis",
]

#: Every piece of evidence is exactly as it was, and nothing new is in scope.
HOLDS = "HOLDS"
#: Something moved. The claim is UNVERIFIED until re-measured. Not false.
REOPENED = "REOPENED"
#: Some evidence could not be judged. Never counts as HOLDS. See `Harness`.
UNKNOWN = "UNKNOWN"
#: Admitted as open work again. Kept as the audit trail, but stops alarming.
RETIRED = "RETIRED"

#: The fingerprint stored for evidence that is not there. Deliberately not "",
#: because empty-string-means-missing is how a missing file becomes a silent pass.
ABSENT = "<absent>"

_SLUG = re.compile(r"[^a-z0-9]+")


def fingerprint(data: bytes) -> str:
    """Content fingerprint. Truncated on purpose: this store is read by humans.

    16 hex chars is 64 bits. Two different files colliding by accident is not a
    risk worth 48 more characters of noise per line in a file people have to read.
    """
    return hashlib.sha256(data).hexdigest()[:16]


def fingerprint_path(path: Path) -> str:
    """Fingerprint a file, or ABSENT if it is not there.

    A directory fingerprints as its sorted list of entry names, so "the fixtures
    folder gained a file" is a change even when no existing file was touched.
    """
    try:
        if path.is_dir():
            names = sorted(p.name for p in path.iterdir())
            return fingerprint("\n".join(names).encode("utf-8"))
        return fingerprint(path.read_bytes())
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except OSError as exc:  # unreadable is not the same as absent
        raise BasisError(f"cannot read evidence {path}: {exc}") from exc


def slug(text: str, limit: int = 60) -> str:
    out = _SLUG.sub("-", text.strip().lower()).strip("-")
    return (out[:limit].rstrip("-") or "claim")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BasisError(RuntimeError):
    """Raised when a claim cannot honestly be recorded or judged."""


@dataclass(frozen=True)
class Evidence:
    """One thing a claim rests on, and its fingerprint when the claim was made.

    `kind="file"` fingerprints itself from disk on every recheck. `kind="value"`
    is anything else you cited -- a test summary line, a command's exit code, a
    row count -- and you must hand the current value back at recheck time. If you
    do not, that evidence reports UNKNOWN rather than passing.
    """

    ref: str
    digest: str
    kind: str = "file"

    @classmethod
    def value(cls, ref: str, text: str) -> "Evidence":
        """Evidence that is not a file. `text` is fingerprinted, not stored.

        The raw text is deliberately not kept: this store gets committed, and a
        claim's evidence can easily be a log line with something in it.
        """
        return cls(ref=ref, digest=fingerprint(str(text).encode("utf-8")), kind="value")

    def as_dict(self) -> dict:
        return {"ref": self.ref, "digest": self.digest, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        return cls(ref=str(d["ref"]), digest=str(d["digest"]), kind=str(d.get("kind", "file")))


@dataclass(frozen=True)
class Claim:
    """A recorded completion claim and the basis it was measured against."""

    claim_id: str
    claim: str
    recorded: str
    evidence: tuple[Evidence, ...] = ()
    scope: tuple[str, ...] = ()
    retired_at: str = ""
    now_lives: str = ""
    superseded: tuple[dict, ...] = ()

    @property
    def is_retired(self) -> bool:
        return bool(self.retired_at)

    def as_dict(self) -> dict:
        d: dict = {
            "claim": self.claim,
            "recorded": self.recorded,
            "evidence": [e.as_dict() for e in self.evidence],
            "scope": list(self.scope),
        }
        if self.retired_at:
            d["retired_at"] = self.retired_at
            d["now_lives"] = self.now_lives
        if self.superseded:
            d["superseded"] = list(self.superseded)
        return d

    @classmethod
    def from_dict(cls, claim_id: str, d: dict) -> "Claim":
        return cls(
            claim_id=claim_id,
            claim=str(d.get("claim", "")),
            recorded=str(d.get("recorded", "")),
            evidence=tuple(Evidence.from_dict(e) for e in d.get("evidence", [])),
            scope=tuple(str(s) for s in d.get("scope", [])),
            retired_at=str(d.get("retired_at", "")),
            now_lives=str(d.get("now_lives", "")),
            superseded=tuple(d.get("superseded", [])),
        )


@dataclass(frozen=True)
class Status:
    """What a recheck concluded about one claim, and why, in plain words."""

    claim_id: str
    claim: str
    verdict: str
    recorded: str
    changed: tuple[str, ...] = ()
    vanished: tuple[str, ...] = ()
    appeared: tuple[str, ...] = ()
    narrowed: tuple[str, ...] = ()
    unjudged: tuple[str, ...] = ()
    checked: int = 0
    note: str = ""

    @property
    def is_reopened(self) -> bool:
        return self.verdict == REOPENED

    def why(self) -> str:
        """One sentence a reader who was not there can act on."""
        if self.verdict == RETIRED:
            return (f'closed {self.recorded}, admitted as open work again '
                    f'{self.note or "later"}')
        if self.verdict == REOPENED:
            parts = []
            if self.changed:
                parts.append(f"{len(self.changed)} of {self.checked} piece(s) of "
                             f"evidence changed since ({', '.join(self.changed)})")
            if self.vanished:
                parts.append(f"the evidence {', '.join(self.vanished)} no longer "
                             f"exists, so the proof cannot be re-read")
            if self.appeared:
                parts.append(f"{len(self.appeared)} source(s) it never looked at now "
                             f"exist ({', '.join(self.appeared)})")
            return (f'closed {self.recorded} on "{self.claim}", but '
                    + "; and ".join(parts)
                    + ", so it is UNVERIFIED until re-measured")
        if self.verdict == UNKNOWN:
            return (f"{len(self.unjudged)} piece(s) of evidence could not be judged "
                    f"({', '.join(self.unjudged)}). That is not the same as unchanged")
        tail = ""
        if self.narrowed:
            tail = (f"; {', '.join(self.narrowed)} is no longer in scope, which cannot "
                    f"add evidence the claim missed")
        return f"same {self.checked} piece(s) of evidence as when it was closed{tail}"

    def line(self) -> str:
        return f"{self.verdict:<9} {self.claim_id}\n          {self.why()}"


class ClaimBasis:
    """Record what a completion claim was measured against, and notice when it moves.

        basis = ClaimBasis("claims.json")
        basis.record("auth refactor done",
                     evidence=["src/auth.py", "tests/test_auth.py"])
        ...
        raise SystemExit(basis.run())

    `store` may be omitted, in which case nothing is written to disk and the
    claims live for the life of the object. That is for tests and one-shot
    scripts; a claim that does not outlive the session cannot expire.

    `scope` is a callable returning the sources this basis measures against --
    the *places you look*, as opposed to the evidence you cite. Supply it and
    every claim recorded before a new source appeared reopens automatically, with
    nobody having to remember that a new source changes old answers. Discover it;
    do not hand-write it. A hand-written list has to be edited by the same person
    who would have had to remember.
    """

    def __init__(
        self,
        store: str | os.PathLike[str] | None = None,
        root: str | os.PathLike[str] | None = None,
        scope: Callable[[], Iterable[str]] | None = None,
    ) -> None:
        self.store = Path(store) if store is not None else None
        self.root = Path(root) if root is not None else Path.cwd()
        self._scope_fn = scope
        self._memory: dict[str, dict] = {}

    # ------------------------------------------------------------- storage
    def _load(self) -> dict[str, dict]:
        if self.store is None:
            return dict(self._memory)
        if not self.store.exists():
            return {}
        try:
            raw = json.loads(self.store.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Never silently start from empty. An unreadable store looks exactly
            # like an empty one, and an empty one says every claim is fine.
            raise BasisError(
                f"{self.store} exists but could not be read ({exc}). Refusing to "
                f"continue from an empty store, which would report every claim as "
                f"holding."
            ) from exc
        return dict(raw.get("claims", {}))

    def _save(self, claims: dict[str, dict]) -> None:
        if self.store is None:
            self._memory = dict(claims)
            return
        self.store.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "claims": claims},
                             indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(self.store.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.store)  # atomic: a half-written store is unreadable
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def claims(self) -> list[Claim]:
        return [Claim.from_dict(k, v) for k, v in sorted(self._load().items())]

    def __len__(self) -> int:
        return len(self._load())

    # --------------------------------------------------------------- scope
    def current_scope(self) -> tuple[str, ...]:
        """The sources in scope right now, discovered rather than typed."""
        if self._scope_fn is None:
            return ()
        found = tuple(sorted({str(s) for s in self._scope_fn()}))
        if not found:
            raise BasisError(
                "the scope function returned nothing. Refusing to treat zero "
                "sources as a valid scope: every claim would then be trivially "
                "still-valid forever, which is the exact failure this exists for."
            )
        return found

    # -------------------------------------------------------------- record
    def record(
        self,
        claim: str,
        evidence: Sequence[str | Evidence],
        claim_id: str | None = None,
        when: str | None = None,
    ) -> Claim:
        """Attach a basis to a completion claim.

        `evidence` items are file paths (resolved against `root`) or `Evidence`
        instances. **A file that does not exist raises.** Citing proof that is not
        there is the failure one layer below this one, and recording it would put
        a claim in the store that can never be re-verified.

        Re-recording an id keeps the previous version under `superseded`. A claim
        that reopened and was re-measured is the mechanism working; quietly
        overwriting the trail would look identical to never having been wrong.
        """
        if not claim or not claim.strip():
            raise BasisError("a claim needs text. An unnamed claim cannot be re-measured.")

        collected: list[Evidence] = []
        for item in evidence:
            if isinstance(item, Evidence):
                collected.append(item)
                continue
            ref = str(item)
            digest = fingerprint_path(self._resolve(ref))
            if digest == ABSENT:
                raise BasisError(
                    f"cannot record {claim!r} against {ref!r}: it does not exist. "
                    f"Evidence that is not there cannot support a claim, and "
                    f"storing it would create a claim nothing can ever re-verify."
                )
            collected.append(Evidence(ref=ref, digest=digest, kind="file"))

        if not collected:
            raise BasisError(
                f"cannot record {claim!r} with no evidence. A claim with an empty "
                f"basis holds forever, which is worse than not recording it."
            )

        cid = claim_id or slug(claim)
        claims = self._load()
        previous = claims.get(cid)

        record = Claim(
            claim_id=cid,
            claim=claim,
            recorded=when or _now(),
            evidence=tuple(collected),
            scope=self.current_scope(),
        )
        if previous:
            history = list(previous.get("superseded", []))
            history.append({k: previous[k] for k in ("claim", "recorded", "evidence", "scope")
                            if k in previous})
            record = replace(record, superseded=tuple(history))

        claims[cid] = record.as_dict()
        self._save(claims)
        return record

    def retire(self, claim_id: str, now_lives: str, when: str | None = None) -> Claim:
        """Admit a claim is open work again, and say where that work now lives.

        It stops alarming and is still listed. A check that fires forever teaches
        everyone to ignore it, and then it is useless on the day it is right.
        `now_lives` is required: demoting a claim without saying where its work
        went is how a reopened item disappears instead of getting done.
        """
        if not now_lives or not now_lives.strip():
            raise BasisError(
                f"retiring {claim_id!r} needs somewhere for the work to go. Without "
                f"it the claim stops alarming and the work is simply lost."
            )
        claims = self._load()
        if claim_id not in claims:
            raise BasisError(f"no recorded claim {claim_id!r}")
        claims[claim_id]["retired_at"] = when or _now()
        claims[claim_id]["now_lives"] = now_lives
        self._save(claims)
        return Claim.from_dict(claim_id, claims[claim_id])

    # ------------------------------------------------------------- recheck
    def _resolve(self, ref: str) -> Path:
        p = Path(ref)
        return p if p.is_absolute() else self.root / p

    def recheck(self, values: dict[str, str] | None = None) -> list[Status]:
        """Judge every recorded claim. Returns ALL of them, not just the stale ones.

        The whole list is returned on purpose: "2 reopened" means nothing without
        "out of how many". `values` supplies the current text of any non-file
        evidence, keyed by its `ref`. Non-file evidence with no current value is
        reported UNKNOWN, never as holding.
        """
        supplied = {k: fingerprint(str(v).encode("utf-8")) for k, v in (values or {}).items()}
        scope_now = set(self.current_scope())
        out: list[Status] = []

        for claim in self.claims():
            if claim.is_retired:
                out.append(Status(
                    claim_id=claim.claim_id, claim=claim.claim, verdict=RETIRED,
                    recorded=claim.recorded, checked=len(claim.evidence),
                    note=f"{claim.retired_at}: {claim.now_lives}",
                ))
                continue

            changed: list[str] = []
            vanished: list[str] = []
            unjudged: list[str] = []

            for ev in claim.evidence:
                if ev.kind == "file":
                    now = fingerprint_path(self._resolve(ev.ref))
                    if now == ABSENT:
                        vanished.append(ev.ref)
                    elif now != ev.digest:
                        changed.append(ev.ref)
                else:
                    now_value = supplied.get(ev.ref)
                    if now_value is None:
                        unjudged.append(ev.ref)
                    elif now_value != ev.digest:
                        changed.append(ev.ref)

            was = set(claim.scope)
            if was and self._scope_fn is None:
                # The claim was measured against a scope this basis cannot see.
                # Reporting HOLDS here would be a guess dressed as a result.
                unjudged.append("scope")
                appeared: set[str] = set()
                narrowed: set[str] = set()
            else:
                appeared = scope_now - was
                narrowed = was - scope_now

            if changed or vanished or appeared:
                verdict = REOPENED
            elif unjudged:
                verdict = UNKNOWN
            else:
                verdict = HOLDS

            out.append(Status(
                claim_id=claim.claim_id, claim=claim.claim, verdict=verdict,
                recorded=claim.recorded,
                changed=tuple(sorted(changed)), vanished=tuple(sorted(vanished)),
                appeared=tuple(sorted(appeared)), narrowed=tuple(sorted(narrowed)),
                unjudged=tuple(sorted(unjudged)), checked=len(claim.evidence),
            ))
        return out

    def reopened(self, values: dict[str, str] | None = None) -> list[Status]:
        """Only the claims that need re-measuring."""
        return [s for s in self.recheck(values) if s.is_reopened]

    # ----------------------------------------------------------------- run
    def run(self, values: dict[str, str] | None = None, echo: bool = True) -> int:
        """0 everything holds, 1 something reopened, 2 could not tell.

        An empty store exits 2, not 0. Nothing being watched looks identical to
        nothing having expired, and that confusion is the whole point of this file.
        """
        statuses = self.recheck(values)
        if not statuses:
            if echo:
                print("UNKNOWN: no claim has recorded a basis, so nothing is being "
                      "watched. That is not the same as nothing having expired.")
            return 2

        stale = [s for s in statuses if s.verdict == REOPENED]
        unsure = [s for s in statuses if s.verdict == UNKNOWN]

        if echo:
            for s in statuses:
                print(s.line())
            held = len(statuses) - len(stale) - len(unsure)
            print(f"\n{len(statuses)} claim(s) checked: {held} holding, "
                  f"{len(stale)} REOPENED, {len(unsure)} unknown")
            if unsure:
                print("UNKNOWN is not a pass. It means the basis could not be judged.")

        if stale:
            return 1
        if unsure:
            return 2
        return 0

    def as_check(self, values: dict[str, str] | None = None):
        """A `Harness` check: every recorded claim still rests on what it cited.

            h.check("claims-hold", "Every closed claim still rests on unchanged "
                                   "evidence")(basis.as_check())
        """
        def _check() -> tuple[bool | None, str]:
            statuses = self.recheck(values)
            if not statuses:
                return None, "no claim has recorded a basis, so nothing is watched"
            stale = [s for s in statuses if s.verdict == REOPENED]
            unsure = [s for s in statuses if s.verdict == UNKNOWN]
            if stale:
                return False, (f"{len(stale)} of {len(statuses)} claim(s) reopened: "
                               + "; ".join(s.claim_id for s in stale))
            if unsure:
                return None, (f"{len(unsure)} of {len(statuses)} claim(s) could not be "
                              f"judged: " + "; ".join(s.claim_id for s in unsure))
            return True, f"all {len(statuses)} claim(s) still rest on unchanged evidence"
        return _check

    # ------------------------------------------------------------ selftest
    @staticmethod
    def selftest(echo: bool = True) -> bool:
        """Plant real staleness and prove it is caught.

        Everything here happens on a real temporary directory with real files,
        because the bug this is guarding against lives in reading files, and a
        test with a fake filesystem would not have touched it.
        """
        ok = True

        def check(label: str, cond: bool) -> None:
            nonlocal ok
            if echo:
                print(("  ok    " if cond else "  FAIL  ") + label)
            ok = ok and bool(cond)

        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            store = room / "claims.json"
            proof = room / "proof.txt"
            proof.write_text("green\n", encoding="utf-8")

            basis = ClaimBasis(store, root=room)
            basis.record("the suite passes", evidence=["proof.txt"], claim_id="suite")

            check("a claim whose evidence has not moved HOLDS",
                  basis.recheck()[0].verdict == HOLDS)

            # THE CASE THIS EXISTS FOR: the evidence is edited afterwards.
            proof.write_text("red\n", encoding="utf-8")
            after = basis.recheck()[0]
            check("editing the evidence REOPENS the claim -- the answer was true "
                  "when measured and is now unverified", after.verdict == REOPENED)
            check("...and the reason names the file that moved, so a reader who was "
                  "not there can act on it", "proof.txt" in after.why())
            check("...and run() exits 1 rather than 0", basis.run(echo=False) == 1)

            # Same bytes written again is NOT a change. A checker that fires on a
            # touched-but-identical file gets switched off.
            proof.write_text("green\n", encoding="utf-8")
            check("rewriting the identical bytes does NOT reopen -- fingerprints are "
                  "content, not timestamps", basis.recheck()[0].verdict == HOLDS)

            proof.unlink()
            check("evidence that VANISHED reopens: the proof cannot be re-read",
                  basis.recheck()[0].verdict == REOPENED)
            proof.write_text("green\n", encoding="utf-8")

            # Citing proof that is not there must raise, not store.
            try:
                basis.record("built it", evidence=["does-not-exist.txt"])
                raised = False
            except BasisError:
                raised = True
            check("recording a claim against a file that does not exist RAISES -- "
                  "otherwise the store holds a claim nothing can re-verify", raised)

            try:
                basis.record("built it", evidence=[])
                empty_raised = False
            except BasisError:
                empty_raised = True
            check("a claim with NO evidence is refused -- an empty basis holds "
                  "forever", empty_raised)

            # Scope: widening reopens, narrowing does not.
            sources = {"logs", "tests"}
            scoped = ClaimBasis(room / "scoped.json", root=room,
                                scope=lambda: sorted(sources))
            scoped.record("nothing older than March is open", evidence=["proof.txt"],
                          claim_id="ages")
            check("a claim holds while the scope is unchanged",
                  scoped.recheck()[0].verdict == HOLDS)
            sources.add("inbox")
            widened = scoped.recheck()[0]
            check("a NEW source reopens every claim recorded before it existed, with "
                  "nobody having to remember that", widened.verdict == REOPENED)
            check("...and it names the source that was never looked at",
                  "inbox" in widened.why())
            sources.clear()
            sources.update({"tests"})
            narrowed = scoped.recheck()[0]
            check("a source DISAPPEARING does not reopen -- somewhere you no longer "
                  "look cannot hold evidence the claim missed",
                  narrowed.verdict == HOLDS and "logs" in narrowed.why())

            # A scope function that discovers nothing must raise.
            try:
                ClaimBasis(room / "empty.json", root=room, scope=lambda: []).current_scope()
                empty_scope_raised = False
            except BasisError:
                empty_scope_raised = True
            check("a scope that discovers ZERO sources raises -- zero sources would "
                  "mark every claim trivially valid", empty_scope_raised)

            # Non-file evidence: unjudged is UNKNOWN, never a pass.
            vals = ClaimBasis(room / "vals.json", root=room)
            vals.record("64 tests pass", claim_id="tests",
                        evidence=[Evidence.value("suite", "64 passed")])
            check("evidence we were given no current value for is UNKNOWN, not a pass",
                  vals.recheck()[0].verdict == UNKNOWN)
            check("...and UNKNOWN exits 2, distinct from both 0 and 1",
                  vals.run(echo=False) == 2)
            check("the same value still HOLDS",
                  vals.recheck({"suite": "64 passed"})[0].verdict == HOLDS)
            check("a different value REOPENS",
                  vals.recheck({"suite": "63 passed"})[0].verdict == REOPENED)

            # Re-measuring keeps what was believed before.
            again = basis.record("the suite passes", evidence=["proof.txt"],
                                 claim_id="suite")
            check("re-measuring KEEPS the superseded claim -- silently overwriting "
                  "would look the same as never having been wrong",
                  len(again.superseded) == 1)

            # Retiring stops the alarm without deleting the record.
            basis.retire("suite", "tracked in ROADMAP.md")
            retired = basis.recheck()[0]
            check("a claim admitted as open work again stops alarming",
                  retired.verdict == RETIRED)
            check("...but is still listed, with where the work went",
                  "ROADMAP.md" in retired.why())
            try:
                basis.retire("suite", "")
                no_home_raised = False
            except BasisError:
                no_home_raised = True
            check("retiring with nowhere for the work to go is refused",
                  no_home_raised)

            # An empty store is UNKNOWN, never a pass.
            check("an EMPTY store exits 2 -- nothing being watched looks identical "
                  "to nothing having expired",
                  ClaimBasis(room / "nothing.json", root=room).run(echo=False) == 2)

            # An unreadable store must not read as empty.
            broken = room / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            try:
                ClaimBasis(broken, root=room).recheck()
                corrupt_raised = False
            except BasisError:
                corrupt_raised = True
            check("a corrupt store RAISES rather than starting from empty, which "
                  "would report every claim as holding", corrupt_raised)

        if echo:
            print("SELFTEST", "PASS" if ok else "FAIL")
        return ok


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m claimproof.basis",
        description="Record what a completion claim was measured against, "
                    "and notice when that evidence moves.")
    ap.add_argument("--store", default="claims.json", help="where claims live (JSON)")
    ap.add_argument("--root", default=None, help="directory file evidence is relative to")
    ap.add_argument("--record", metavar="CLAIM", help="the claim being closed")
    ap.add_argument("--evidence", nargs="*", default=[], metavar="PATH",
                    help="files that prove it")
    ap.add_argument("--id", dest="claim_id", default=None,
                    help="stable id; defaults to a slug of the claim text")
    ap.add_argument("--retire", metavar="ID", help="admit a claim is open work again")
    ap.add_argument("--now-lives", default="", help="where that work is tracked now")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return 0 if ClaimBasis.selftest() else 1

    basis = ClaimBasis(args.store, root=args.root)

    try:
        if args.retire:
            claim = basis.retire(args.retire, args.now_lives)
            print(f"{claim.claim_id} is no longer a done-claim. "
                  f"Work now tracked at: {claim.now_lives}")
            return 0

        if args.record:
            claim = basis.record(args.record, args.evidence, claim_id=args.claim_id)
            print(f"recorded {claim.claim_id}: measured against "
                  f"{len(claim.evidence)} piece(s) of evidence "
                  f"({', '.join(e.ref for e in claim.evidence)}) on {claim.recorded}")
            return 0

        if args.list:
            for claim in basis.claims():
                refs = ", ".join(e.ref for e in claim.evidence)
                print(f"{claim.claim_id}  {claim.recorded}  [{refs}]  {claim.claim}")
            return 0

        return basis.run()
    except BasisError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
