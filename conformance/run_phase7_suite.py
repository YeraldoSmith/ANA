"""Run ANA v0.1 Core's independent Java/Python conformance suite."""

from __future__ import annotations

import subprocess
import sys


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_phase7", "-v"]))
