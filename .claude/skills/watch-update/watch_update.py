#!/usr/bin/env python3
"""watch_update.py -- follow an in-progress OPNsense firmware update through the reboot.

Designed as a Claude Code Monitor event stream: every stdout line is one event.
Read-only: only reads firmware status via the REST API; never triggers or mutates
anything. Runs from mcp/.venv and imports the MCP package so config loading, API
access, and repo-error detection have a single source of truth (the original bash
version duplicated the _repo_error() signature and .env parsing).

State machine (same as the proven bash original):
  waiting  -- the upgradestatus endpoint retains the previous run's terminal status
              (and reports 'error' with an empty log right after a reboot), so
              terminal statuses at arm time are stale residue. Wait for 'running'
              or an API drop; give up after NO_RUN_AFTER seconds.
  watching -- emit stall warnings (with the Zenarmor/SunnyValley unreachable-repo
              signature check), detect the reboot drop (two consecutive failed
              polls), and exit on back-online / done / error.

Env knobs: POLL_SECONDS (20), STALL_AFTER (300), MAX_SECONDS (1800),
           NO_RUN_AFTER (90). Credentials come from mcp/.env via the MCP package
           loader; OPNSENSE_* environment variables override it.
"""

import os
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
MCP_DIR = os.path.join(ROOT, "mcp")
sys.path.insert(0, MCP_DIR)

import httpx  # noqa: E402  (from the mcp venv)
from src.opnsense_mcp.api import OPNsenseAPI  # noqa: E402
from src.opnsense_mcp.config import Config  # noqa: E402
from src.opnsense_mcp.tools import _repo_error  # noqa: E402

LOGS_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOGS_DIR, f"watch-update-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
)
STATUS_LOG = os.path.join(LOGS_DIR, "install-status.log")

_log_fh = open(LOG_FILE, "a")
# stdout is the Monitor event stream -- duplicate it to the log, but keep stderr
# noise (httpx warnings, tracebacks) out of the stream.
sys.stderr = _log_fh


def emit(msg):
    print(msg, flush=True)
    _log_fh.write(msg + "\n")
    _log_fh.flush()


def status_to_log(status, detail=""):
    line = "%-19s  %-8s  %-12s  %s\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "[UPDATE]",
        "opnsense",
        status + (f"  ({detail})" if detail else ""),
    )
    with open(STATUS_LOG, "a") as f:
        f.write(line)


def get_upgradestatus(api):
    """upgradestatus body, or None when the API is unreachable (reboot window)."""
    try:
        return api.firmware_upgradestatus()
    except Exception:
        return None


def get_status(api):
    try:
        return api.firmware_status()
    except Exception:
        return None


def fw_version(api):
    status = get_status(api)
    if status:
        return status.get("product", {}).get("product_version", "?") or "?"
    return "?"


def main():
    poll = int(os.environ.get("POLL_SECONDS", "20"))
    stall_after = int(os.environ.get("STALL_AFTER", "300"))
    max_seconds = int(os.environ.get("MAX_SECONDS", "1800"))
    no_run_after = int(os.environ.get("NO_RUN_AFTER", "90"))

    try:
        config = Config.from_env()
    except ValueError as e:
        emit(f"ERROR: {e}")
        return 1
    api = OPNsenseAPI(config)
    # The package default (30s) makes reboot-window polls sluggish; match the
    # bash original's curl -m 10.
    api._client.timeout = httpx.Timeout(10)

    start = time.monotonic()
    phase = "waiting"  # waiting: run not seen yet; watching: run confirmed
    down = False
    fails = 0
    warned_stall = False
    last_log_len = 0
    last_log_change = start

    body = get_upgradestatus(api)
    initial = body.get("status", "") if body else ""
    emit(
        f"Watching update: initial status='{initial or 'unreachable'}', "
        f"version={fw_version(api)}"
    )
    if initial == "running":
        phase = "watching"

    while True:
        now = time.monotonic()
        if now - start >= max_seconds:
            emit(
                f"GAVE UP after {max_seconds}s -- run is not terminal; "
                "check the firewall manually"
            )
            status_to_log("WARNING", f"watch-update gave up after {max_seconds}s")
            return 1

        body = get_upgradestatus(api)

        if phase == "waiting":
            # Ignore stale terminal statuses from a previous run; wait for this
            # run to appear.
            if body is None:
                fails += 1
                if fails >= 2:
                    emit("API unreachable -- firewall is likely rebooting now")
                    phase = "watching"
                    down = True
            else:
                fails = 0
                if body.get("status") == "running":
                    emit("Run detected (status=running)")
                    phase = "watching"
                    last_log_change = now
                elif now - start >= no_run_after:
                    emit(
                        f"No update run detected within {no_run_after}s "
                        "-- nothing to watch"
                    )
                    return 0
            time.sleep(5)
            continue

        if body is None:
            fails += 1
            # two consecutive failures = real drop, not a transient blip
            if not down and fails >= 2:
                emit("API unreachable -- firewall is likely rebooting now")
                down = True
        elif down:
            ver = fw_version(api)
            emit(f"Firewall BACK ONLINE after reboot -- version: {ver}")
            status_to_log("SUCCESS", f"back online at {ver}")
            return 0
        else:
            fails = 0
            fw_status = body.get("status", "")
            if fw_status == "done":
                ver = fw_version(api)
                emit(
                    f"Update finished (status=done, no reboot observed) "
                    f"-- version: {ver}"
                )
                status_to_log("SUCCESS", f"done at {ver}")
                return 0
            if fw_status == "error":
                emit("Update FAILED (status=error) -- last log lines:")
                for line in (body.get("log") or "").strip().splitlines()[-5:]:
                    emit(line)
                status_to_log("FAILED", "status=error")
                return 1

            log_len = len(body.get("log") or "")
            if log_len != last_log_len:
                last_log_len = log_len
                last_log_change = now
            elif not warned_stall and now - last_log_change >= stall_after:
                warned_stall = True
                status = get_status(api)
                rerr = _repo_error(status) if status else None
                if rerr:
                    emit(
                        f"WARNING: log stalled {stall_after}s and a pkg repo is "
                        f"unreachable ({rerr}) -- the stalled-update signature. "
                        "Likely needs manual recovery on the firewall."
                    )
                else:
                    emit(
                        f"WARNING: log has not advanced in {stall_after}s "
                        f"(status still '{fw_status}') -- keeping watch"
                    )
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main())
