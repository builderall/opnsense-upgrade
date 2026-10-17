#!/usr/bin/env python3
"""Regression tests for _pkg_origin_check(): pre_upgrade_check must flag a
FreeBSD-built pkg before a major upgrade, because OPNsense's 10-sanity.sh aborts
the upgrade over it only after the set download (#36).

Fixtures mirror live firmware_info() package entries: pkg 2.6.2_1 from FreeBSD
(26.1.11, 2026-10-16) and pkg 2.8.4_1 from OPNsense (26.7.7, 2026-10-17).
No network or firewall needed. Run with:

    mcp/.venv/bin/python mcp/tests/test_pkg_origin.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.opnsense_mcp.tools import _pkg_origin_check


def info(repository, installed="1"):
    return {"package": [
        {"name": "base", "version": "26.1.11", "installed": "1", "repository": "OPNsense"},
        {"name": "pkg", "version": "2.6.2_1", "installed": installed,
         "repository": repository},
    ]}


def test_freebsd_pkg_blocks_major():
    line, issue = _pkg_origin_check(info("FreeBSD"), major_pending=True)
    assert "FreeBSD" in line and "NOT the OPNsense" in line
    assert issue and "pkg-static install -fy -r OPNsense pkg" in issue


def test_freebsd_pkg_without_major_only_warns():
    line, issue = _pkg_origin_check(info("FreeBSD"), major_pending=False)
    assert "NOT the OPNsense" in line
    assert issue is None


def test_other_origin_warns_without_issue():
    line, issue = _pkg_origin_check(info("SunnyValley"), major_pending=True)
    assert "SunnyValley" in line and issue is None


def test_opnsense_origin_passes():
    line, issue = _pkg_origin_check(info("OPNsense"), major_pending=True)
    assert line.endswith("OPNsense") and issue is None


def test_missing_pkg_is_unknown_not_pass():
    line, issue = _pkg_origin_check(info("FreeBSD", installed="0"), major_pending=True)
    assert "unknown" in line and issue is None
    line, issue = _pkg_origin_check({}, major_pending=True)
    assert "unknown" in line and issue is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"\n{len(tests)} tests passed.")
