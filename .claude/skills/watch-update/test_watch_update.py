#!/usr/bin/env python3
"""Regression tests for watch_update.py's state machine, driven by a fake API.

Covers the paths a live run rarely (or never) exercises: the reboot ride-through
(drop detected -> back online), done-without-reboot, error with log tail, stall
warnings (with and without the unreachable-repo signature -- the repo check uses
the exact _repo_error() the MCP server uses, by import), the give-up deadline,
and stale-terminal-status-at-arm. No network or firewall needed. Run with:

    mcp/.venv/bin/python .claude/skills/watch-update/test_watch_update.py
"""

import importlib.util
import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

os.environ.update(POLL_SECONDS="0", STALL_AFTER="1", MAX_SECONDS="30", NO_RUN_AFTER="1")

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("wu", os.path.join(HERE, "watch_update.py"))
wu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wu)

# Keep test noise out of the real logs: watch_update opened a log file and
# pointed stderr at it during import, and status_to_log appends to the
# install-status record of real operations.
sys.stderr = sys.__stderr__
wu._log_fh.close()
os.remove(wu.LOG_FILE)
wu._log_fh = io.StringIO()
wu.status_to_log = lambda *a, **k: None

EXC = object()  # sentinel: this poll raises (API unreachable)


class FakeAPI:
    """Scripted firmware_upgradestatus responses; firmware_status is static.
    The last script entry repeats forever."""

    def __init__(self, upgradestatus_script, status_body):
        self._client = SimpleNamespace(timeout=None)
        self.script = list(upgradestatus_script)
        self.status_body = status_body

    def firmware_upgradestatus(self):
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if item is EXC:
            raise ConnectionError("down")
        return item

    def firmware_status(self):
        return self.status_body


def run_main(fake):
    wu.Config.from_env = staticmethod(lambda: None)
    wu.OPNsenseAPI = lambda cfg: fake
    out = io.StringIO()
    with redirect_stdout(out):
        rc = wu.main()
    return rc, out.getvalue()


failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


VER = {"product": {"product_version": "26.1.12"}}
running = {"status": "running", "log": "x" * 10}

# 1. Full reboot ride-through: running -> two failed polls -> back online
fake = FakeAPI([running, {"status": "running", "log": "x" * 20}, EXC, EXC,
                {"status": "done", "log": ""}], VER)
rc, out = run_main(fake)
check("reboot: drop detected", "likely rebooting now" in out)
check("reboot: back online with version",
      "BACK ONLINE after reboot -- version: 26.1.12" in out)
check("reboot: exit 0", rc == 0)

# 2. Done without reboot
fake = FakeAPI([running, {"status": "done", "log": "x"}], VER)
rc, out = run_main(fake)
check("done: finished message", "status=done, no reboot observed" in out)
check("done: exit 0", rc == 0)

# 3. Error terminal with log tail
fake = FakeAPI([running, {"status": "error", "log": "l1\nl2\nl3"}], VER)
rc, out = run_main(fake)
check("error: FAILED message + tail", "Update FAILED" in out and "l3" in out)
check("error: exit 1", rc == 1)

# 4. Stall warning uses the shared _repo_error (identical function to the MCP server).
# Log length never changes -> stall at STALL_AFTER=1s; MAX_SECONDS=3 ends the run.
os.environ["MAX_SECONDS"] = "3"
repo_status = {"status_msg": "Could not find the repository on the selected mirror",
               "product": {"product_version": "26.1.11"}}
fake = FakeAPI([running], repo_status)  # repeats forever
rc, out = run_main(fake)
check("stall: repo-unreachable warning", "stalled-update signature" in out)
check("stall: gave up at deadline, exit 1", "GAVE UP" in out and rc == 1)

# 5. Benign stall (no repo error) -> plain keeping-watch warning
fake = FakeAPI([running], VER)
rc, out = run_main(fake)
check("stall: benign warning without repo signature",
      "keeping watch" in out and "stalled-update signature" not in out)

# 6. Stale terminal status at arm time -> nothing to watch
os.environ["MAX_SECONDS"] = "30"
fake = FakeAPI([{"status": "error", "log": ""}], VER)
rc, out = run_main(fake)
check("no-run: stale error ignored", "nothing to watch" in out and rc == 0)

print("\n" + ("FAILURES: " + ", ".join(failures)
              if failures else "ALL STATE-MACHINE TESTS PASSED"))
sys.exit(1 if failures else 0)
