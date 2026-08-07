"""Compatibility shim: this project is now `claimproof`.

The library was briefly published under this name; the PyPI namespace made the
rename necessary, and code written against the old name should not break for
it. Every public name forwards to `claimproof` unchanged. New code should
import `claimproof` directly.
"""
from claimproof import *            # noqa: F401,F403 - deliberate re-export
from claimproof import __version__  # noqa: F401
