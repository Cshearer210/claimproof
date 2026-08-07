"""Forwards to claimproof.claude_code -- the project was renamed.

Kept runnable so a hook installed under the old name (`python -m
agentattest.claude_code` in someone's settings) keeps guarding their turns
instead of silently dying on the day of the rename.
"""
from claimproof.claude_code import *   # noqa: F401,F403
from claimproof.claude_code import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
