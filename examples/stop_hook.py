#!/usr/bin/env python3
"""A complete stop hook. Copy this file, point your agent runtime at it, done.

It reads the agent's proposed final message as JSON on stdin and exits 2 to
refuse the turn, printing the reason on stderr so the agent can fix it.

Wire it into Claude Code by adding this to ~/.claude/settings.json:

    {
      "hooks": {
        "Stop": [
          {"hooks": [{"type": "command",
                      "command": "python /full/path/to/stop_hook.py"}]}
        ]
      }
    }

Other runtimes: call `stop_hook(payload, gates)` yourself. It takes a dict and
returns (exit_code, message), so adapting it is a few lines rather than a port.

Try it without an agent:

    echo '{"text": "I fixed it. All tests pass."}' | python stop_hook.py ; echo $?
    echo '{"text": "I fixed it.\\n56 passed in 0.14s"}' | python stop_hook.py ; echo $?
"""
import sys

from agentattest.gates import UnbackedClaims
from agentattest.hooks import run_stop_hook

# The gates this hook enforces. Add your own here; each one is checked and each
# must pass its own selftest before it is trusted, so a broken gate stops the
# pipeline rather than quietly approving everything.
GATES = [
    UnbackedClaims(window=2),
]

if __name__ == "__main__":
    sys.exit(run_stop_hook(GATES))
