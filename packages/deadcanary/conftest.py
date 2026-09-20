"""Make `pytest` work in a fresh clone, with no install step.

⛔ WHY THIS FILE EXISTS, measured 2026-09-20. In a clean checkout, `python3 -m pytest` in this
directory produced **14 collection errors**, every one of them `ModuleNotFoundError: No module
named 'deadcanary'` -- because the tests import the package by name and nothing put `src/` on the
path. The package itself is fine and imports correctly; only the test run was broken.

⭐ AND THAT IS THE WORST SHAPE FOR A PUBLIC REPO SPECIFICALLY. The first thing anyone evaluating
it does is clone it and run the tests. They do not see "you skipped an install step" -- they see
fourteen errors and close the tab. A repo that is a portfolio piece cannot have a failure that
arrives before the reader ever reaches the code.

⚠ IT DOES NOT SHADOW AN INSTALLED COPY. `src` is APPENDED, not inserted at the front, so a
properly installed `deadcanary` still wins and the tests go on exercising the real installed
package. This only rescues the case where there is no install at all.
"""
from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")

if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.append(_SRC)
