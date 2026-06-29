#!/usr/local/bin/python3
"""Regression tests for the hang-prevention logic in opnsense-upgrade.py.

Covers Shell.run_tee_output's idle-timeout (kills a command that produces no
output, the failure that motivated it) and SystemInfo.host_reachable (an HTTP
error response still means the host is up). Pure stdlib, no network or OPNsense
dependencies — runs anywhere:

    python3 python/test_shell.py
"""

import importlib.util
import os
import socket
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "opnsense_upgrade", os.path.join(HERE, "opnsense-upgrade.py")
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures.append(name)


def make_shell():
    log = mod.Logger(tempfile.mkdtemp(prefix="opnsense-test-"), prefix="test")
    return mod.Shell(log, dry_run=False)


def test_timeout():
    sh = make_shell()

    # Normal stream completes fast and returns its output.
    ok, out = sh.run_tee_output("printf 'line1\\nline2\\n'")
    check("normal stream returns (True, output)", ok is True and "line1" in out and "line2" in out)

    # Silent hang is killed within the idle window.
    t0 = time.monotonic()
    ok, out = sh.run_tee_output("sleep 30", idle_timeout=2)
    check("silent hang killed within idle window", ok is False and out == "" and time.monotonic() - t0 < 5)

    # Output then hang: killed after output stops, output preserved.
    t0 = time.monotonic()
    ok, out = sh.run_tee_output("sh -c 'echo started; sleep 30'", idle_timeout=2)
    check("output-then-hang killed, output kept", ok is False and "started" in out and time.monotonic() - t0 < 6)

    # Nonzero exit returns fast (a real failure, not a timeout).
    t0 = time.monotonic()
    ok, out = sh.run_tee_output("sh -c 'echo hi; exit 3'", idle_timeout=10)
    check("nonzero exit returns fast as failure", ok is False and "hi" in out and time.monotonic() - t0 < 2)

    # run_tee delegates to run_tee_output and returns a bool.
    check("run_tee delegates and returns True", sh.run_tee("printf 'x\\n'") is True)

    # Dry-run never executes the command.
    dry = mod.Shell(sh.log, dry_run=True)
    check("dry-run returns (True, '') without executing", dry.run_tee_output("sleep 30") == (True, ""))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/ok" else 404)
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *_):
        pass


def test_host_reachable():
    sh = make_shell()
    si = mod.SystemInfo(sh, sh.log)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        check("HTTP 200 is reachable", si.host_reachable(f"http://127.0.0.1:{port}/ok") is True)
        check("HTTP 404 is still reachable", si.host_reachable(f"http://127.0.0.1:{port}/missing") is True)
    finally:
        server.shutdown()

    # A closed port -> connection refused -> unreachable.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed_port = s.getsockname()[1]
    s.close()
    check("connection refused is unreachable",
          si.host_reachable(f"http://127.0.0.1:{closed_port}/", timeout=3) is False)


if __name__ == "__main__":
    test_timeout()
    test_host_reachable()
    print()
    if _failures:
        print(f"{len(_failures)} test(s) FAILED: {', '.join(_failures)}")
        raise SystemExit(1)
    print("All tests passed.")
