#!/usr/bin/env bash
# watch-update.sh -- follow an in-progress OPNsense firmware update through the reboot.
#
# Designed as a Claude Code Monitor event stream: every stdout line is one event.
# Read-only: only reads firmware status via the REST API; never triggers or mutates anything.
#
# Events emitted (one line each):
#   - initial state when armed
#   - stall warning when the log stops advancing (with repo-unreachable check, the
#     classic Zenarmor/SunnyValley stalled-update signature)
#   - API drop (firewall rebooting)
#   - back online + version (terminal)
#   - done + version (terminal, for updates that do not reboot)
#   - error + last log lines (terminal)
#
# The upgradestatus endpoint keeps the previous run's terminal status (and reports
# 'error' with an empty log right after a reboot), so a terminal status seen at arm
# time is stale residue, not this run's outcome. The script therefore waits for the
# run to appear (status 'running', or an API drop) before honoring terminal states;
# if none appears within NO_RUN_AFTER seconds it reports "nothing to watch".
#
# Env knobs: ENV_FILE (default mcp/.env), POLL_SECONDS (20), STALL_AFTER (300),
#            MAX_SECONDS (1800), NO_RUN_AFTER (90).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/mcp/.env}"
POLL_SECONDS="${POLL_SECONDS:-20}"
STALL_AFTER="${STALL_AFTER:-300}"
MAX_SECONDS="${MAX_SECONDS:-1800}"
NO_RUN_AFTER="${NO_RUN_AFTER:-90}"

LOGS_DIR="$ROOT/logs"
mkdir -p "$LOGS_DIR"
LOG_FILE="$LOGS_DIR/watch-update-$(date +%Y%m%d-%H%M%S).log"
STATUS_LOG="$LOGS_DIR/install-status.log"
# stdout is the Monitor event stream -- tee it to the log, but keep stderr out of
# the stream (curl/python noise must not become notification events).
exec > >(tee -a "$LOG_FILE") 2>>"$LOG_FILE"

status_to_log() {
    local type="$1" component="$2" status="$3" detail="${4:-}"
    printf "%-19s  %-8s  %-12s  %s\n" \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "[$type]" "$component" \
        "$status${detail:+  ($detail)}" >> "$STATUS_LOG"
}

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: env file not found: $ENV_FILE"
    exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
for v in OPNSENSE_URL OPNSENSE_API_KEY OPNSENSE_API_SECRET; do
    if [ -z "${!v:-}" ]; then
        echo "ERROR: $v not set (checked $ENV_FILE)"
        exit 1
    fi
done
AUTH="${OPNSENSE_API_KEY}:${OPNSENSE_API_SECRET}"
BASE="${OPNSENSE_URL%/}"

api() {  # api <path> -- GET, prints body or nothing on failure
    curl -sk -m 10 -u "$AUTH" "$BASE/api/$1" 2>/dev/null || true
}

jfield() {  # jfield <key> -- top-level string field from JSON on stdin, or ""
    python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1],""))' "$1" \
        2>/dev/null || true
}

fw_version() {
    api core/firmware/status | python3 -c \
        'import json,sys; print(json.load(sys.stdin)["product"]["product_version"])' \
        2>/dev/null || echo "?"
}

repo_error() {  # mirrors _repo_error() in mcp/src/opnsense_mcp/tools.py
    api core/firmware/status | python3 -c '
import json, sys
msg = (json.load(sys.stdin).get("status_msg") or "").lower()
words = ("could not", "not found", "unable", "fail", "unreachable", "error")
if "repositor" in msg and any(w in msg for w in words):
    print(msg)
' 2>/dev/null || true
}

log_tail() {  # last 5 log lines from an upgradestatus body on stdin
    python3 -c '
import json, sys
log = (json.load(sys.stdin).get("log") or "").strip()
print("\n".join(log.splitlines()[-5:]))
' 2>/dev/null || true
}

start=$(date +%s)
phase=waiting   # waiting: run not seen yet; watching: run confirmed
down=0
fails=0
warned_stall=0
last_log_len=0
last_log_change=$start

initial=$(api core/firmware/upgradestatus | jfield status)
echo "Watching update: initial status='${initial:-unreachable}', version=$(fw_version)"
if [ "$initial" = "running" ]; then
    phase=watching
fi

while true; do
    now=$(date +%s)
    if [ $((now - start)) -ge "$MAX_SECONDS" ]; then
        echo "GAVE UP after ${MAX_SECONDS}s -- run is not terminal; check the firewall manually"
        status_to_log UPDATE opnsense WARNING "watch-update gave up after ${MAX_SECONDS}s"
        exit 1
    fi

    body=$(api core/firmware/upgradestatus)

    if [ "$phase" = "waiting" ]; then
        # Ignore stale terminal statuses from a previous run; wait for this run to appear.
        if [ -z "$body" ]; then
            fails=$((fails + 1))
            if [ "$fails" -ge 2 ]; then
                echo "API unreachable -- firewall is likely rebooting now"
                phase=watching
                down=1
            fi
        else
            fails=0
            if [ "$(jfield status <<<"$body")" = "running" ]; then
                echo "Run detected (status=running)"
                phase=watching
                last_log_change=$now
            elif [ $((now - start)) -ge "$NO_RUN_AFTER" ]; then
                echo "No update run detected within ${NO_RUN_AFTER}s -- nothing to watch"
                exit 0
            fi
        fi
        sleep 5
        continue
    fi

    if [ -z "$body" ]; then
        fails=$((fails + 1))
        # two consecutive failures = real drop, not a transient blip
        if [ "$down" -eq 0 ] && [ "$fails" -ge 2 ]; then
            echo "API unreachable -- firewall is likely rebooting now"
            down=1
        fi
    elif [ "$down" -eq 1 ]; then
        ver=$(fw_version)
        echo "Firewall BACK ONLINE after reboot -- version: $ver"
        status_to_log UPDATE opnsense SUCCESS "back online at $ver"
        exit 0
    else
        fails=0
        s=$(jfield status <<<"$body")
        case "$s" in
        done)
            ver=$(fw_version)
            echo "Update finished (status=done, no reboot observed) -- version: $ver"
            status_to_log UPDATE opnsense SUCCESS "done at $ver"
            exit 0
            ;;
        error)
            echo "Update FAILED (status=error) -- last log lines:"
            log_tail <<<"$body"
            status_to_log UPDATE opnsense FAILED "status=error"
            exit 1
            ;;
        *)
            loglen=$(python3 -c \
                'import json,sys; print(len(json.load(sys.stdin).get("log") or ""))' \
                <<<"$body" 2>/dev/null || echo 0)
            if [ "$loglen" != "$last_log_len" ]; then
                last_log_len=$loglen
                last_log_change=$now
            elif [ "$warned_stall" -eq 0 ] && \
                 [ $((now - last_log_change)) -ge "$STALL_AFTER" ]; then
                warned_stall=1
                rerr=$(repo_error)
                if [ -n "$rerr" ]; then
                    echo "WARNING: log stalled ${STALL_AFTER}s and a pkg repo is" \
                         "unreachable ($rerr) -- the stalled-update signature." \
                         "Likely needs manual recovery on the firewall."
                else
                    echo "WARNING: log has not advanced in ${STALL_AFTER}s" \
                         "(status still '$s') -- keeping watch"
                fi
            fi
            ;;
        esac
    fi
    sleep "$POLL_SECONDS"
done
