---
name: watch-update
description: >
  Follow an in-progress OPNsense firmware update or upgrade through the mid-update reboot
  and verify the final version. Use immediately after triggering run_update/run_upgrade via
  the opnsense MCP server, or when upgrade_status shows a run already in progress.
---

# Watch an OPNsense update through to completion

Follows a running firmware update end to end: normal progress, the mid-update reboot
(kernel/base batches reboot the firewall automatically), the firewall coming back online,
and the final version. Also detects the stalled-update signature (log stops advancing
while a pkg repo is unreachable -- the Zenarmor/SunnyValley incident).

## Steps

1. **Confirm a run is in progress.** Call the `upgrade_status` MCP tool. If the status is
   not `running` and the user has not just triggered an update, report that there is
   nothing to watch and stop. Do not trigger an update yourself -- `run_update` and
   `run_upgrade` always require explicit user confirmation.

2. **Arm the Monitor.** Use the Monitor tool with:
   - command: `bash <project-root>/.claude/skills/watch-update/watch-update.sh`
   - timeout_ms: `1500000` (25 min) for a minor update; `3600000` for a major upgrade
     (also pass `MAX_SECONDS=3300` in the command environment so the script's own
     give-up deadline stays inside the Monitor timeout)
   - **Use the major-upgrade values (`3600000` + `MAX_SECONDS=3300`) for ANY batch
     containing `os-sensei`, even a minor update.** Zenarmor's post-install deadlock (see
     Recovery below) has burned 5-25 min on its own before the reboot even starts, so 25
     min is not enough. Check the package list from `check_updates` / `run_update` before
     choosing.
   - persistent: `false`
   - description: `OPNsense update: reboot drop, back-online version, done/error`

   Do not poll `upgrade_status` in a loop while the monitor is armed -- events arrive
   as notifications. One immediate `upgrade_status` call right after triggering is fine
   (it shows the package list and exercises the repo-stall warning path).

3. **Interpret events.**

   | Event | Meaning / action |
   |---|---|
   | `API unreachable -- firewall is likely rebooting` | Expected for kernel/base updates. Wait. |
   | `Firewall BACK ONLINE after reboot -- version: X` | Terminal. Go to step 4. |
   | `Update finished (status=done, ...)` | Terminal, no reboot happened. Go to step 4. |
   | `Update FAILED (status=error)` + log lines | Terminal. Show the log to the user. |
   | `WARNING: log stalled ... repo is unreachable` | Repo unreachable. See Recovery A. |
   | `WARNING: log has not advanced in Ns` (no repo) | Post-install deadlock. See Recovery B. |
   | `No update run detected within Ns` | Nothing started. Was the trigger successful? |
   | `GAVE UP after Ns` | Not terminal. Check `upgrade_status` and the firewall manually. |

   The script ignores a terminal status seen at arm time: `upgradestatus` retains the
   previous run's state (and reports `error` with an empty log right after a reboot),
   so it waits for `running` or an API drop before honoring `done`/`error`.

4. **Verify.** Call `get_version` to confirm the new version. Then call `check_updates`
   for the full picture. Caveat: for a few minutes after boot, `check_updates` can time
   out because the diagnostics `getActivity` endpoint is slow while services settle --
   `get_version` working while `check_updates` times out is normal. Retry after a minute
   (a background `until curl ...` probe on the getActivity endpoint works well).

5. **Report** the version transition, whether a reboot occurred, and any warnings.

## Recovery A: stalled update (unreachable repo)

pkg fetches every configured repo's catalog before installing, so one unreachable
third-party repo (historically SunnyValley/Zenarmor) hangs the whole run with the web UI
frozen. Recovery is manual, on the firewall via SSH as root:

1. Kill the stuck pkg process.
2. `mv /usr/local/etc/pkg/repos/SunnyValley.conf{,.disabled}`
3. Re-run the update, then re-enable the repo afterwards.

## Recovery B: Zenarmor post-install deadlock

Different failure, different fix -- do NOT disable the repo here. The catalogues fetched
fine and the download completed; pkg is stuck in post-install. Recurs on every `os-sensei`
update and never self-clears.

Signature: log frozen right after `CLI check-fix done`, status still `running`, and the
stall warning mentions no repo error. Zenarmor's `killbypid()` loop spins on `kill -0`
against a resolver pid that is already a zombie child of pkg -- only pkg can reap it, and
pkg is the one waiting.

Diagnose read-only over SSH (see `fw.sh` in the project root):

```
ps -ax -o pid,ppid,stat,wchan,command | grep -E 'pkg|php|sensei'
ps -ax -o pid,ppid,stat,command | awk '$3 ~ /Z/'
```

The chain is `pkg-static` (wait/select) -> `post-install.sh` -> `CLI.php` (piperd) ->
`CLIResolv.php` (nanslp). Fix: plain `kill <CLIResolv.php pid>` -- SIGTERM has been enough
every time; verify the pid still maps to `CLIResolv.php` immediately before killing. pkg
then reaps the zombies, finishes, and the batch's automatic reboot fires.

Expect DNS to be down during the hang (the zombies are `unbound`/`dnsmasq`), and expect
post-install to advance to a new step that may park again -- same fix, new pid.

## Notes

- `watch-update.sh` is a thin launcher; the watcher logic is `watch_update.py`, run from
  `mcp/.venv`. It imports the MCP package directly (`Config`, `OPNsenseAPI`,
  `_repo_error`), so repo-error detection and config loading have a single source of
  truth with the MCP server.
- The script is read-only: it only GETs firmware status endpoints.
- Credentials come from `mcp/.env` via the MCP package loader (`OPNSENSE_*` environment
  variables override it); the script never prints them.
- Output is duplicated to `logs/watch-update-YYYYMMDD-HHMMSS.log`; a one-line result is
  appended to `logs/install-status.log`.
- Env knobs: `POLL_SECONDS` (default 20), `STALL_AFTER` (300), `MAX_SECONDS` (1800),
  `NO_RUN_AFTER` (90, wait for the run to appear before giving up).
- Regression tests: `test_watch_update.py` drives the full state machine with a fake API
  (no firewall needed): `mcp/.venv/bin/python .claude/skills/watch-update/test_watch_update.py`
