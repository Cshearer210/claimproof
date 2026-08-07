#!/usr/bin/env python3
"""Checks that look at the world. Run it: python live_checks.py

These are real checks against the machine you run them on, not mocks. Run it on
two different computers and you should get two different answers, which is the
point: a test suite gives the same answer everywhere because it only looks at
your code.

Exit codes: 0 all fine, 1 something broke, 2 something could not be determined.
"""
import os
import shutil
import sys
import time

from claimproof import Harness

h = Harness()


@h.check("disk-space", "There is room left on the disk")
def _():
    total, used, free = shutil.disk_usage(os.path.expanduser("~"))
    pct = free / total * 100
    return pct > 10, f"{pct:.0f}% free ({free // 2**30} GB of {total // 2**30} GB)"


@h.check("clock-sane", "The system clock is not obviously wrong")
def _():
    year = time.gmtime().tm_year
    return 2024 <= year <= 2100, f"system year reads {year}"


@h.check("home-writable", "We can actually write to the home directory")
def _():
    p = os.path.join(os.path.expanduser("~"), ".claimproof-probe")
    try:
        with open(p, "w") as f:
            f.write("probe")
        os.remove(p)
        return True, "wrote and removed a probe file"
    except OSError as e:
        return False, f"cannot write to home: {e}"


@h.check("gpu-present", "A GPU is available for local inference")
def _():
    # The interesting one. On a machine with no NVIDIA tooling we cannot tell
    # whether there is no GPU or whether the driver is simply missing. That is
    # UNKNOWN, and UNKNOWN is not a pass. Returning False here would be a lie,
    # and returning True would be worse.
    if shutil.which("nvidia-smi") is None:
        return None, "nvidia-smi not on PATH, so this cannot be determined here"
    return True, "nvidia-smi is present"


@h.check("backup-recent", "An off-machine backup ran in the last two days")
def _():
    # Deliberately points at a path that will not exist for you. A check that
    # cannot find what it is meant to measure must say so rather than pass.
    log = os.path.join(os.path.expanduser("~"), ".claimproof-example-backup.log")
    if not os.path.exists(log):
        return None, "no backup log found at the configured path, cannot tell"
    age_h = (time.time() - os.path.getmtime(log)) / 3600
    return age_h <= 48, f"newest backup {age_h:.0f}h old"


if __name__ == "__main__":
    code = h.run()
    print(f"\nexit {code}")
    print("Two checks above report UNKNOWN on purpose. Neither is a failure, and")
    print("neither is a pass. The exit code is 2 rather than 0 because something")
    print("we wanted to know, we do not know.")
    sys.exit(code)
