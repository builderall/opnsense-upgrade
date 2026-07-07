#!/usr/bin/env bash
#
# test-on-firewall.sh - Run the opnsense-upgrade.py test suite against a live
# OPNsense firewall over SSH, using an SSH ControlMaster socket so you only
# authenticate once.
#
# All tests are read-only or dry-run except the backup stage (-b), which only
# writes a config backup to /root/config-backups/. Nothing destructive is run.
#
# Usage:
#   ./test-on-firewall.sh              # run the suite (needs the socket open)
#   ./test-on-firewall.sh --deploy     # scp the local script to the firewall first
#   ./test-on-firewall.sh --help
#
# Override defaults via env: FW_HOST, SOCK, REMOTE_SCRIPT
#   FW_HOST=root@10.0.0.1 ./test-on-firewall.sh
#
set -uo pipefail

FW_HOST="${FW_HOST:-root@192.168.1.1}"
SOCK="${SOCK:-/tmp/opnsense.sock}"
REMOTE_SCRIPT="${REMOTE_SCRIPT:-/root/opnsense-upgrade.py}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPT="${SCRIPT_DIR}/opnsense-upgrade.py"
LOCAL_TESTS="${SCRIPT_DIR}/test_shell.py"

DEPLOY=0
case "${1:-}" in
    --help|-h)
        sed -n '3,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    --deploy) DEPLOY=1 ;;
    "") ;;
    *) echo "Unknown option: $1 (use --help)"; exit 2 ;;
esac

# Tee all output to a timestamped log alongside the script.
LOGS_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOGS_DIR"
LOG_FILE="${LOGS_DIR}/firewall-tests-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

# expect() runs on the right of a pipe (a subshell), so tally to temp files
# rather than shell vars — the parent cannot see a subshell's variable writes,
# and shopt lastpipe is unavailable on macOS bash 3.2.
PASS_FILE="$(mktemp)"
FAIL_FILE="$(mktemp)"
trap 'rm -f "$PASS_FILE" "$FAIL_FILE"' EXIT

strip() { sed 's/\x1b\[[0-9;]*m//g'; }
rsh() { ssh -S "$SOCK" "$FW_HOST" sh; }   # run remote /bin/sh reading stdin (avoids tcsh quirks)

hdr() { echo; echo "########## $* ##########"; }
note() { echo "    -> $*"; }

# expect <description> <pattern> -- reads stdin, marks PASS if pattern is found
expect() {
    local desc="$1" pat="$2" out
    out="$(cat)"
    echo "$out" | strip
    if echo "$out" | grep -qE "$pat"; then
        echo x >> "$PASS_FILE"; note "PASS: $desc"
    else
        echo x >> "$FAIL_FILE"; note "FAIL: $desc (expected /$pat/)"
    fi
}

# --- Preflight: is the control socket open? ---
if ! ssh -S "$SOCK" -O check "$FW_HOST" 2>/dev/null; then
    cat <<MSG
==================================================================
SSH control socket is not open: $SOCK

Open a master connection in YOUR terminal (you will be prompted for
the firewall root password once). It stays alive for 1 hour:

    ssh -M -S $SOCK -o ControlPersist=1h -fN $FW_HOST

Then re-run this script:

    $0 ${1:-}

To close the connection when finished:

    ssh -S $SOCK -O exit $FW_HOST
==================================================================
MSG
    exit 1
fi
echo "Control socket OK -> $FW_HOST   (log: $LOG_FILE)"

# --- Optional: deploy the local script to the firewall ---
if [ "$DEPLOY" -eq 1 ]; then
    hdr "Deploy local script -> $REMOTE_SCRIPT"
    scp -o ControlPath="$SOCK" "$LOCAL_SCRIPT" "${FW_HOST}:${REMOTE_SCRIPT}"
    ssh -S "$SOCK" "$FW_HOST" "chmod +x ${REMOTE_SCRIPT}"
    note "deployed"
fi

# --- 0. Connectivity + version + script-version match ---
hdr "0. Connectivity and version"
ssh -S "$SOCK" "$FW_HOST" 'opnsense-version; uname -r' | strip
if [ -f "$LOCAL_SCRIPT" ]; then
    LMD5="$(md5sum "$LOCAL_SCRIPT" | awk '{print $1}')"
    RMD5="$(ssh -S "$SOCK" "$FW_HOST" "md5 -q ${REMOTE_SCRIPT}" 2>/dev/null)"
    if [ "$LMD5" = "$RMD5" ]; then
        note "deployed script matches local (md5 $RMD5)"
    else
        note "WARNING: deployed script differs from local"
        note "local=$LMD5 remote=$RMD5 -- run with --deploy to sync"
    fi
fi

# --- 1. Third-party repo reachability (read-only) ---
hdr "1. check_third_party_repos (read-only)"
rsh <<PYEOF | expect "repo check returns a list" "unreachable repos: \["
python3 - <<'PY'
import importlib.util
s = importlib.util.spec_from_file_location("u", "${REMOTE_SCRIPT}")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
log = m.Logger("/tmp/repotest"); sh = m.Shell(log, False)
print("unreachable repos:", m.SystemInfo(sh, log).check_third_party_repos())
PY
rm -rf /tmp/repotest
PYEOF

# --- 2. Dry-run major upgrade to an unreleased version (mirror validation) ---
hdr "2. Dry-run -t 26.7 (mirror validation rejects unreleased)"
ssh -S "$SOCK" "$FW_HOST" "${REMOTE_SCRIPT} -t 26.7" \
    | expect "rejects unreleased version" "not found on pkg mirror"

# --- 3. Dry-run auto-detect major ---
hdr "3. Dry-run -t (major auto-detect)"
ssh -S "$SOCK" "$FW_HOST" "${REMOTE_SCRIPT} -t" \
    | expect "reports up to date / no major" "up to date|already on latest|No major upgrade"

# --- 4. Resume with no saved state ---
hdr "4. -r with no saved state (detect_state)"
ssh -S "$SOCK" "$FW_HOST" "${REMOTE_SCRIPT} -r" \
    | expect "nothing to resume" "Nothing to resume|already fully upgraded"

# --- 5. Backup stage (writes a config backup) ---
hdr "5. -b backup stage (writes a config backup)"
ssh -S "$SOCK" "$FW_HOST" "${REMOTE_SCRIPT} -b" \
    | expect "config backed up" "Config backed up|Backup completed"

# --- 6. Unit tests under the firewall's Python ---
hdr "6. test_shell.py under firewall python3"
if [ -f "$LOCAL_TESTS" ]; then
    scp -o ControlPath="$SOCK" "$LOCAL_TESTS" "${FW_HOST}:/root/test_shell.py" >/dev/null
    rsh <<'PYEOF' | expect "all unit tests pass" "All tests passed"
python3 --version
cd /root && python3 test_shell.py
rm -f /root/test_shell.py
PYEOF
else
    note "SKIP: $LOCAL_TESTS not found"
fi

# --- 7. Bare -t with -b must enter the upgrade flow, not standalone backup ---
# Regression test for the flag collision fixed in PR #8: bare -t sets target=None,
# which used to match the standalone-backup condition and silently skip the
# upgrade. "No target version specified" is printed only by the upgrade flow —
# the standalone backup path prints "Configuration Backup" instead.
hdr "7. Dry-run -t -b (flag collision: upgrade flow, not standalone backup)"
ssh -S "$SOCK" "$FW_HOST" "${REMOTE_SCRIPT} -t -b" \
    | expect "bare -t with -b enters upgrade flow" "No target version specified"

# --- Summary ---
PASS="$(wc -l < "$PASS_FILE" | tr -d ' ')"
FAIL="$(wc -l < "$FAIL_FILE" | tr -d ' ')"
hdr "Summary"
echo "PASS: $PASS    FAIL: $FAIL"
echo "Log: $LOG_FILE"
[ "$FAIL" -eq 0 ] || exit 1
