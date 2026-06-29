#!/usr/bin/env bash
#
# run-upgrade-on-firewall.sh - Deploy and run opnsense-upgrade.py on a live
# OPNsense firewall over SSH, as a fallback for when the MCP server or web UI
# is having issues.
#
# Dry-run by default (the upgrade script only previews, changing nothing). Pass
# --execute to perform a REAL update/upgrade; the wrapper asks you to confirm.
#
# A real run is launched DETACHED on the firewall (nohup) so a mid-upgrade
# reboot or an SSH drop does not kill it -- the upgrade keeps running on the box
# and (for major upgrades) auto-resumes after reboot. The wrapper then follows
# the log until completion or until the connection drops at reboot. Because a
# detached run has no TTY for the script's own confirmation prompt, the wrapper
# confirms instead and passes -f.
#
# Usage:
#   ./run-upgrade-on-firewall.sh [mode] [options]
#
# Modes (pick one; default --latest):
#   --latest          Query available versions (read-only)
#   --minor           Minor update within the current branch
#   --major VERSION   Major upgrade to VERSION (e.g. 26.7)
#   --auto-major      Auto-detect and upgrade to the next major
#   --resume          Resume an interrupted upgrade
#   --backup          Back up config + package list only
#   --clean           Clear saved upgrade state
#
# Options:
#   --execute         Actually run (default is a dry-run preview)
#   --yes             Skip the interactive confirmation for --execute
#   --no-deploy       Do not scp the local script first (use what is on the box)
#   --follow          Re-attach to an in-progress detached run (e.g. after reboot)
#   --help
#
# Env overrides: FW_HOST, SOCK, REMOTE_SCRIPT
#
set -uo pipefail

FW_HOST="${FW_HOST:-root@192.168.1.1}"
SOCK="${SOCK:-/tmp/opnsense.sock}"
REMOTE_SCRIPT="${REMOTE_SCRIPT:-/root/opnsense-upgrade.py}"
RESUME_LOG="/var/log/opnsense-upgrade-resume.log"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPT="${SCRIPT_DIR}/opnsense-upgrade.py"

usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^#\{0,1\} \{0,1\}//'; }

MODE_ARGS=()
DESC=""
REAL_MODE=0          # mode that mutates state (minor/major/auto-major/resume)
EXECUTE=0 YES=0 DEPLOY=1 FOLLOW=0

while [ $# -gt 0 ]; do
    case "$1" in
        --latest)     MODE_ARGS=(-l);     DESC="query latest versions" ;;
        --minor)      MODE_ARGS=(-m);     DESC="minor update";              REAL_MODE=1 ;;
        --major)      shift; [ $# -gt 0 ] || { echo "--major needs VERSION"; exit 2; }
                      MODE_ARGS=(-t "$1"); DESC="major upgrade to $1";       REAL_MODE=1 ;;
        --auto-major) MODE_ARGS=(-t);     DESC="auto-detected major upgrade"; REAL_MODE=1 ;;
        --resume)     MODE_ARGS=(-r);     DESC="resume interrupted upgrade";  REAL_MODE=1 ;;
        --backup)     MODE_ARGS=(-b);     DESC="backup config + package list" ;;
        --clean)      MODE_ARGS=(-c);     DESC="clean saved state" ;;
        --execute)    EXECUTE=1 ;;
        --yes)        YES=1 ;;
        --no-deploy)  DEPLOY=0 ;;
        --follow)     FOLLOW=1 ;;
        --help|-h)    usage; exit 0 ;;
        *) echo "Unknown option: $1 (use --help)"; exit 2 ;;
    esac
    shift
done
[ "${#MODE_ARGS[@]}" -gt 0 ] || { MODE_ARGS=(-l); DESC="query latest versions"; }

strip() { sed 's/\x1b\[[0-9;]*m//g'; }
master_up() { ssh -S "$SOCK" -O check "$FW_HOST" 2>/dev/null; }
rcmd() { ssh -S "$SOCK" "$FW_HOST" "$@"; }

require_socket() {
    master_up && return 0
    cat <<MSG
==================================================================
SSH control socket is not open: $SOCK

Open a master connection in YOUR terminal (prompts for the root
password once; stays alive 1 hour):

    ssh -M -S $SOCK -o ControlPersist=1h -fN $FW_HOST

Then re-run this script. To close it when done:

    ssh -S $SOCK -O exit $FW_HOST
==================================================================
MSG
    exit 1
}

# follow_log <remote_log> <pidfile> -- stream new lines until the process exits
# or the connection drops (a reboot). Tracks how many lines were already shown.
follow_log() {
    local log="$1" pidfile="$2" seen=0 total pid
    while :; do
        if ! rcmd true 2>/dev/null; then
            echo
            echo "** Connection lost -- the firewall is likely rebooting for the upgrade. **"
            echo "   Re-open the SSH master, then follow the auto-resume with:"
            echo "       $0 --follow"
            return 0
        fi
        total="$(rcmd "wc -l < $log" 2>/dev/null | tr -d ' ')"; : "${total:=0}"
        if [ "$total" -gt "$seen" ]; then
            rcmd "sed -n '$((seen + 1)),\$p' $log" | strip
            seen="$total"
        fi
        pid="$(rcmd "cat $pidfile" 2>/dev/null)"
        # Wrap in remote sh: tcsh's kill writes "No such process" to stdout,
        # which a local 2>/dev/null would not suppress.
        if [ -n "$pid" ] && ! rcmd "sh -c 'kill -0 $pid 2>/dev/null'" 2>/dev/null; then
            rcmd "sed -n '$((seen + 1)),\$p' $log" | strip
            rcmd "rm -f $pidfile" 2>/dev/null
            echo
            echo "** Upgrade process finished on the firewall. **"
            return 0
        fi
        sleep 5
    done
}

require_socket

# --follow: re-attach to the most recent detached run and the resume log.
if [ "$FOLLOW" -eq 1 ]; then
    echo "Following latest wrapper log + auto-resume log (Ctrl-C to stop)..."
    rcmd "ls -t /var/log/opnsense-upgrades/wrapper-*.log 2>/dev/null | head -1 \
          | xargs -I{} sh -c 'echo \"== {} ==\"; tail -n 40 {}'" | strip
    echo "== ${RESUME_LOG} (live) =="
    rcmd "touch $RESUME_LOG 2>/dev/null; tail -n +1 -f $RESUME_LOG" | strip
    exit 0
fi

echo "Target: $FW_HOST   Mode: ${MODE_ARGS[*]}   (${DESC})   (log dir: /var/log/opnsense-upgrades)"
rcmd 'opnsense-version' | strip

# Deploy the local script unless told not to.
if [ "$DEPLOY" -eq 1 ] && [ -f "$LOCAL_SCRIPT" ]; then
    scp -o ControlPath="$SOCK" "$LOCAL_SCRIPT" "${FW_HOST}:${REMOTE_SCRIPT}" >/dev/null
    rcmd "chmod +x $REMOTE_SCRIPT"
    echo "Deployed local script -> ${REMOTE_SCRIPT}"
fi

PYARGS=("${MODE_ARGS[@]}")

# --- Dry-run / read-only path: run directly and stream (no reboot risk) ---
if [ "$EXECUTE" -eq 0 ] || [ "$REAL_MODE" -eq 0 ]; then
    [ "$REAL_MODE" -eq 1 ] && echo "(dry-run preview -- add --execute to perform it for real)"
    rcmd "${REMOTE_SCRIPT} ${PYARGS[*]}" | strip
    exit 0
fi

# --- Real run: confirm, then launch DETACHED with -f and follow the log ---
if [ "$YES" -eq 0 ]; then
    ans=""
    # Open the controlling terminal directly; this fails (and we refuse) when
    # there is no interactive TTY, so a real upgrade never proceeds unconfirmed.
    if { exec 3<>/dev/tty; } 2>/dev/null; then
        printf 'About to perform a REAL %s on %s. Type "yes" to proceed: ' "$DESC" "$FW_HOST" >&3
        IFS= read -r ans <&3 || ans=""
        exec 3>&- 2>/dev/null || true
        [ "$ans" = "yes" ] || { echo "Aborted."; exit 1; }
    else
        echo "Refusing a real upgrade without an interactive terminal. Re-run with --yes."
        exit 1
    fi
fi

PYARGS+=(-x -f)   # detached run has no TTY for the script's own confirm prompt
TS="$(date +%Y%m%d-%H%M%S)"
REMOTE_LOG="/var/log/opnsense-upgrades/wrapper-${TS}.log"
PIDFILE="/tmp/opnsense-wrapper-${TS}.pid"

rcmd "sh -c 'nohup ${REMOTE_SCRIPT} ${PYARGS[*]} > ${REMOTE_LOG} 2>&1 < /dev/null & \
      echo \$! > ${PIDFILE}'"
echo "Launched DETACHED on firewall (survives SSH drop / reboot)."
echo "  remote log: ${REMOTE_LOG}"
echo "  resume log: ${RESUME_LOG} (after a reboot)"
echo
follow_log "$REMOTE_LOG" "$PIDFILE"
