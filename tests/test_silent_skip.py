"""SilentSkip: a check that swallows its own failure and lets the run continue.

Half of this file is false-alarm tests, deliberately. The gate's whole viability
rests on not firing on ordinary defensive code, and the third rule this gate used
to have was deleted for exactly that reason (see the class docstring). Every
"must not flag" case below is a real shape that a wider version of this gate
fired on, taken from a sweep of 466 files of production code.
"""
from pathlib import Path

import pytest

import agentattest
from agentattest.gates import SilentSkip

PACKAGE = Path(agentattest.__file__).resolve().parent


def test_its_own_selftest_cases_all_hold():
    checked = SilentSkip().verify()
    assert len(checked) == 15


# ------------------------------------------------------------- must flag
@pytest.mark.parametrize("source", [
    "def check():\n    try:\n        return verify()\n"
    "    except Exception:\n        return True\n",
    "def check_one():\n    try:\n        run()\n"
    "    except Exception:\n        return 0\n",
    "def findings():\n    try:\n        return scan_it()\n"
    "    except Exception:\n        return []\n",
    "def health():\n    try:\n        return probe()\n"
    "    except Exception:\n        return {}\n",
    "def gate():\n    try:\n        validate_everything()\n"
    "    except Exception:\n        pass\n",
])
def test_a_swallowed_check_is_flagged(source):
    assert SilentSkip().check(source), f"should have flagged: {source!r}"


def test_the_finding_names_the_function_and_the_line():
    source = ("def check_config():\n"
              "    try:\n"
              "        return verify()\n"
              "    except Exception:\n"
              "        return True\n")
    findings = SilentSkip().check(source)

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "check_config()" in findings[0].message
    assert "reported as success" in findings[0].message


# --------------------------------------------------------- must NOT flag
@pytest.mark.parametrize("source", [
    # Re-raising is the correct thing to do.
    "try:\n    run()\nexcept Exception as e:\n    raise RuntimeError(e)\n",
    # Returning a failure, or an UNKNOWN, is correct.
    "def check():\n    try:\n        return verify()\n"
    "    except Exception:\n        return False\n",
    "def check():\n    try:\n        return verify()\n"
    "    except Exception as e:\n        return None, str(e)\n",
    # Incidental, not a check.
    "try:\n    os.unlink(tmp)\nexcept OSError:\n    pass\n",
    "try:\n    import ujson as json\nexcept ImportError:\n    import json\n",
    # A reader returning empty is normal.
    "def read_config():\n    try:\n        return json.load(open(p))\n"
    "    except OSError:\n        return {}\n",
    # os.scandir must not read as a "scan". This was 1 of 6 hits in the first
    # real-corpus sweep, purely because `scandir` starts with `scan`.
    "def measure(path):\n    try:\n        with os.scandir(path) as it:\n"
    "            pass\n    except OSError:\n        pass\n",
    # True as the CONSERVATIVE answer. `_git_busy` returning True on error means
    # "assume busy, back off" -- the opposite of silently passing.
    "def _git_busy():\n    try:\n        return run().returncode == 0\n"
    "    except Exception:\n        return True\n",
    "def _win_alive(pid):\n    try:\n        return probe(pid)\n"
    "    except Exception:\n        return True\n",
    "",
    "x = 1\n",
])
def test_ordinary_defensive_code_is_left_alone(source):
    """A gate that cries wolf gets switched off, which is worse than no gate."""
    assert SilentSkip().check(source) == [], f"false alarm on: {source!r}"


def test_skipping_one_item_of_a_loop_and_saying_so_is_normal():
    """The deleted third rule fired on 40 of 45 hits, nearly all of this shape."""
    source = ("def check_all(files):\n"
              "    for f in files:\n"
              "        try:\n"
              "            check_one(f)\n"
              "        except OSError as e:\n"
              "            print(f'SKIP {f}: {e}')\n"
              "            continue\n")
    assert SilentSkip().check(source) == []


def test_a_handler_that_may_re_raise_is_left_alone():
    """A handler doing real error handling is not a swallowed check.

    The obvious fixture for this -- a handler whose whole body is `raise` --
    tests nothing, because no rule would fire on it anyway. Deleting the
    re-raise guard left the suite green until this case existed. It needs a
    handler that WOULD be flagged but for the raise.
    """
    source = ("def check():\n"
              "    try:\n"
              "        return verify()\n"
              "    except Exception:\n"
              "        if fatal:\n"
              "            raise\n"
              "        return True\n")
    assert SilentSkip().check(source) == []


def test_except_pass_inside_a_loop_is_left_alone():
    """Swallowing one item of a loop is ordinary; swallowing the check is not."""
    in_a_loop = ("def check_all(files):\n"
                 "    for f in files:\n"
                 "        try:\n"
                 "            check_one(f)\n"
                 "        except OSError:\n"
                 "            pass\n")
    assert SilentSkip().check(in_a_loop) == []

    # The same shape outside a loop swallows the whole check, and IS flagged.
    once = ("def check_all(files):\n"
            "    try:\n"
            "        check_one(files)\n"
            "    except OSError:\n"
            "        pass\n")
    assert SilentSkip().check(once)


def test_a_handler_that_records_the_failure_is_not_silent():
    source = ("def check():\n"
              "    fails = []\n"
              "    try:\n"
              "        verify()\n"
              "    except OSError as e:\n"
              "        fails.append(f'could not read it: {e}')\n"
              "    return fails\n")
    assert SilentSkip().check(source) == []


def test_a_written_exemption_is_honoured():
    source = ("def check():\n"
              "    try:\n"
              "        return verify()\n"
              "    except Exception:\n"
              "        return True  # agentattest: deliberate, documented reason\n")
    assert SilentSkip().check(source) == []


# ----------------------------------------------------- unparseable input
def test_text_that_is_not_python_yields_nothing_by_default():
    assert SilentSkip().check("this is not python at all ((") == []


def test_strict_mode_refuses_to_call_unparseable_text_clean():
    """The lenient default IS the pattern this gate hunts, which is why strict exists."""
    findings = SilentSkip(strict=True).check("this is not python at all ((")

    assert len(findings) == 1
    assert "could not judge it" in findings[0].message


def test_strict_mode_still_reads_real_python():
    source = "def check():\n    try:\n        return verify()\n    except Exception:\n        return True\n"
    assert SilentSkip(strict=True).check(source)


# ------------------------------------------------------------ integration
def test_the_gate_is_clean_over_the_librarys_own_source():
    modules = sorted(PACKAGE.glob("*.py"))
    assert len(modules) >= 7, f"only found {len(modules)} modules, expected the whole package"

    gate = SilentSkip()
    offenders = {m.name: gate.inspect(m.read_text(encoding="utf-8")) for m in modules}
    assert not any(offenders.values()), \
        f"the library silently skips: { {k: v for k, v in offenders.items() if v} }"


def test_it_refuses_a_write_through_the_pre_write_hook():
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "gate.py",
                              "content": "def check():\n    try:\n        return verify()\n"
                                         "    except Exception:\n        return True\n"}}
    code, message = pre_tool_use_hook(payload, [gate_invariant(SilentSkip())])

    assert code != 0
    assert "gate.py" in message
    assert "reported as success" in message


def test_suffix_filtering_keeps_it_off_files_it_cannot_read():
    """The content must be genuinely unparseable, or this test proves nothing.

    The first version used `# just prose`, which is a valid Python comment. It
    parsed, produced no findings, and passed whether the suffix filter worked or
    not -- a test that was green with the filter deleted.
    """
    from agentattest.hooks import gate_invariant, pre_tool_use_hook

    prose = "# Notes\n\nThis is prose, not Python: it has ((unbalanced brackets\n"
    assert SilentSkip(strict=True).check(prose), "the fixture must be unparseable"

    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "notes.md", "content": prose}}
    filtered, _ = pre_tool_use_hook(
        payload, [gate_invariant(SilentSkip(strict=True), suffixes=(".py",))])
    assert filtered == 0, "a markdown file is not something this gate can judge"

    unfiltered, _ = pre_tool_use_hook(
        payload, [gate_invariant(SilentSkip(strict=True))])
    assert unfiltered != 0, "without the filter it judges files it cannot read"
