"""No module may answer "was this corruption applied" privately.

THE DEFECT THIS PINS WAS REAL, and it was found by auditing for the class rather
than by tripping over it. "Was this corruption actually put to the suite" was
answered in three places, and two of them left `BROKE-THE-RUN` out -- so a
report's denominator could disagree with `mutations_applied` in the same run and
nothing anywhere would say so.

Fixing the three instances is a patch. THIS is the fix: a new module that starts
answering the question privately fails the suite on the commit that adds it,
instead of being found by the next person who audits for it.

The check reads the SOURCE with `ast`, not a grep, so a verdict word inside a
docstring, a comment or a test fixture is not mistaken for a decision.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import deadcanary
from deadcanary.hunt import APPLIED, BROKE, KILLED, NOOP, SURVIVED, UNDONE

PACKAGE = Path(deadcanary.__file__).parent

#: The vocabulary. A module comparing against these is deciding the question.
VERDICTS = {KILLED, SURVIVED, BROKE, NOOP, UNDONE}

#: Where the answer is allowed to live: the one definition, and nowhere else.
OWNER = "hunt.py"

#: A module may still BUILD a report fixture containing verdict strings; that is
#: data, not a decision. Only a COMPARISON is a decision, which is why this walks
#: Compare nodes rather than every string literal.


def _private_decisions(path: Path) -> list[str]:
    """Comparisons against verdict words, outside the module that owns them."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken file fails elsewhere, loudly
        return []

    found: list[str] = []

    class Walker(ast.NodeVisitor):
        def visit_Compare(self, node: ast.Compare) -> None:
            for side in [node.left, *node.comparators]:
                for lit in ast.walk(side):
                    if isinstance(lit, ast.Constant) and lit.value in VERDICTS:
                        found.append("line %d: compares against %r"
                                     % (node.lineno, lit.value))
            self.generic_visit(node)

    Walker().visit(tree)
    return found


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.glob("*.py") if p.name != "__init__.py")


def test_the_population_is_real():
    """A sweep over an empty population is not a clean result."""
    mods = _modules()
    assert len(mods) >= 6, mods
    assert any(p.name == OWNER for p in mods)


def test_only_one_module_decides_what_applied_means():
    offenders = {}
    for path in _modules():
        if path.name == OWNER:
            continue
        hits = _private_decisions(path)
        if hits:
            offenders[path.name] = hits
    assert not offenders, (
        "these modules decide the verdict question themselves instead of importing "
        "hunt.APPLIED / hunt.INCONCLUSIVE, which is how two of them silently left "
        "BROKE-THE-RUN out of their denominator: %s" % offenders)


def test_the_owner_really_does_define_it():
    """Guard against this check passing because the definition vanished.

    Note what it does NOT assert: that `hunt.py` compares against verdict
    LITERALS. It does not, and that is correct -- it compares against its own
    named constants. Comparing against a raw string is the private-definition
    smell, which is exactly why `matrix.py` and `targeted.py` were the ones that
    drifted. Discovered by this guard failing on its first run, which is the
    entire reason a guard case exists.
    """
    assert set(APPLIED) == {KILLED, SURVIVED, BROKE}
    source = (PACKAGE / OWNER).read_text(encoding="utf-8")
    assert "APPLIED = (" in source, (
        "hunt.py no longer defines the vocabulary, so this check watches nothing")


def test_comparing_against_the_named_constant_is_the_right_shape(tmp_path):
    """The fix the offenders were meant to adopt must not itself be flagged."""
    p = tmp_path / "good.py"
    p.write_text(
        "from deadcanary.hunt import APPLIED\n"
        "def f(c):\n"
        "    return c['verdict'] in APPLIED\n", encoding="utf-8")
    assert _private_decisions(p) == []


def test_it_would_catch_a_new_private_definition(tmp_path):
    """The other direction. A check never shown to fire is not a check.

    This is the exact shape the real defect had: a new module quietly writing its
    own tuple and leaving BROKE out.
    """
    offender = tmp_path / "newreport.py"
    offender.write_text(
        "def summarise(report):\n"
        "    return [c for c in report['corruptions']\n"
        "            if c['verdict'] in ('KILLED', 'SURVIVED')]\n",
        encoding="utf-8")
    assert _private_decisions(offender), "a new private definition must be caught"


@pytest.mark.parametrize("source", [
    '"""A docstring mentioning KILLED and SURVIVED."""\n',
    "# a comment about NO-OP\nx = 1\n",
    "FIXTURE = {'verdict': 'SURVIVED'}\n",
    "from deadcanary.hunt import APPLIED\nok = v in APPLIED\n",
])
def test_it_stays_quiet_on_things_that_are_not_decisions(tmp_path, source):
    """Prose, fixture data and correct imports are not private definitions.

    An over-firing check here would flag every test file in the package, which is
    how a check like this gets deleted within a week.
    """
    p = tmp_path / "quiet.py"
    p.write_text(source, encoding="utf-8")
    assert _private_decisions(p) == [], source
