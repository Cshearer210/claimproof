"""TypedScope: the gate that reads source before it lands.

Every fixture in this file that contains the bad pattern carries `# noscope:`,
because the fixture text IS the bad pattern and the gate must not flag its own
test data. That is the same exemption a real user gets, used honestly.
"""
from pathlib import Path

import pytest

import agentattest
from agentattest.gates import TypedScope

# Located from the module actually imported, NOT from the repo layout. A
# repo-relative path resolves to nothing when the suite is run against an
# installed wheel, and the first version of this file silently found 0 modules
# there. Caught by tools/verify_wheel.py, which is what that script is for.
PACKAGE = Path(agentattest.__file__).resolve().parent


def test_its_own_selftest_cases_all_hold():
    checked = TypedScope().verify()
    assert len(checked) == 10


@pytest.mark.parametrize("source", [
    'def roots():\n    return ["/srv/app", "/opt/data"]',  # noscope: must-fail fixture
    'SCAN_ROOTS = ["/home/me/projects"]',  # noscope: must-fail fixture
    'search_paths = ["/var/a", "/var/b", "/var/c"]',  # noscope: must-fail fixture
    'anchors = ["C:\\\\Work"]',  # noscope: must-fail fixture
    'BASE_DIRS = ["/opt/one", "/opt/two"]',  # noscope: must-fail fixture
])
def test_a_typed_population_is_flagged(source):
    assert TypedScope().check(source), f"should have flagged: {source!r}"


@pytest.mark.parametrize("source", [
    'LOGFILE = "/var/log/app.log"',
    'ROOT = "/srv/app"',
    'CONFIG = "/home/me/.config/thing.toml"',
    "roots = discover_roots()",
    "roots = [p for p in Path('/').iterdir()]",
    'SCAN_ROOTS = ["/srv/only-mount"]  # noscope: one known mount, not a population',
    '# roots = ["/srv/a", "/opt/b"]',  # noscope: fixture
    "",
    "import os\nprint(os.getcwd())",
])
def test_innocent_source_is_left_alone(source):
    """A gate that cries wolf gets switched off, which is worse than no gate."""
    assert TypedScope().check(source) == [], f"false alarm on: {source!r}"


def test_a_docstring_quoting_the_pattern_is_not_flagged():
    source = '\n'.join([
        'def scan():',
        '    """Do not do this:',
        '',
        '        roots = ["/srv/a", "/opt/b"]',  # noscope: inside a docstring fixture
        '    """',
        '    return discover()',
    ])
    assert TypedScope().check(source) == []


def test_the_finding_says_which_line_and_why():
    source = 'import os\nroots = ["/srv/a", "/opt/b"]\nprint(roots)'  # noscope: fixture
    findings = TypedScope().check(source)

    assert len(findings) == 1
    assert findings[0].line == 2
    assert "hand-written population" in findings[0].message
    assert "/srv/a" in findings[0].excerpt


def test_the_gate_is_clean_over_the_librarys_own_source():
    """If the library cannot pass its own gate, the gate is wrong or the library is.

    Reads every module in the package and states the count, rather than checking
    one file and calling it 'the source'.
    """
    modules = sorted(PACKAGE.glob("*.py"))
    assert len(modules) >= 7, f"only found {len(modules)} modules, expected the whole package"

    gate = TypedScope()
    offenders = {m.name: gate.inspect(m.read_text(encoding="utf-8")) for m in modules}
    assert not any(offenders.values()), \
        f"the library types its own scope: { {k: v for k, v in offenders.items() if v} }"


def test_it_composes_with_the_pre_write_hook():
    """The point is refusing the write, not finding it later in a diff."""
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "scan.py",
                              "content": 'roots = ["/srv/a", "/opt/b"]'}}  # noscope: fixture
    code, message = pre_tool_use_hook(payload, [gate_invariant(TypedScope())])

    assert code != 0, "the write should have been refused"
    assert "scan.py" in message
    assert "hand-written population" in message


def test_an_innocent_write_is_allowed_through():
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "app.py",
                              "content": 'LOGFILE = "/var/log/app.log"'}}
    code, message = pre_tool_use_hook(payload, [gate_invariant(TypedScope())])

    assert code == 0 and message == ""


def test_a_tool_that_is_not_a_write_is_ignored():
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    payload = {"tool_name": "Bash",
               "tool_input": {"command": 'echo ["/srv/a", "/opt/b"]'}}  # noscope: fixture
    code, _ = pre_tool_use_hook(payload, [gate_invariant(TypedScope())])

    assert code == 0


def test_content_it_cannot_read_fails_open_by_default_and_strict_refuses():
    """The default is a deliberate trade, so both halves of it are pinned here."""
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    payload = {"tool_name": "Write", "tool_input": {"file_path": "x.py"}}

    lenient, _ = pre_tool_use_hook(payload, [gate_invariant(TypedScope())])
    assert lenient == 0, "a hook that blocks everything it cannot parse gets deleted"

    strict, message = pre_tool_use_hook(
        payload, [gate_invariant(TypedScope(), strict=True)])
    assert strict != 0
    assert "could not be checked" in message


def test_a_gate_that_cannot_prove_itself_raises_rather_than_allowing_the_write():
    """Silently allowing every write is the one outcome that must not happen."""
    from agentattest import Case, SelftestError
    from agentattest.core import Gate as BaseGate
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    class NeverFails(BaseGate):
        def inspect(self, text):
            return []

        def selftest_cases(self):
            return [Case(text="anything", expect_flagged=False)]

    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "x.py", "content": "whatever"}}

    with pytest.raises(SelftestError):
        pre_tool_use_hook(payload, [gate_invariant(NeverFails())])
