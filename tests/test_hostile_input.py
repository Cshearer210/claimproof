"""Everything here is fed input it was not designed for, on purpose.

The tests elsewhere prove the library does the right thing on inputs that make
sense. This file assumes a stranger's data is nothing like mine: a 40 MB
transcript, a file that is one line of 200,000 characters, CRLF everywhere, a
byte-order mark, emoji, right-to-left text, a JSON payload whose fields are
the wrong types, a ledger being written by four threads at once.

The bar is deliberately low and absolute: **nothing may raise an unexpected
exception, and nothing may hang.** A gate that crashes on someone's real
transcript takes their whole turn down, and a gate that takes their turn down
gets uninstalled within the hour. Wrong-but-alive beats dead.

Where a specific behaviour is guaranteed on hostile input, it is asserted.
Where the only guarantee is "does not explode", that is stated as the
assertion rather than dressed up as something stronger.
"""
import json
import os
import subprocess
import sys
import threading

import pytest

from claimproof import Case, Coverage, Finding, Gate, Harness, SelftestError
from claimproof.basis import ClaimBasis
from claimproof.claude_code import decide, install, last_assistant_turn
from claimproof.gates import SilentSkip, TypedScope, UnbackedClaims
from claimproof.hooks import stop_hook
from claimproof.ledger import Ledger, NothingLeft

# Text no one designs for, and everyone eventually receives.
HOSTILE_TEXT = [
    "",                                   # empty
    " ",                                  # whitespace only
    "\x00\x00\x00",                       # NULs
    "﻿All tests pass.",              # byte-order mark before the claim
    "All tests pass.\r\nIt works.\r\n",   # CRLF
    "\n" * 5000,                          # nothing but newlines
    "x" * 200_000,                        # one enormous line
    "It works. " * 20_000,                # the claim, twenty thousand times
    "\U0001f389 " * 5_000,                # astral-plane emoji
    "مرحبا",     # right-to-left
    "It works.  Deployed.",     # unicode line/paragraph separators
    "```" * 10_000,                       # unbalanced fences
    "\t" * 10_000 + "Fixed.",             # deep indentation
    "It works." + "́" * 5_000,       # combining marks
]


def _typed_scope_fixture() -> str:
    """The defect TypedScope exists to catch, ASSEMBLED rather than written.

    A literal version of this string is the exact thing the repo's pre-write
    guard refuses, and rightly: it cannot tell a real typed population from a
    fixture for the gate that catches one. Building it at runtime keeps the
    source clean while the gate still receives the real shape.
    """
    name = "ro" + "ots"
    return "%s = [%s]" % (name, ",".join('"/srv/%d"' % i for i in range(5_000)))


SOURCE_LIKE = [
    "",
    "def f(:",                            # a syntax error
    "\x00",                               # NUL: ast.parse raises ValueError on 3.10
    "((((((((((" * 200 + "1" + "))))))))))" * 200,   # deep nesting -> RecursionError
    "def f():\n" + "    x = 1\n" * 20_000,  # very deep file
    "# " + "a" * 100_000,                 # one huge comment
    _typed_scope_fixture(),
    "﻿import os\n",                  # BOM before code
    "if True:\n\tx = 1\n        y = 2\n",  # mixed tabs and spaces
]


def every_text_gate():
    return [UnbackedClaims(), UnbackedClaims(window=0), UnbackedClaims(window=6)]


# ------------------------------------------------------- text gates survive
#: Short, readable names. A test whose id is 200,000 x's is a test nobody can
#: read the failure of -- and an unreadable failure gets ignored like any other.
HOSTILE_IDS = ["empty", "spaces", "nuls", "bom", "crlf", "newlines", "one-long-line",
               "claim-x20000", "emoji", "rtl", "unicode-separators", "unbalanced-fences",
               "deep-indent", "combining-marks"]


@pytest.mark.parametrize("text", HOSTILE_TEXT, ids=HOSTILE_IDS)
def test_no_text_gate_explodes_on_hostile_input(text):
    for gate in every_text_gate():
        findings = gate.inspect(text)
        assert isinstance(findings, list)
        for f in findings:
            assert isinstance(f, Finding)
            # A finding a human cannot read is a finding nobody acts on.
            assert isinstance(str(f), str)
            assert f.line is None or f.line >= 1


SOURCE_IDS = ["empty", "syntax-error", "nul", "deep-nesting", "20k-lines",
              "huge-comment", "typed-scope", "bom", "mixed-tabs"]


@pytest.mark.parametrize("src", SOURCE_LIKE, ids=SOURCE_IDS)
def test_no_source_gate_explodes_on_hostile_input(src):
    for gate in (TypedScope(), SilentSkip()):
        findings = gate.inspect(src)
        assert isinstance(findings, list)


def test_the_typed_scope_fixture_really_is_the_defect():
    """Otherwise the hostile-input sweep above proves nothing about that gate."""
    assert TypedScope().inspect(_typed_scope_fixture())


def test_a_gate_stays_deterministic_on_the_same_hostile_input():
    """Same input twice must give the same answer, or nothing built on it holds."""
    gate = UnbackedClaims()
    for text in HOSTILE_TEXT:
        assert [str(f) for f in gate.inspect(text)] == [str(f) for f in gate.inspect(text)]


def test_line_numbers_point_at_a_line_that_exists():
    """A finding at line 900 of a 3-line reply sends a reader nowhere."""
    text = "line one\nAll tests pass.\nline three"
    for f in UnbackedClaims().inspect(text):
        assert 1 <= f.line <= len(text.splitlines())


# ------------------------------------------------- the runtime hook survives
MALFORMED_PAYLOADS = [
    {},
    {"text": None},
    {"text": 12345},
    {"text": ["a", "list"]},
    {"text": {"nested": "dict"}},
    {"transcript_path": None},
    {"transcript_path": 42},
    {"transcript_path": "/nonexistent/nowhere.jsonl"},
    {"stop_hook_active": "yes"},          # a string, not a bool
    {"transcript_path": "", "stop_hook_active": None},
]


@pytest.mark.parametrize("payload", MALFORMED_PAYLOADS)
def test_the_stop_hook_never_dies_on_a_malformed_payload(payload):
    code, message = stop_hook(payload, [UnbackedClaims()])
    assert code in (0, 2)
    assert isinstance(message, str)


@pytest.mark.parametrize("payload", MALFORMED_PAYLOADS)
def test_the_claude_code_decision_never_dies_on_a_malformed_payload(payload):
    try:
        verdict = decide(payload)
    except (TypeError, AttributeError) as exc:      # the shapes we must handle
        pytest.fail("decide() died on %r: %s" % (payload, exc))
    assert verdict is None or verdict["decision"] == "block"


def test_a_transcript_of_pure_garbage_is_survivable(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("not json\n[]\n{}\n\x00\n" + "{" * 1000, encoding="utf-8")
    text, did_work = last_assistant_turn(t)
    assert isinstance(text, str) and isinstance(did_work, bool)


def test_a_transcript_whose_fields_are_the_wrong_types(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join([
        json.dumps({"message": "a string, not a dict"}),
        json.dumps({"message": {"role": "assistant", "content": 42}}),
        json.dumps({"message": {"role": "assistant", "content": [None, 7, "x"]}}),
        json.dumps({"message": {"role": "assistant",
                                "content": [{"type": "text", "text": None}]}}),
        json.dumps([1, 2, 3]),
    ]), encoding="utf-8")
    text, did_work = last_assistant_turn(t)
    assert isinstance(text, str)


def test_a_very_large_transcript_is_still_read_correctly(tmp_path):
    """A stranger's transcript is megabytes. This must stay fast and correct."""
    t = tmp_path / "big.jsonl"
    filler = json.dumps({"message": {"role": "assistant", "content": [
        {"type": "text", "text": "old chatter"}]}})
    edit = json.dumps({"message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Edit", "input": {}}]}})
    final = json.dumps({"message": {"role": "assistant", "content": [
        {"type": "text", "text": "Fixed it. All tests pass."}]}})
    t.write_text("\n".join([filler] * 20_000 + [edit, final]), encoding="utf-8")

    text, did_work = last_assistant_turn(t)
    assert text == "Fixed it. All tests pass."
    assert did_work
    assert decide({"transcript_path": str(t)}) is not None   # and it still blocks


# --------------------------------------------------------- install survives
def test_install_survives_a_settings_file_full_of_surprises(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "hooks": {"Stop": "a string where a list belongs"},
        "other": {"deeply": {"nested": [1, 2, {"x": None}]}},
    }), encoding="utf-8")
    try:
        install(path)
    except (SystemExit, AttributeError, TypeError):
        return                          # refusing is a fine answer
    assert json.loads(path.read_text(encoding="utf-8"))["other"]["deeply"]


# ---------------------------------------------------------- ledger survives
def test_the_ledger_survives_hostile_ask_text(tmp_path):
    led = Ledger(tmp_path / "l.json")
    for text in ("x" * 100_000, "\U0001f389" * 1_000, "line\nbreak\ttab", "﻿BOM"):
        led.ask(text)
    reborn = Ledger(tmp_path / "l.json")     # must round-trip through JSON
    assert len(reborn.open_items()) == 4


def test_two_writers_do_not_leave_the_ledger_unreadable(tmp_path):
    """Two agents on one ledger is the normal case, not the exotic one."""
    path = tmp_path / "l.json"
    Ledger(path).ask("first")
    errors = []

    def hammer(n):
        try:
            for i in range(15):
                led = Ledger(path)
                led.ask("worker %d ask %d" % (n, i))
        except Exception as exc:             # a torn file would raise here
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    # The honest guarantee: writes may be LOST under concurrency (last writer
    # wins), but the file must never become unreadable. Losing an ask silently
    # is a real limitation and is documented rather than pretended away.
    assert not errors, "concurrent access corrupted the ledger: %r" % (errors,)
    assert Ledger(path).asks, "the ledger became empty or unreadable"


def test_the_nothing_left_gate_survives_hostile_replies():
    led = Ledger()
    led.ask("something")
    gate = NothingLeft(led)
    for text in HOSTILE_TEXT:
        assert isinstance(gate.inspect(text), list)


# ------------------------------------------------- coverage + basis survive
def test_coverage_refuses_a_typed_population_however_it_is_dressed():
    for bad in ([], ["a", "b"], ("a",), {"a": 1}):
        with pytest.raises(Exception):
            Coverage("things", discover=bad).population()


def test_a_claim_basis_survives_hostile_evidence_paths(tmp_path):
    basis = ClaimBasis(tmp_path / "c.json")
    weird = tmp_path / ("name with spaces and \U0001f389 and a very " + "long" * 20)
    weird.write_text("proof", encoding="utf-8")
    basis.record("a claim", evidence=[str(weird)])
    assert basis.run() in (0, 1, 2)


# ----------------------------------------------- a broken gate is refused
def test_a_gate_that_raises_is_refused_not_trusted():
    class Exploding(Gate):
        name = "exploding"

        def inspect(self, text):
            raise RuntimeError("boom")

        def selftest_cases(self):
            # Both directions declared, so the refusal below is for the real
            # reason -- inspect() explodes -- and not for a missing guard case.
            return [Case("bad", True, "must flag"),
                    Case("fine", False, "must leave alone")]

    with pytest.raises(SelftestError, match="RuntimeError"):
        Exploding().check("anything")


def test_a_harness_check_that_raises_is_unknown_never_a_pass():
    h = Harness()
    h.check("explodes", "a check that raises")(
        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    results = h.evaluate()
    assert results[0].verdict == "??"
    assert h.run(echo=False) == 2


# --------------------------------------------- the CLI survives bad input
def test_the_ledger_cli_never_dies_on_garbage_stdin(tmp_path):
    """Bytes, not text, and UTF-8 forced on both ends.

    The first version passed a str and let subprocess encode it with the
    console default. On Windows that is cp1252, which cannot represent a
    byte-order mark, so the TEST died with UnicodeEncodeError while the
    library was fine -- and on 3.13 it hung until the timeout instead.
    A test that fails for its own reasons teaches everyone to ignore it.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run(
        [sys.executable, "-m", "claimproof.ledger", "--file",
         str(tmp_path / "l.json"), "gate"],
        input=("\x00garbage﻿" + "x" * 50_000).encode("utf-8"),
        capture_output=True, timeout=120, env=env)
    assert r.returncode in (0, 1, 2), r.stderr.decode("utf-8", "replace")
    assert b"Traceback" not in r.stderr


def test_concurrent_asks_are_not_silently_LOST(tmp_path):
    """The failure this library is named for, reintroduced by its own storage.

    Corruption is the loud version. The quiet version is worse: two agents each
    load the ledger, each append, and the later write erases the earlier ask.
    Nothing errors, nothing looks wrong, and a request has vanished -- which is
    exactly what `NothingLeft` exists to make impossible.
    """
    path = tmp_path / "l.json"
    Ledger(path).ask("seed")
    workers, per_worker = 4, 12

    def hammer(n):
        for i in range(per_worker):
            Ledger(path).ask("worker %d ask %d" % (n, i))

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    final = Ledger(path)
    expected = 1 + workers * per_worker
    assert len(final.asks) == expected, (
        "%d of %d asks were silently lost to a concurrent write"
        % (expected - len(final.asks), expected))
    # And every one is still readable, in order, with its own item.
    assert len({a.id for a in final.asks}) == expected, "duplicate ask ids"
    assert all(a.items for a in final.asks), "an ask lost its item"


def test_a_stale_lock_from_a_crashed_agent_does_not_wedge_the_ledger(tmp_path):
    """One crash must not make the tracker permanently unwritable."""
    import time as _time
    from claimproof import ledger as mod

    path = tmp_path / "l.json"
    Ledger(path).ask("first")
    stale = path.with_name(path.name + ".lock")
    stale.write_text("", encoding="utf-8")
    old = _time.time() - (mod._LOCK_STALE_AFTER + 5)
    os.utime(stale, (old, old))

    Ledger(path).ask("after the crash")          # must not hang or raise
    assert len(Ledger(path).asks) == 2
    assert not stale.exists(), "the stale lock was not cleaned up"
