# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0]

Everything before this released and tested only from the source tree. This release is about
making sure the thing people actually install works, which is a different question.

### Added
- `py.typed`, so downstream type checkers see the annotations. Without it every `mypy` and
  `pyright` user silently gets nothing from a fully annotated package.
- `python -m agentattest` as an alias for `python -m agentattest.demo`.
- A CI job that builds the wheel, installs it into a clean virtual environment, and runs the
  suite from a directory where the source tree is not importable. The existing jobs all tested
  the repo, which cannot catch a packaging bug.
- `CONTRIBUTING.md` and `SECURITY.md`.

### Changed
- Minimum Python lowered from 3.11 to 3.10. Nothing in the codebase required 3.11; the floor was
  arbitrary and excluded users for no reason.

### Fixed
- Nothing. The `py.typed` entry above was a genuinely missing file, not a broken config.

  A first draft of this changelog claimed the file also needed declaring in the build config or it
  would not ship. That was asserted without testing and it is **false**: hatchling includes
  `py.typed` automatically because it lives inside the package directory. Verified by removing the
  declaration, rebuilding, and confirming the wheel still contained it. The declaration was dead
  config and has been removed. CI asserts the file is present in the *installed* package, which is
  the check that actually protects this.

## [0.3.0]

### Added
- `agentattest.demo`, a runnable demonstration. The README transcript is copied from a real run.
- Tests asserting the demo actually refuses and actually allows, so it cannot decay into prose
  describing a refusal it no longer performs.

## [0.2.0]

### Added
- `gates.UnbackedClaims`: flags hard completion claims with no evidence within a configurable
  window. Hedged language passes on purpose.
- `hooks.stop_hook` and `hooks.pre_tool_use_hook`. Malformed input fails open, because a hook
  that wedges every turn gets deleted and then protects nothing.
- `Harness`: checks that assert against live state. `None` reports UNKNOWN and exits 2, never 0.
- `Harness.selftest()`, proving the three verdicts stay distinguishable.

### Fixed
- The evidence pattern matched `PASS` case-insensitively, so the word "pass" inside
  *"All tests pass"* cleared its own claim and every claim containing the word was silently
  approved. Now a separate case-sensitive pattern, with a regression test.
- `selftest_cases()` asserted multi-line fixtures against a `window=0` gate, a guarantee that
  configuration never made. Cases now match the gate's own window.

Both were caught by the mandatory must-fail case before either shipped.

## [0.1.0]

### Added
- `Gate`, `Case`, `Finding`, `SelftestError`. `selftest_cases()` is abstract and must include a
  case the gate is required to flag, so a gate that has never been made to fail on purpose cannot
  return a clean result through `check()`.
