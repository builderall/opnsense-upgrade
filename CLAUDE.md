# Project: OPNsense Enhanced Upgrade Script

## Overview

Multi-tool project for managing OPNsense firewall upgrades. Three components:

- **python/** — Main upgrade script (runs on OPNsense via SSH as root)
- **ps1/** — Windows PowerShell recovery tools (split routing for failed upgrades)
- **mcp/** — Claude MCP server for OPNsense API integration (built and working)

## Key Files

- `python/opnsense-upgrade.py` — The main upgrade script. Stateful, multi-stage, dry-run by default.
- `ps1/Enable-SplitRouting-WithModule.ps1` — Split routing setup for upgrade recovery.
- `MCP-PLAN.md` — Original MCP server design plan (implemented).
- `mcp/SETUP.md` — Step-by-step setup guide for new users.
- `mcp/src/opnsense_mcp/` — MCP server Python package (see MCP Server section below).
- `.claude/skills/watch-update/` — Claude Code skill: follows a running update through the
  mid-update reboot via a Monitor event stream. Watcher logic is `watch_update.py` (runs
  from mcp/.venv, imports the MCP package — single source of truth for repo-error
  detection and config); `watch-update.sh` is a thin launcher kept as the stable entry
  point for the Monitor command and the PostToolUse hook.
- `.claude/settings.json` — project hook: after `run_update`/`run_upgrade` actually triggers
  (response contains "triggered"; blocked/no-op responses are ignored), a PostToolUse hook
  injects an instruction to invoke the watch-update skill, so no update runs unwatched.
- `push.sh` — Push to GitHub using gh CLI token (auto-creates repo on first run).

## Conventions

- Version: 1.3 (tagged v1.3 on GitHub; first release was v1.0)
- Dry-run by default, `-x` to execute
- Keep READMEs in each subdirectory
- No emojis in code or docs
- Python script targets Python 3 on FreeBSD (OPNsense)
- MCP server targets Python 3.10+ on user's workstation (Linux/WSL)

### Language Policy

Each language has a defined role — do not deviate for new components:

| Language | Used for | Why |
|---|---|---|
| Python 3 (stdlib only) | `python/opnsense-upgrade.py` + its tests | Runs on the firewall (FreeBSD); no pip there |
| Python 3.10+ (mcp/.venv) | `mcp/` package; any workstation tool with logic (e.g. the watch-update watcher) | One venv, one source of truth — tools import `Config`, `OPNsenseAPI`, `_repo_error` from the MCP package instead of re-implementing them |
| bash | Orchestration and glue only: SSH drivers (`test-on-firewall.sh`, `run-upgrade-on-firewall.sh`), thin launchers, `push.sh` | Process/pipe wrangling is what shell is for; no business logic |
| PowerShell | `ps1/` Windows-side recovery tools | Windows host is the runtime |

Rules of thumb:
- If a bash script needs `python3 -c` more than once, it should be a Python script with a
  thin bash launcher (see `.claude/skills/watch-update/`).
- Never re-implement MCP package logic (repo-error detection, .env parsing, API calls) in
  another language — import it from `mcp/.venv` instead. The original bash watcher did,
  and the duplicated `_repo_error()` signature was a standing drift risk until PR #12.
- Launchers exist to keep stable entry points (Monitor commands, hooks, docs); keep them
  under ~20 lines with no logic beyond path resolution and exec.

## OPNsense Context

- Firewall hostname: `OPNsense.home.lan` (user's local DNS)
- Current version: 26.1.11_6 (incrementally updated from 26.1.1 during development)
- Next major version: 26.7 (confirmed via API `CORE_NEXT` field)
- Version format: YY.M.P (e.g., 26.1.2) with pkg revision suffix `_N` (e.g., 26.1.2_5) — always strip suffix for comparisons
- Minor updates: within same branch (26.1.1 -> 26.1.2)
- Major upgrades: across branches (26.1 -> 26.7), require base/kernel upgrade + reboot
- OPNsense REST API at `/api/core/firmware/` — confirmed working
- `pkg` can break after base/kernel upgrade due to ABI mismatch — the python script handles this

## GitHub

- Repo: https://github.com/builderall/opnsense-upgrade
- Branch: master
- Tags: v1.0 (initial) through v1.3 (latest)
- Git user: builderall / 25215839+builderall@users.noreply.github.com (set locally, not globally)
- Push with: `./push.sh` (uses gh CLI token, auto-creates repo if missing)
- All work is pushed; changes land on master via PRs (merge commits, e.g. #1-#3)

## MCP Server

**Status: Live tested via Claude Code sessions — all read tools plus `run_update` exercised
against the real firewall. Only `run_upgrade`/`reboot` execution remains untested (needs the
26.7 major release).**

### Structure

```
mcp/
├── .env                          # credentials (gitignored) — loaded automatically by config.py
├── .venv/                        # Python 3.12 venv (gitignored) — mcp 1.26.0, httpx 0.28.1, pydantic 2.12.5
├── requirements.txt              # mcp, httpx, pydantic
├── pyproject.toml
├── SETUP.md                      # user setup guide
├── tests/
│   └── test_batch_summary.py     # pending-batch reporting tests (no network; run via .venv)
└── src/opnsense_mcp/
    ├── config.py                 # loads mcp/.env, pydantic Config model
    ├── api.py                    # OPNsenseAPI class — HTTP calls, reboot staleness, batch_summary()
    ├── tools.py                  # 10 MCP tools registered via list_tools/call_tool decorators
    └── server.py                 # asyncio entry point, started by Claude Code via settings.json
```

### Registered in Claude Code

Registered via `claude mcp add` CLI (writes to `~/.claude.json`, user scope):

```bash
claude mcp add --scope user opnsense -- bash \
  -c "cd ~/projects/opnsense-upgrade/mcp && exec .venv/bin/python -m src.opnsense_mcp.server"
```

Resulting entry in `~/.claude.json` (top-level `mcpServers`, not inside `projects`):
```json
{
  "mcpServers": {
    "opnsense": {
      "type": "stdio",
      "command": "bash",
      "args": ["-c", "cd ~/projects/opnsense-upgrade/mcp && exec .venv/bin/python -m src.opnsense_mcp.server"],
      "env": {}
    }
  }
}
```

Note: `~/.claude/settings.json` is for the Claude Code CLI only — the VSCode extension uses `~/.claude.json`.

### Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major |
| `check_updates` | read | Minor/major update availability + reboot status |
| `upgrade_status` | read | Monitor in-progress upgrade |
| `get_changelog` | read | Changelog for a specific version |
| `list_packages` | read | Installed packages with versions |
| `system_info` | read | Uptime, load average, top processes |
| `run_update` | write | Trigger minor update (requires user confirmation) |
| `run_upgrade` | write | Trigger major upgrade (requires user confirmation) |
| `reboot` | write | Reboot firewall (requires user confirmation) |
| `pre_upgrade_check` | read | Pre-upgrade health assessment: pending minor updates, reboot status, in-progress detection, py37 packages, go/no-go verdict |

Write tools are blocked when `OPNSENSE_READ_ONLY=true` in `.env`.

### OPNsense API User (claude-mcp)

Privileges required:
- `System: Firmware` — firmware status, update, upgrade
- `Diagnostics: System Activity` — uptime via `POST /api/diagnostics/activity/getActivity`

### Pending MCP Work

1. **Test `run_upgrade` + `reboot`** — guards verified working; actual execution still pending a real major upgrade (26.7 when released). `run_update` is now exercised live (see Completed).

### Completed MCP Work

- Pending-batch reporting (2026-07-12) — `check_updates`/`pre_upgrade_check`/`run_update` now
  list every pending package (name, version change, repo, action) and classify the batch via
  shared `batch_summary()` in `api.py` (core = `base`/`kernel`/`opnsense*`). A plugin-only
  batch no longer reads as an OPNsense point release ("Minor update available: 26.1.11" when
  the version would not change), and `check_needs_reboot()` attributes a pending-batch reboot
  to the packages requesting it. Incident: os-sensei/os-sensei-agent 2.6 -> 2.6.1 (SunnyValley,
  173 MiB, reboot flagged) looked like a kernel/base minor update. Tests:
  `mcp/tests/test_batch_summary.py` (fixture = live incident data, no network).
- Live tested all 10 read tools against OPNsense 26.1.2 via Claude Code VSCode session — all working.
- `run_update` exercised live during the 26.1.8_5 -> 26.1.10 minor update — trigger, duplicate-run guard, and "already up to date" guard all confirmed.
- `check_services` and `get_config_backup` removed — both require admin-level API access not grantable via restricted keys.
- Path expansion confirmed — `~` expands correctly in `bash -c "cd ~/..."` args.
- mcp/.env URL confirmed — `https://192.168.1.1` working.
- Error handling added — graceful messages for ConnectError, TimeoutException, HTTPStatusError.
- Safety guards on write tools — blocks duplicate runs, pending minor updates before major upgrade, unreleased versions.
- mcp/README.md added — user-facing README for the mcp/ directory.
- `system_info` columns fixed — `getActivity` (top `-aHSTn` thread mode) exposes `WCPU` and `RES`, not `%CPU`/`%MEM`, so both columns were always blank. CPU% now falls back through `%CPU`/`WCPU`/`CPU`/`C`; the memory column falls back through `%MEM`/`MEM`/`RES`/`SIZE` and is relabeled `RES` (resident size, e.g. eastpect at 284M). Verified live on 26.1.10.
- `pre_upgrade_check` now flags an unreachable pkg repo (via `status_msg`) as a NOT-READY issue — see the SunnyValley/Zenarmor incident note below.
- Write tools now refuse on an unreachable repo — `run_update`/`run_upgrade` call shared `_repo_error()` and return `_repo_blocked_text()` instead of triggering a doomed (hanging) run; `upgrade_status` appends a stall warning when a `running` status coincides with a repo error. Repo-error detection is now one shared helper used by all five tools including `check_updates` (was inline in `pre_upgrade_check`).
- Post-merge review fixes (2026-07-06) — `upgrade_status`'s repo probe is best-effort (a second `firmware_status()` call could time out on a wedged firewall and discard the already-gathered log report); `check_updates` converted to the shared `_version_state()`/`_repo_error()` helpers (its inline copy diverged: missing `current_base` truthiness guard) and now warns on an unreachable repo; dead `product`/`current_base` keys dropped from `_version_state()`; `pyproject.toml` build backend fixed to `setuptools.build_meta` (previous value was invalid, `pip install` would fail).

## Testing Status (python script)

- **Deployed on firewall:** v1.3 with PR #8 fixes, copied to `/root/opnsense-upgrade.py`
  on 2026-07-06 (md5-verified, compile + `-l` smoke-tested live). The firewall copy does
  NOT auto-update — redeploy after every merged change to `python/opnsense-upgrade.py`
  via `python/test-on-firewall.sh --deploy` (needs the SSH control socket open; the v1.0
  copy sat stale on the firewall for months before this was caught).
- Minor update (26.1.1 -> 26.1.2) tested successfully on OPNsense 26.1
- `pkg rquery '%v' opnsense` confirmed as reliable minor version detection fallback
- Reboot detection (`"please reboot" in output`) logic correct but untested — minor update did not change the FreeBSD kernel so no reboot was triggered
- Auto-resume via `/etc/rc.local.d/` not yet tested — needs a major upgrade with actual base/kernel reboot to verify. If it fails, user must manually run `./opnsense-upgrade.py -x -r` after reboot.

## MCP API Notes

- `needs_reboot: 1` in firmware status after 26.1.2 upgrade: **leftover artifact** — UI shows no reboot needed. The flag persists in the cached API response even after the reboot. Fixed in `api.py`: if no packages are pending and `status == 'none'`, flag is treated as stale regardless of timing.
- Reboot staleness logic in `api.py` (four-stage): (1) **pending packages + `status` in (`update`, `upgrade`) => `pending_update_reboot`** — the flag describes the *upcoming* batch ("applying this will reboot"), informational, never an issue; the explanation attributes the reboot via `batch_summary()` (kernel/base/core vs plugin-only, naming the packages); (2) **`upgrade_needs_reboot == '1'` => genuine, never stale** — OPNsense's authoritative signal that a just-applied update (e.g. a kernel bump) requires a reboot; this overrides the version-match path so a real post-update reboot is never hidden; (3) if no pending packages + (`status == 'none'` or current==latest) => leftover artifact, safe to ignore; (4) else compare uptime vs last_check_age — if `uptime < last_check_age`, check predates this boot => stale; if `uptime > last_check_age`, daemon ran after boot => genuine. Every `explanation` string leads with the verdict (`not required -- ...`, `REQUIRED -- ...`, `recommended -- ...`) and only then mentions the raw flag — a stale `needs_reboot` must never read as an action item (2026-07-12 wording fix).
- Unreachable third-party pkg repo (SunnyValley/Zenarmor) hangs both the web UI and `pkg` — `pkg` fetches every repo catalog before installing. Symptom: `check_updates` reports `status_msg` "Could not find the repository on the selected mirror" and an `update`/`upgrade` trigger never produces log output past the first two lines. `pre_upgrade_check` now detects this in `status_msg` (keyword `repositor` + an error word) and forces a NOT-READY verdict. Fix on the firewall: `mv /usr/local/etc/pkg/repos/SunnyValley.conf{,.disabled}`, retry, then re-enable. The python script also probes repo reachability in pre-checks. (Incident: 2026-06-28 during the 26.1.8_5 -> 26.1.10 update.)
- Zenarmor post-install deadlock (incident 2026-07-12, os-sensei 2.6 -> 2.6.1): the update
  hung ~25 min with `upgradestatus` stuck on `running` after "check-fix done". pkg waits for
  Zenarmor's `post-install.sh` -> `CLI.php` -> `CLIResolv.php`, whose `killbypid()` loop
  spins on `kill -0` against an unbound pid that was a *zombie child of pkg itself* — only
  pkg can reap it, and pkg is the one waiting. Diagnose over SSH (`pgrep -lP <pkg-pid>`
  shows daemons/zombies as pkg children; `procstat kstack` walks the chain); fix by killing
  the leaf `CLIResolv.php`, after which pkg finishes and the batch's auto-reboot fires. The
  agent package may land post-reboot via Zenarmor's `.senpaimustupdate` force-reinstall, so
  verify versions a few minutes after boot.
- Post-reboot `upgradestatus` residue: right after a reboot the endpoint reports
  `status: "error"` with an empty log — stale residue from the pre-reboot run, not a failure.
  The watch-update skill script ignores terminal statuses until it has seen the run start.
- `needs_reboot` pre-update semantics (FIXED 2026-07-06): OPNsense sets the flag when a
  *pending* update includes kernel/base (meaning "applying this will reboot"), which the
  uptime-comparison stage misread as a genuine outstanding reboot, so `pre_upgrade_check`
  listed "Reboot required before upgrading" as a NOT-READY issue — a false positive
  observed live before the 26.1.10 -> 26.1.11 update. Fixed via the
  `pending_update_reboot` stage in `check_needs_reboot()` (see staleness logic above);
  `pre_upgrade_check` now reports it as "(not a blocker)".
- `last_check` timezone caveat: `parse_last_check_age_seconds` strips the firewall's TZ name and compares against the workstation's local `datetime.now()` — only correct when firewall and workstation share a timezone. A differing TZ skews `last_check_age` by the offset and can flip the genuine/stale verdict.
- `GET` requests to diagnostics endpoints return 401; use `POST` for `getActivity` and similar.
- `CORE_NEXT: 26.7` confirmed in firmware status API — next major version detection works.
- Error handling in `tools.py` `call_tool`: top-level `try/except` catches `httpx.ConnectError` (firewall unreachable), `httpx.TimeoutException`, `httpx.HTTPStatusError` (4xx/5xx with status code), and general `Exception`. `ValueError` is re-raised so read-only blocks and unknown-tool errors surface normally to the MCP caller.
- `check_services` removed: `POST /api/core/service/search` returns 403 for all restricted API keys — OPNsense does not expose a grantable privilege for this endpoint. Service checking requires SSH/root access (handled by the python script instead).
- `get_config_backup` removed: `GET /api/core/backup/download/this` returns 403 even with `Diagnostics: Backup & Restore` privilege — OPNsense restricts backup download to admin-level access only.
