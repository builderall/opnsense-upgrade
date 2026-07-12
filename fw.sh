#!/usr/bin/env bash
#
# fw.sh - SSH ControlMaster wrapper for the OPNsense firewall.
#
# Opens one authenticated SSH connection and reuses it for troubleshooting
# commands and remote shells. Uses the same socket path as the python/ SSH
# drivers (test-on-firewall.sh, run-upgrade-on-firewall.sh), so opening the
# socket here serves those scripts too.
#
set -uo pipefail

FW_HOST="${FW_HOST:-root@192.168.1.1}"
SOCK="${SOCK:-/tmp/opnsense.sock}"

usage() {
    cat <<EOF
fw.sh - SSH control-socket wrapper for the OPNsense firewall

Purpose:
  Authenticate to the firewall once (SSH ControlMaster), then reuse that
  connection for troubleshooting: one-shot commands, scripted /bin/sh input,
  or an interactive shell. The socket is shared with the python/ SSH drivers,
  so 'open' here also unlocks test-on-firewall.sh and run-upgrade-on-firewall.sh.

Usage:
  ./fw.sh <command> [args]

Commands:
  open          Open the control socket (asks to authenticate; idles out after 1h)
  status        Report whether the control socket is alive
  run <cmd...>  Run a one-shot command on the firewall
  sh            Pipe stdin through remote /bin/sh (for heredocs; avoids tcsh quirks)
  shell         Interactive login shell on the firewall
  close         Close the control socket
  help          Show this help

Environment overrides:
  FW_HOST   SSH destination        (default: root@192.168.1.1)
  SOCK      control socket path    (default: /tmp/opnsense.sock)

Examples:
  ./fw.sh open
  ./fw.sh run 'opnsense-version; uname -r'
  ./fw.sh run 'pgrep -lP 12345'      # children of a wedged pkg process
  ./fw.sh sh <<'EOF2'
  ps -auxww | grep pkg
  procstat kstack 12345
  EOF2
  FW_HOST=root@10.0.0.1 ./fw.sh shell

Note: 'run', 'sh', and 'shell' open the socket automatically if it is not
already up. The remote login shell is tcsh -- prefer 'sh' for anything with
redirects, loops, or heredocs.
EOF
}

master_up() { ssh -S "$SOCK" -O check "$FW_HOST" 2>/dev/null; }

ensure_open() {
    if master_up; then
        return 0
    fi
    echo "Control socket not open -- opening ${SOCK} to ${FW_HOST} ..."
    ssh -M -S "$SOCK" -o ControlPersist=1h -fN "$FW_HOST"
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    open)
        ensure_open
        echo "Control socket open: ${SOCK} -> ${FW_HOST}"
        ;;
    status)
        if master_up; then
            echo "OPEN: ${SOCK} -> ${FW_HOST}"
        else
            echo "CLOSED: ${SOCK} (run './fw.sh open')"
            exit 1
        fi
        ;;
    close)
        if master_up; then
            ssh -S "$SOCK" -O exit "$FW_HOST"
        else
            echo "Control socket already closed: ${SOCK}"
        fi
        ;;
    run)
        if [ $# -eq 0 ]; then
            echo "Usage: ./fw.sh run '<command>'" >&2
            exit 2
        fi
        ensure_open
        ssh -S "$SOCK" "$FW_HOST" "$@"
        ;;
    sh)
        ensure_open
        ssh -S "$SOCK" "$FW_HOST" sh
        ;;
    shell)
        ensure_open
        ssh -S "$SOCK" "$FW_HOST"
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        echo "Unknown command: $cmd (use './fw.sh help')" >&2
        exit 2
        ;;
esac
