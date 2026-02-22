"""OPNsense REST API client."""

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Config


class OPNsenseAPI:
    def __init__(self, config: Config):
        self.config = config
        self._client = httpx.Client(
            base_url=config.url,
            auth=(config.api_key, config.api_secret),
            verify=config.verify_ssl,
            timeout=30,
        )

    def _get(self, path: str) -> dict:
        resp = self._client.get(f"/api/{path}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict | None = None) -> dict:
        resp = self._client.post(f"/api/{path}", json=data or {})
        resp.raise_for_status()
        return resp.json()

    # --- Firmware ---

    def firmware_status(self) -> dict:
        return self._get("core/firmware/status")

    def firmware_info(self) -> dict:
        return self._post("core/firmware/info")

    def firmware_running(self) -> dict:
        return self._get("core/firmware/running")

    def firmware_changelog(self, version: str) -> dict:
        return self._post(f"core/firmware/changelog/{version}")

    def firmware_update(self) -> dict:
        """Trigger a minor update."""
        return self._post("core/firmware/update")

    def firmware_upgrade(self, version: str = "") -> dict:
        """Trigger a major upgrade."""
        payload = {"upgrade": version} if version else {}
        return self._post("core/firmware/upgrade", payload)

    def firmware_reboot(self) -> dict:
        return self._post("core/firmware/reboot")

    def firmware_upgradestatus(self) -> dict:
        return self._get("core/firmware/upgradestatus")

    # --- Diagnostics ---

    def system_activity(self) -> dict:
        return self._post("diagnostics/activity/getActivity")

    # --- Derived helpers ---

    def get_uptime_seconds(self) -> int | None:
        """Parse uptime from system activity headers. Returns seconds or None."""
        try:
            data = self.system_activity()
            headers = data.get("headers", [])
            header_str = headers[0] if headers else ""
            # Format: "up 0+01:08:14" or "up 2 days, 3:45:12"
            m = re.search(r"up\s+(\d+)\+(\d+):(\d+):(\d+)", header_str)
            if m:
                days, hours, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                return days * 86400 + hours * 3600 + mins * 60 + secs
            m = re.search(r"up\s+(\d+):(\d+):(\d+)", header_str)
            if m:
                hours, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return hours * 3600 + mins * 60 + secs
        except Exception:
            pass
        return None

    def parse_last_check_age_seconds(self, last_check_str: str) -> int | None:
        """Return how many seconds ago last_check was. Returns None if unparseable."""
        # Format: "Sat Feb 21 14:14:23 EST 2026"
        try:
            # Strip timezone name (EST, UTC, etc.) — not always parseable by strptime
            cleaned = re.sub(r"\s+[A-Z]{2,4}\s+", " ", last_check_str).strip()
            dt = datetime.strptime(cleaned, "%a %b %d %H:%M:%S %Y")
            now = datetime.now()
            return int((now - dt).total_seconds())
        except Exception:
            return None

    def check_needs_reboot(self) -> dict[str, Any]:
        """
        Determine whether needs_reboot is genuine or stale.
        Returns dict with: needs_reboot (bool), is_stale (bool), uptime_seconds, explanation.
        """
        status = self.firmware_status()
        needs_reboot = status.get("needs_reboot") == "1"
        upgrade_needs_reboot = status.get("upgrade_needs_reboot") == "1"
        last_check_str = status.get("last_check", "")

        if not needs_reboot:
            return {"needs_reboot": False, "is_stale": False, "explanation": "No reboot required."}

        # If no packages are pending and system is up to date, the flag is a leftover artifact
        # from a previously applied update that was already rebooted. The UI ignores it too.
        pending_packages = any([
            status.get("upgrade_packages"),
            status.get("new_packages"),
            status.get("reinstall_packages"),
            status.get("downgrade_packages"),
            status.get("remove_packages"),
        ])
        if not pending_packages and status.get("status") == "none":
            return {
                "needs_reboot": True,
                "upgrade_needs_reboot": upgrade_needs_reboot,
                "is_stale": True,
                "explanation": "needs_reboot is set but no packages are pending and system is up to date. "
                               "Leftover flag from a previously applied update. Safe to ignore.",
            }

        uptime = self.get_uptime_seconds()
        last_check_age = self.parse_last_check_age_seconds(last_check_str)

        # Timeline: ... [boot] ... [last_check] ... [now]
        # uptime = seconds since boot
        # last_check_age = seconds since last firmware check
        # If uptime > last_check_age: boot happened first, check happened after boot => flag is genuine
        # If uptime < last_check_age: check happened first, then boot => flag predates the reboot => stale
        is_stale = False
        explanation = ""
        if uptime is not None and last_check_age is not None:
            if uptime < last_check_age:
                is_stale = True
                explanation = (
                    f"needs_reboot is set but appears stale: system has been up "
                    f"{uptime // 60}m, but last firmware check was {last_check_age // 60}m ago "
                    f"(check predates this boot). Safe to ignore."
                )
            else:
                explanation = (
                    f"needs_reboot is set and appears genuine: system has been up "
                    f"{uptime // 60}m, last firmware check was {last_check_age // 60}m ago "
                    f"(firmware daemon ran after this boot and still reports reboot needed). "
                    f"A reboot is recommended."
                )
        else:
            explanation = "needs_reboot is set. Could not determine if stale (uptime unavailable)."

        return {
            "needs_reboot": True,
            "upgrade_needs_reboot": upgrade_needs_reboot,
            "is_stale": is_stale,
            "uptime_seconds": uptime,
            "last_check": last_check_str,
            "explanation": explanation,
        }

    def close(self):
        self._client.close()
