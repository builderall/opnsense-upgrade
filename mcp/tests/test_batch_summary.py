#!/usr/bin/env python3
"""Regression tests for pending-batch reporting: batch_summary(), the
check_updates availability lines, and reboot attribution in check_needs_reboot.

Motivated by the os-sensei 2.6.1 release (2026-07-12): a plugin-only
SunnyValley batch was reported as "Minor update available: 26.1.11" with a
kernel/base reboot, when in fact the OPNsense version would not change and the
reboot was requested by the Zenarmor engine. No network or firewall needed.
Run with:

    mcp/.venv/bin/python mcp/tests/test_batch_summary.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.opnsense_mcp.api import OPNsenseAPI, batch_summary
from src.opnsense_mcp.tools import _package_lines, _update_lines, _version_state


def make_status(current="26.1.11_6", latest="26.1.11", fw_status="update",
                needs_reboot="1", **package_lists):
    status = {
        "product": {"product_version": current, "product_latest": latest,
                    "CORE_NEXT": "26.7"},
        "status": fw_status,
        "needs_reboot": needs_reboot,
        "upgrade_needs_reboot": "0",
        "status_msg": "",
    }
    status.update(package_lists)
    return status


# Live firmware status data from the 2026-07-12 incident, verbatim.
SENSEI_BATCH = [
    {"name": "os-sensei", "repository": "SunnyValley",
     "current_version": "2.6", "new_version": "2.6.1"},
    {"name": "os-sensei-agent", "repository": "SunnyValley",
     "current_version": "2.6", "new_version": "2.6.1"},
]

CORE_BATCH = [
    {"name": "base", "repository": "OPNsense",
     "current_version": "26.1.11", "new_version": "26.1.12"},
    {"name": "kernel", "repository": "OPNsense",
     "current_version": "26.1.11", "new_version": "26.1.12"},
    {"name": "opnsense", "repository": "OPNsense",
     "current_version": "26.1.11_6", "new_version": "26.1.12"},
]


def fake_api(status):
    api = OPNsenseAPI.__new__(OPNsenseAPI)
    api.firmware_status = lambda: status
    return api


def test_batch_summary_plugin_only():
    b = batch_summary(make_status(upgrade_packages=SENSEI_BATCH))
    assert len(b["packages"]) == 2
    assert not b["has_core"]
    assert b["repos"] == ["SunnyValley"]
    assert b["packages"][0]["action"] == "upgrade"


def test_batch_summary_core():
    b = batch_summary(make_status(latest="26.1.12", upgrade_packages=CORE_BATCH))
    assert b["has_core"]
    assert b["repos"] == ["OPNsense"]


def test_batch_summary_empty_and_actions():
    assert batch_summary(make_status(fw_status="none"))["packages"] == []
    b = batch_summary(make_status(
        new_packages=[{"name": "os-foo", "repository": "OPNsense",
                       "current_version": "", "new_version": "1.0"}],
        remove_packages=[{"name": "py37-old", "repository": "OPNsense",
                          "current_version": "1.2"}],
    ))
    actions = {p["name"]: p["action"] for p in b["packages"]}
    assert actions == {"os-foo": "install", "py37-old": "remove"}
    # remove entries have no new_version; _package_lines must not crash on them
    joined = "\n".join(_package_lines(b))
    assert "py37-old" in joined and "[remove]" in joined


def test_update_lines_plugin_only():
    status = make_status(upgrade_packages=SENSEI_BATCH)
    lines = _update_lines(_version_state(status), batch_summary(status))
    assert lines[0] == "Package updates available: 2 (third-party only, OPNsense stays 26.1.11_6)"
    assert "Minor update available" not in "\n".join(lines)
    assert any("os-sensei" in l and "2.6 -> 2.6.1" in l and "SunnyValley" in l
               for l in lines)


def test_update_lines_core_no_version_bump():
    # Core packages pending but product_latest == current base (e.g. a base/kernel
    # rebuild within the same version): no "third-party only" claim.
    batch = [{"name": "kernel", "repository": "OPNsense",
              "current_version": "26.1.11", "new_version": "26.1.11_1"}]
    status = make_status(upgrade_packages=batch)
    lines = _update_lines(_version_state(status), batch_summary(status))
    assert lines[0] == "Package updates available: 1 (OPNsense version stays 26.1.11_6)"


def test_update_lines_version_bump():
    status = make_status(latest="26.1.12", upgrade_packages=CORE_BATCH)
    lines = _update_lines(_version_state(status), batch_summary(status))
    assert lines[0] == "Minor update available: 26.1.12 (3 packages)"
    assert any("base" in l and "26.1.11 -> 26.1.12" in l for l in lines)


def test_update_lines_up_to_date_and_stale_cache():
    status = make_status(fw_status="none", needs_reboot="0")
    assert _update_lines(_version_state(status), batch_summary(status)) == \
        ["Minor update: up to date"]
    # Stale daemon cache: product_latest ahead, but no package list yet.
    status = make_status(latest="26.1.12", fw_status="none", needs_reboot="0")
    assert _update_lines(_version_state(status), batch_summary(status)) == \
        ["Minor update available: 26.1.12"]


def test_reboot_attribution_plugin_only():
    info = fake_api(make_status(upgrade_packages=SENSEI_BATCH)).check_needs_reboot()
    assert info["pending_update_reboot"]
    assert "os-sensei" in info["explanation"]
    assert "no kernel/base change" in info["explanation"]


def test_reboot_attribution_core():
    status = make_status(latest="26.1.12", upgrade_packages=CORE_BATCH)
    info = fake_api(status).check_needs_reboot()
    assert info["pending_update_reboot"]
    assert "kernel/base/core" in info["explanation"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS {name}")
    print(f"\n{len(tests)} tests passed.")
