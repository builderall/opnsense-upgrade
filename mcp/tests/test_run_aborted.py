#!/usr/bin/env python3
"""Regression tests for _run_aborted(): OPNsense reports an aborted firmware run as
status 'done', so the abort has to be read from the log (#34).

Fixture is the live log tail from the first 26.7 major-upgrade attempt (2026-10-17),
aborted by 10-sanity.sh over a FreeBSD-built pkg. No network or firewall needed.
Run with:

    mcp/.venv/bin/python mcp/tests/test_run_aborted.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.opnsense_mcp.tools import _run_aborted

ABORTED_LOG = """\
Extracting kernel-26.7-amd64.txz... done
Please reboot.
>>> Invoking upgrade script 'sanity.sh'
The Package manager "pkg" is incompatible and needs a reinstall.
>>> Error in upgrade script '10-sanity.sh'
The upgrade was aborted due to an error.
***DONE***"""

SUCCESS_LOG = """\
Extracting kernel-26.7-amd64.txz... done
Please reboot.
>>> Invoking upgrade script 'sanity.sh'
Passed all upgrade tests.
Installing kernel-26.7-amd64.txz... done
***REBOOT***"""


def test_aborted_log_detected():
    line = _run_aborted(ABORTED_LOG)
    assert line == ">>> Error in upgrade script '10-sanity.sh'"


def test_abort_message_alone_detected():
    assert _run_aborted("The upgrade was aborted due to an error.\n***DONE***")


def test_successful_and_empty_logs_not_aborted():
    assert _run_aborted(SUCCESS_LOG) is None
    assert _run_aborted("") is None
    assert _run_aborted(None) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"\n{len(tests)} tests passed.")
