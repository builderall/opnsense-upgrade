#!/usr/local/bin/python3
"""
opnsense-upgrade.py - Enhanced Stateful OPNsense Upgrade with Recovery

Handles multi-stage upgrades with automatic reboot handling, pkg incompatibility
fixes, and automatic recovery. Dry-run by default.

Features:
- Automatic version detection via configctl firmware status parsing
- Stateful upgrades that survive reboots with auto-resume
- Multi-stage process with pre-checks, cleanup, backup, and verification
- Supports both minor updates (26.1.1 -> 26.1.2) and major upgrades (26.1 -> 27.1)
- Shows help by default for safety (use -l to check versions, -x to execute)

Version: 1.0 | License: MIT
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError


# ==========================================================================
# Constants
# ==========================================================================

class Stage:
    """Upgrade stage identifiers and metadata."""
    INIT = 0
    PRECHECKS = 1
    CLEANUP = 2
    BACKUP = 3
    BASE_KERNEL = 4
    FIX_PKG = 6
    PACKAGES = 7
    POST_VERIFY = 8
    COMPLETE = 10

    NAMES = {
        0: "Initialization", 1: "Pre-checks", 2: "Cleanup", 3: "Backup",
        4: "Base/Kernel Upgrade", 6: "Fix pkg Compatibility",
        7: "Package Upgrade", 8: "Post-Verification", 10: "Complete",
    }

    # Execution order (excludes INIT, includes COMPLETE as sentinel)
    ORDER = [1, 2, 3, 4, 6, 7, 8, 10]

    @classmethod
    def name(cls, stage):
        return cls.NAMES.get(stage, "Unknown")


# ==========================================================================
# Logger
# ==========================================================================

class Logger:
    """Colored console output with file logging."""
    COLORS = {"info": "\033[0;36m", "success": "\033[0;32m",
              "warning": "\033[1;33m", "error": "\033[0;31m",
              "header": "\033[0;34m"}
    ICONS = {"info": "i ", "success": "✓ ", "warning": "⚠ ", "error": "✗ "}
    NC = "\033[0m"

    def __init__(self, log_dir, prefix="upgrade"):
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_file = f"{log_dir}/opnsense-{prefix}-{ts}.log"

    def _write(self, level, msg):
        color = self.COLORS[level]
        icon = self.ICONS.get(level, "")
        print(f"{color}{icon}{self.NC}{msg}", flush=True)
        try:
            with open(self.log_file, "a") as f:
                f.write(f"{icon}{msg}\n")
        except OSError:
            pass

    def info(self, msg):     self._write("info", msg)
    def success(self, msg):  self._write("success", msg)
    def warning(self, msg):  self._write("warning", msg)
    def error(self, msg):    self._write("error", msg)

    def header(self, msg):
        bar = "=" * 44
        color, nc = self.COLORS["header"], self.NC
        print(f"\n{color}{bar}{nc}\n{color}  {msg}{nc}\n{color}{bar}{nc}\n")
        try:
            with open(self.log_file, "a") as f:
                f.write(f"\n{bar}\n  {msg}\n{bar}\n\n")
        except OSError:
            pass


# ==========================================================================
# Shell — subprocess helper
# ==========================================================================

class Shell:
    """Wraps subprocess calls with dry-run and logging support."""

    def __init__(self, log: Logger, dry_run: bool):
        self.log = log
        self.dry_run = dry_run

    def output(self, cmd, timeout=30, include_stderr=False):
        """Run command and return stdout (ignores errors)."""
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            if include_stderr:
                return (r.stdout + r.stderr).strip()
            return r.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            return ""

    def run(self, cmd):
        """Run command, return True on success. Respects dry-run."""
        if self.dry_run:
            self.log.info(f"[DRY RUN] Would run: {cmd}")
            return True
        self.log.info(f"Running: {cmd}")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
            self._append_log(r.stdout + r.stderr)
            if r.returncode != 0:
                self.log.error(f"Command failed (exit {r.returncode}): {cmd}")
                return False
            return True
        except subprocess.TimeoutExpired:
            self.log.error(f"Command timed out: {cmd}")
            return False

    def run_tee(self, cmd):
        """Run command streaming output to console and log. Respects dry-run."""
        if self.dry_run:
            self.log.info(f"[DRY RUN] Would run: {cmd}")
            return True
        self.log.info(f"Running: {cmd}")
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with open(self.log.log_file, "a") as f:
                for line in proc.stdout:
                    decoded = line.decode("utf-8", errors="replace")
                    sys.stdout.write(decoded)
                    f.write(decoded)
            proc.wait()
            return proc.returncode == 0
        except OSError as e:
            self.log.error(f"Failed to run: {e}")
            return False

    def run_tee_output(self, cmd):
        """Like run_tee but also returns combined output for inspection."""
        if self.dry_run:
            self.log.info(f"[DRY RUN] Would run: {cmd}")
            return True, ""
        self.log.info(f"Running: {cmd}")
        collected = []
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with open(self.log.log_file, "a") as f:
                for raw in proc.stdout:
                    decoded = raw.decode("utf-8", errors="replace")
                    sys.stdout.write(decoded)
                    sys.stdout.flush()
                    f.write(decoded)
                    collected.append(decoded)
            proc.wait()
            return proc.returncode == 0, "".join(collected)
        except OSError as e:
            self.log.error(f"Failed to run: {e}")
            return False, ""

    def check(self, cmd):
        """Run command, return exit code 0 = True."""
        r = subprocess.run(cmd, shell=True, capture_output=True)
        return r.returncode == 0

    def _append_log(self, text):
        try:
            with open(self.log.log_file, "a") as f:
                f.write(text)
        except OSError:
            pass


# ==========================================================================
# SystemInfo — version and mirror queries
# ==========================================================================

class SystemInfo:
    """Queries system version info and pkg mirrors."""

    PKG_CONF = "/usr/local/etc/pkg/repos/OPNsense.conf"
    CHANGELOG_DIR = "/usr/local/opnsense/changelog"

    def __init__(self, shell: Shell, log: Logger):
        self.sh = shell
        self.log = log
        self._mirror_cache = None

    @staticmethod
    def major(version):
        """Extract YY.M from YY.M.P or YY.M."""
        parts = version.split(".")
        return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version

    def opnsense_version(self):
        """Current OPNsense version string (pkg revision suffix stripped)."""
        out = self.sh.output("opnsense-version")
        parts = out.split()
        ver = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
        return re.sub(r"_\d+$", "", ver)

    def freebsd_version(self):
        return self.sh.output("uname -r")

    def freebsd_major(self):
        ver = self.freebsd_version()
        return ver.split(".")[0] if ver else ""

    def mirror_url(self):
        """Get pkg mirror base URL (cached)."""
        if self._mirror_cache:
            return self._mirror_cache

        if os.path.exists(self.PKG_CONF):
            try:
                with open(self.PKG_CONF) as f:
                    m = re.search(r"pkg\+https://[^\"]+", f.read())
                if m:
                    url = re.sub(r"/[0-9]{2}\.[0-9][^/]*/.*", "", m.group(0).replace("pkg+", ""))
                    self._mirror_cache = url
                    return url
            except OSError:
                pass

        arch = self.sh.output("uname -m") or "amd64"
        osver = self.freebsd_major()
        self._mirror_cache = f"https://pkg.opnsense.org/FreeBSD:{osver}:{arch}"
        return self._mirror_cache

    def check_url(self, url, timeout=5):
        try:
            with urlopen(url, timeout=timeout) as r:
                return r.status == 200
        except (URLError, OSError, ValueError):
            return False

    def fetch_url(self, url, timeout=5):
        try:
            with urlopen(url, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except (URLError, OSError, ValueError):
            return ""

    def validate_mirror(self, version):
        """Check that a version repo exists on the mirror."""
        url = f"{self.mirror_url()}/{self.major(version)}/latest/meta.conf"
        self.log.info(f"Validating version {version} on mirror...")
        if self.check_url(url):
            self.log.success(f"Version {version} validated on mirror")
            return True
        self.log.error(f"Version {version} not found on pkg mirror")
        self.log.error(f"Checked: {url}")
        return False

    def query_latest(self, minor_only=False):
        """Query available versions via multiple methods. Returns best version or None."""
        current = self.opnsense_version()
        found_major = found_minor = None

        self.log.info(f"Current version: {current or 'unknown'}")
        self.log.info("Querying available versions...")

        # Method 1: configctl firmware
        if shutil.which("configctl"):
            self.log.info("Checking via configctl firmware...")
            # Run firmware check and status in one call to get fresh data
            status = self.sh.output("configctl firmware status", timeout=120, include_stderr=True)
            if status:
                found_major, found_minor = self._parse_firmware(status, current)
                if minor_only:
                    found_major = None

        # Method 2: pkg mirror probing (skip for minor-only)
        if not minor_only and not found_major and current:
            self.log.info("Checking pkg mirrors for major upgrades...")
            found_major = self._probe_mirrors(current)

        # Method 3: opnsense-update -c
        if shutil.which("opnsense-update"):
            self.log.info("Checking via opnsense-update...")
            out = self.sh.output("opnsense-update -c 2>&1")
            if "can be upgraded" in out.lower():
                m = re.search(r"(\d{2}\.\d\S*)", out)
                if m:
                    self.log.success(f"Update available: {m.group(1)}")
                    if not found_minor or found_minor == current:
                        found_minor = m.group(1)

        # Method 4: probe current branch mirror for latest patch (fallback)
        if (not found_minor or found_minor == current) and current:
            patched = self._probe_mirror_minor(current)
            if patched and patched != current:
                found_minor = patched

        # Method 5: changelog directory (skip for minor-only)
        if not minor_only and os.path.isdir(self.CHANGELOG_DIR) and current:
            found_major, found_minor = self._check_changelog(current, found_major, found_minor)

        # Summary
        self._print_version_summary(current, found_major, found_minor)

        # Return best result
        if found_major:
            return found_major
        if found_minor and found_minor != current:
            return found_minor
        return current

    def _print_version_summary(self, current, found_major, found_minor):
        """Print a clear summary of available versions."""
        self.log.header("Available Versions")
        self.log.info(f"Current version:  {current or 'unknown'}")

        has_minor = found_minor and found_minor != current
        has_major = found_major is not None

        if has_minor:
            self.log.success(f"Minor update:     {found_minor}  (use -m to update)")
        else:
            self.log.info("Minor update:     up to date")

        if has_major:
            if has_minor:
                self.log.warning(f"Major upgrade:    {found_major}  (apply minor updates first!)")
            else:
                self.log.success(f"Major upgrade:    {found_major}  (use -t {found_major} to upgrade)")
        else:
            self.log.info("Major upgrade:    none available")

        if not has_minor and not has_major:
            self.log.success("System is up to date")

    def _parse_firmware(self, status, current):
        """Parse configctl firmware status output."""
        major = minor = None
        maj = min_ = ""

        # Try JSON format first (legacy)
        try:
            data = json.loads(status)
            maj = data.get("upgrade_major_version", "")
            min_ = data.get("product_latest", "")
        except json.JSONDecodeError:
            maj = self._regex_field(status, "upgrade_major_version")
            min_ = self._regex_field(status, "product_latest")

        # Parse plain text package upgrade format
        # Look for: opnsense: 26.1.1 -> 26.1.2_5 [OPNsense]
        opnsense_match = re.search(r'^\s*opnsense:\s+[\d.]+(?:_\d+)?\s+->\s+([\d.]+)(?:_\d+)?', status, re.MULTILINE)
        if opnsense_match:
            new_ver = opnsense_match.group(1)
            if new_ver and new_ver != current:
                # Determine if it's a major or minor update based on version comparison
                if current and self.major(new_ver) != self.major(current):
                    maj = new_ver
                else:
                    min_ = new_ver

        if min_ and min_ != current:
            self.log.success(f"Minor update available (firmware): {min_}")
            minor = min_
        if maj:
            self.log.success(f"Major upgrade available (firmware): {maj}")
            major = maj
        return major, minor

    @staticmethod
    def _regex_field(text, field):
        m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', text)
        return m.group(1) if m else ""

    def _probe_mirrors(self, current):
        """Check pkg mirrors for next major version."""
        mirror = self.mirror_url()
        parts = current.split(".")
        year, month = int(parts[0]), int(parts[1].split("_")[0])

        candidates = ([f"{year+1}.1", f"{year+1}.7"] if month >= 7
                      else [f"{year}.7", f"{year+1}.1"])

        for ver in candidates:
            self.log.info(f"Checking mirror for {ver}...")
            if self.check_url(f"{mirror}/{ver}/latest/meta.conf"):
                self.log.success(f"Major upgrade available on pkg mirror: {ver}")
                exact = self._exact_version(mirror, ver)
                if exact:
                    self.log.success(f"Latest patch version: {exact}")
                return exact or ver
        return None

    def _probe_mirror_minor(self, current):
        """Check for latest patch version within the current branch."""
        branch = self.major(current)

        # Method A: pkg remote query — fast, uses locally cached pkg catalog
        out = re.sub(r"_\d+$", "", self.sh.output("pkg rquery '%v' opnsense 2>/dev/null"))
        if out and out != current and self.major(out) == self.major(current):
            self.log.success(f"Minor update available (pkg): {out}")
            return out

        # Method B: pkg search — queries repo directly
        out = self.sh.output("pkg search -q -e -S name opnsense 2>/dev/null | head -1")
        m = re.search(r"(\d{2}\.\d+\.\d+)", out)
        if m and m.group(1) != current and self.major(m.group(1)) == self.major(current):
            self.log.success(f"Minor update available (pkg search): {m.group(1)}")
            return m.group(1)

        # Method C: direct mirror probe via packagesite
        mirror = self.mirror_url()
        self.log.info(f"Checking pkg mirror for latest {branch} patch...")
        exact = self._exact_version(mirror, branch)
        if exact and exact != current:
            self.log.success(f"Minor update available on mirror: {exact}")
            return exact

        return None

    def _exact_version(self, mirror, major_ver):
        """Extract exact package version from repo."""
        pattern = r'"name":"opnsense","version":"([^"]+)"'
        base = f"{mirror}/{major_ver}/latest"

        # Try zstd (.pkg), then xz (.txz)
        for cmd in [
            f"fetch -qo - -T 15 '{base}/packagesite.pkg' 2>/dev/null | zstd -d 2>/dev/null | tar -xf - --to-stdout packagesite.yaml 2>/dev/null",
            f"fetch -qo - -T 15 '{base}/packagesite.txz' 2>/dev/null | tar -xJf - --to-stdout packagesite.yaml 2>/dev/null",
        ]:
            m = re.search(pattern, self.sh.output(cmd))
            if m:
                return m.group(1)

        # Fallback: meta.conf
        m = re.search(r"(\d{2}\.\d+\.\d+)", self.fetch_url(f"{base}/meta.conf"))
        return m.group(1) if m else None

    def _check_changelog(self, current, found_major, found_minor):
        """Scan changelog directory for version hints."""
        versions = set()
        for name in os.listdir(self.CHANGELOG_DIR):
            m = re.match(r"^(\d+\.\d+)", name)
            if m:
                versions.add(m.group(1))
        if not versions:
            return found_major, found_minor

        latest = max(versions, key=lambda v: [int(x) for x in v.split(".")])
        cur_major = self.major(current)
        if latest != cur_major:
            self.log.info(f"Changelog indicates major upgrade: {latest}")
            if not found_major:
                found_major = latest
        elif not found_minor or found_minor == current:
            found_minor = latest
        return found_major, found_minor

    def detect_state(self, target_version):
        """Detect upgrade state for resume without state file."""
        self.log.header("Detecting System State")
        current = self.opnsense_version()
        fb_major = self.freebsd_major()

        self.log.info(f"OPNsense version: {current}")
        self.log.info(f"FreeBSD version: {self.freebsd_version()}")

        # ABI mismatch = base upgraded, packages not
        pkg_abi = self.sh.output("pkg -vv 2>/dev/null")
        m = re.search(r"FreeBSD:(\d+)", pkg_abi)
        if m and fb_major and fb_major != m.group(1):
            self.log.warning(f"Detected: Base upgraded (FreeBSD {fb_major}) but packages built for FreeBSD {m.group(1)}")
            return Stage.FIX_PKG

        # Already on target?
        if target_version and self.major(current) == self.major(target_version):
            self.log.success(f"System already on {self.major(current)}")
            return Stage.COMPLETE

        # Pending updates?
        if "can be upgraded" in self.sh.output("opnsense-update -c 2>&1").lower():
            self.log.info("Detected: Updates available, base/kernel not yet upgraded")
            return Stage.BASE_KERNEL

        # Check if base/kernel already upgraded but packages still on old branch
        # (handles same-FreeBSD-major upgrades, e.g., 25.7->26.1 both on FreeBSD 14)
        if target_version and current and self.major(current) != self.major(target_version):
            self.log.warning(f"Packages on {self.major(current)} but target is {self.major(target_version)}")
            self.log.info("Base/kernel likely already upgraded. Resuming from pkg fix.")
            return Stage.FIX_PKG

        return Stage.INIT


# ==========================================================================
# StateManager — JSON state file
# ==========================================================================

class StateManager:
    """Manages upgrade state persistence."""

    PATH = "/var/db/opnsense-upgrade.state"

    def __init__(self, log: Logger):
        self.log = log

    def save(self, stage, version, dry_run, **flags):
        if dry_run:
            self.log.info(f"[DRY RUN] State checkpoint: {Stage.name(stage)}, Version {version}")
            return
        data = {"stage": stage, "version": version, "timestamp": int(time.time()), **flags}
        with open(self.PATH, "w") as f:
            json.dump(data, f, indent=2)
        self.log.info(f"State saved: {Stage.name(stage)}, Version {version}")

    def load(self):
        """Load state file. Returns dict or None."""
        if not os.path.exists(self.PATH):
            return None
        try:
            with open(self.PATH) as f:
                content = f.read().strip()
            if not content:
                self.clear()
                return None
            return json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            self.log.warning(f"Corrupt state file removed: {e}")
            self.clear()
            return None

    def clear(self):
        if os.path.exists(self.PATH):
            os.remove(self.PATH)
            self.log.info("Upgrade state cleared")

    def exists(self):
        return os.path.exists(self.PATH)


# ==========================================================================
# OPNsenseUpgrade — main orchestrator
# ==========================================================================

class OPNsenseUpgrade:
    """Orchestrates the multi-stage upgrade process."""

    BACKUP_DIR = "/root/config-backups"
    RESUME_SCRIPT = "/etc/rc.local.d/99-opnsense-upgrade-resume"

    def __init__(self, args):
        self.target = None if args.target == "auto" else args.target
        self.minor = args.minor
        self.force = args.force
        self.backup = args.backup
        self.resume = args.resume
        self.clean = args.clean
        self.dry_run = not args.execute
        self.query = args.latest
        self.wants_major = args.target == "auto"
        self.current_stage = Stage.INIT
        self.script_path = os.path.realpath(__file__)

        if args.latest:
            log_prefix = "query"
        elif not args.execute:
            log_prefix = "dryrun"
        else:
            log_prefix = "upgrade"
        self.log = Logger("/var/log/opnsense-upgrades", prefix=log_prefix)
        self.sh = Shell(self.log, self.dry_run)
        self.sys = SystemInfo(self.sh, self.log)
        self.state = StateManager(self.log)

    def confirm(self, prompt):
        if self.force or self.dry_run:
            return True
        try:
            return input(f"\033[1;33m{prompt} (y/N): \033[0m").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def save(self, stage):
        """Save state and update current_stage."""
        self.state.save(stage, self.target, self.dry_run,
                        minor_only=self.minor, force_mode=self.force,
                        log_file=self.log.log_file)
        self.current_stage = stage

    # ------------------------------------------------------------------
    # Upgrade Stages
    # ------------------------------------------------------------------

    def stage_prechecks(self):
        self.log.header(Stage.name(Stage.PRECHECKS))

        avail = self.sh.output("df -m / | awk 'NR==2 {print $4}'")
        avail_mb = int(avail) if avail.isdigit() else 0
        self.log.info(f"Available space: {avail_mb}MB")
        if avail_mb < 2000:
            self.log.error(f"Insufficient disk space. Need 2GB, have {avail_mb}MB")
            return False
        self.log.success("Disk space check passed")

        if self.dry_run:
            self.log.info("[DRY RUN] Would check package database (pkg check -Ba)")
            self.log.info("[DRY RUN] Would check for obsolete Python 3.7 packages")
        else:
            self.log.info("Checking package database integrity (this may take a minute)...")
            if not self.sh.run_tee("pkg check -Ba"):
                self.log.warning("Package database has issues")
                if self.confirm("Attempt to fix package issues?"):
                    self.sh.run_tee("pkg check -da")

            py37 = self.sh.output("pkg query '%n' | grep '^py37-'")
            if py37:
                self.log.warning("Found obsolete Python 3.7 packages")
                if self.confirm("Remove obsolete packages?"):
                    for pkg in py37.split("\n"):
                        if pkg.strip():
                            self.sh.run(f"pkg delete -fy {pkg.strip()}")

        if os.path.exists("/var/run/pkg.lock"):
            if self.sh.check("pgrep -q pkg"):
                self.log.error("pkg process is running. Wait or kill it manually.")
                return False
            self.sh.run("rm -f /var/run/pkg.lock")

        self.log.success("Pre-checks completed")
        self.save(Stage.CLEANUP)
        return True

    def stage_cleanup(self):
        self.log.header(Stage.name(Stage.CLEANUP))
        self.sh.run("pkg autoremove -y")
        self.sh.run("pkg clean -ay")
        self.sh.run("rm -rf /tmp/* /var/tmp/*")
        self.log.success("Cleanup completed")
        self.save(Stage.BACKUP)
        return True

    def stage_backup(self):
        self.log.header(Stage.name(Stage.BACKUP))

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs(self.BACKUP_DIR, exist_ok=True)

        if self.dry_run:
            self.log.info(f"[DRY RUN] Would backup /conf/config.xml")
            self.log.info(f"[DRY RUN] Would save package list")
        elif os.path.exists("/conf/config.xml"):
            shutil.copy2("/conf/config.xml", f"{self.BACKUP_DIR}/config-backup-{ts}.xml")
            self.log.success("Configuration backed up")
            with open(f"{self.BACKUP_DIR}/packages-{ts}.txt", "w") as f:
                f.write(self.sh.output("pkg query '%n-%v'") + "\n")
        else:
            self.log.error("Configuration file not found")
            return False

        self.log.success("Backup completed")
        self.save(Stage.BASE_KERNEL)
        return True

    def stage_base_kernel(self):
        self.log.header(Stage.name(Stage.BASE_KERNEL))
        if self.minor:
            if self.dry_run:
                self.log.info("[DRY RUN] Would run: opnsense-update -bk")
                self.log.info("[DRY RUN] Would reboot if base/kernel changed")
                self.save(Stage.PACKAGES)
                return True
            self.log.info("Updating base and kernel for minor release...")
            ok, out = self.sh.run_tee_output("opnsense-update -bk")
            if not ok:
                self.log.warning("Base/kernel update reported errors, continuing...")
            self.log.success("Base/kernel update completed")
            self.save(Stage.PACKAGES)
            if "please reboot" in out.lower():
                self._reboot(Stage.BASE_KERNEL, Stage.PACKAGES)
            return True

        self.log.warning(f"Upgrading base and kernel to {self.target}")
        self.log.warning("This will require a reboot")
        if not self.confirm("Proceed with base/kernel upgrade?"):
            self.log.info("Upgrade cancelled")
            self.state.clear()
            return False

        if self.dry_run:
            self.log.info("[DRY RUN] Would run: opnsense-update -ubkf")
            self.log.info("[DRY RUN] Would save state and trigger reboot")
            self.save(Stage.FIX_PKG)
        else:
            if not self.sh.run_tee("opnsense-update -ubkf"):
                self.log.error("Base/kernel update failed")
                return False
            self.log.success("Base/kernel update completed")
            self.save(Stage.FIX_PKG)
            self._reboot(Stage.BASE_KERNEL, Stage.FIX_PKG)
        return True

    def stage_fix_pkg(self):
        self.log.header(Stage.name(Stage.FIX_PKG))
        self.log.info("Checking pkg compatibility with new base...")

        if self.dry_run:
            self.log.info("[DRY RUN] Would check pkg compatibility")
            self.log.info("[DRY RUN] Would reinstall pkg if incompatible")
            self.save(Stage.PACKAGES)
            return True

        # Test pkg thoroughly — pkg -v may pass but pkg update can still segfault
        if self.sh.check("pkg -v") and self.sh.check("pkg query '%n' opnsense"):
            self.log.success("pkg is working correctly")
        else:
            self.log.warning("pkg is incompatible with new base - reinstalling")
            if not (self.sh.run_tee("pkg-static install -fy pkg") and self.sh.check("pkg -v")):
                self.log.warning("Attempting bootstrap...")
                if not self.sh.run_tee("opnsense-bootstrap -y"):
                    self.log.error("Bootstrap failed")
                    return False
                self.log.success("Bootstrap successful")

        # Always force-reinstall pkg after base upgrade to prevent segfaults
        self.log.info("Reinstalling pkg to ensure full compatibility...")
        self.sh.run("pkg-static install -fy pkg")

        self.save(Stage.PACKAGES)
        return True

    def stage_packages(self):
        self.log.header(Stage.name(Stage.PACKAGES))
        self.log.info(f"Upgrading packages to {self.target}...")

        if self.dry_run:
            if self.minor:
                self.log.info("[DRY RUN] Would run: opnsense-update -p")
            else:
                target_major = self.sys.major(self.target)
                self.log.info(f"[DRY RUN] Would switch pkg repo to {target_major}")
                self.log.info("[DRY RUN] Would run: pkg update -f")
                self.log.info("[DRY RUN] Would run: pkg upgrade -fy")
                self.log.info("[DRY RUN] Would run: opnsense-update")
        elif self.minor:
            if not self.sh.run_tee("opnsense-update -p"):
                self.log.warning("Package update reported errors, continuing...")
        else:
            # Switch pkg repo to target version branch
            target_major = self.sys.major(self.target)
            if not self._switch_pkg_repo(target_major):
                return False

            # Force refresh package catalog
            if not self.sh.run("pkg update -f"):
                self.log.warning("pkg update failed, attempting anyway...")

            # Upgrade all packages to new branch versions
            self.log.info("Upgrading all packages to new branch...")
            if not self.sh.run_tee("pkg upgrade -fy"):
                self.log.warning("pkg upgrade reported errors, continuing...")

            # Finalize with opnsense-update
            self.log.info("Finalizing with opnsense-update...")
            if not self.sh.run_tee("opnsense-update"):
                self.log.warning("opnsense-update reported errors, checking...")

            # Verify the upgrade actually worked
            ver = self.sys.opnsense_version()
            if not ver or self.sys.major(ver) != self.sys.major(self.target):
                self.log.error(f"Upgrade failed — still on {ver}")
                return False
            self.log.success(f"Upgraded to {ver}")

        self.log.success("Package upgrade completed")
        self.save(Stage.POST_VERIFY)
        return True

    def _switch_pkg_repo(self, target_major):
        """Switch OPNsense.conf repo URL to target version branch."""
        conf = SystemInfo.PKG_CONF
        if not os.path.exists(conf):
            self.log.error(f"Pkg repo config not found: {conf}")
            return False

        try:
            with open(conf) as f:
                content = f.read()
        except OSError as e:
            self.log.error(f"Failed to read {conf}: {e}")
            return False

        # Find current version in URL (e.g., /25.7/ -> /26.1/)
        new_content = re.sub(r"/\d{2}\.\d+/", f"/{target_major}/", content)
        if new_content == content:
            self.log.info(f"Repo already pointing to {target_major}")
            return True

        self.log.info(f"Switching pkg repo to {target_major}...")
        try:
            with open(conf, "w") as f:
                f.write(new_content)
            self.log.success(f"Pkg repo switched to {target_major}")
            return True
        except OSError as e:
            self.log.error(f"Failed to update {conf}: {e}")
            return False

    def stage_post_verify(self):
        self.log.header(Stage.name(Stage.POST_VERIFY))
        self.log.info(f"Current version: {self.sys.opnsense_version()}")
        self.log.info(f"FreeBSD version: {self.sys.freebsd_version()}")

        if self.dry_run:
            self.log.info("[DRY RUN] Would verify package database")
            self.log.info("[DRY RUN] Would check critical services")
        else:
            self.log.info("Verifying package database integrity (this may take a minute)...")
            if self.sh.run_tee("pkg check -Ba"):
                self.log.success("Package database is healthy")
            else:
                self.log.warning("Package database has issues")

            for svc in ("configd", "syslog-ng"):
                if self.sh.check(f"service {svc} status"):
                    self.log.success(f"{svc} is running")
                else:
                    self.log.warning(f"{svc} is not running")

        self.log.success("Post-verification completed")
        self.save(Stage.COMPLETE)

        if self.dry_run:
            self.log.info("[DRY RUN] Would check if reboot is required")
        elif os.path.exists("/var/run/reboot_required"):
            self.log.warning("Final reboot recommended")
            if self.confirm("Reboot now to complete upgrade?"):
                self._do_reboot("OPNsense upgrade complete")
        return True

    def stage_complete(self):
        if self.dry_run:
            self.log.header("Dry Run Complete")
            self.log.success("Dry run finished - no changes were made")
            self.log.info(f"Current version: {self.sys.opnsense_version()}")
            self.log.info("Review the output above, then run with -x to execute")
        else:
            self.log.header("Upgrade Complete!")
            self.log.success("OPNsense upgrade completed successfully")
            self.log.info(f"Current version: {self.sys.opnsense_version()}")
            self.log.info(f"FreeBSD version: {self.sys.freebsd_version()}")
            self.state.clear()
            self._remove_auto_resume()
            self.log.success("All upgrade stages completed")

    # ------------------------------------------------------------------
    # Reboot and auto-resume
    # ------------------------------------------------------------------

    def _reboot(self, _current, next_stage):
        self.log.header("Reboot Required")
        self.log.warning("System needs to reboot to continue upgrade")
        self.log.info(f"After reboot: Will continue with {Stage.name(next_stage)}")

        if self.dry_run:
            self.log.info("[DRY RUN] Would set up auto-resume and reboot")
            return

        self._setup_auto_resume()
        name = os.path.basename(self.script_path)
        self.log.info("Auto-resume will run ~10 seconds after boot")
        self.log.info(f"To check progress:  tail -f /var/log/opnsense-upgrade-resume.log")
        self.log.info(f"To resume manually: ./{name} -x -r")
        if self.confirm("Reboot now to continue upgrade?"):
            self._do_reboot(f"OPNsense upgrade - Stage: {Stage.name(next_stage)}")
        else:
            self.log.warning("Reboot postponed. Run with -r to resume after manual reboot.")
            sys.exit(0)

    def _do_reboot(self, reason):
        self.log.info("Rebooting system...")
        os.sync()
        time.sleep(2)
        os.system(f"/sbin/shutdown -r now '{reason}'")
        sys.exit(0)

    def _setup_auto_resume(self):
        script = (
            f"#!/bin/sh\n"
            f"STATE_FILE=\"{self.state.PATH}\"\n"
            f"SCRIPT_PATH=\"{self.script_path}\"\n"
            f"if [ -f \"${{STATE_FILE}}\" ] && [ -f \"${{SCRIPT_PATH}}\" ]; then\n"
            f"    logger -t opnsense-upgrade \"Auto-resuming upgrade after reboot\"\n"
            f"    sleep 10\n"
            f"    \"${{SCRIPT_PATH}}\" -x -r >> /var/log/opnsense-upgrade-resume.log 2>&1 &\n"
            f"fi\n"
        )
        os.makedirs(os.path.dirname(self.RESUME_SCRIPT), exist_ok=True)
        with open(self.RESUME_SCRIPT, "w") as f:
            f.write(script)
        os.chmod(self.RESUME_SCRIPT, 0o755)
        self.log.success("Auto-resume configured")

    def _remove_auto_resume(self):
        if os.path.exists(self.RESUME_SCRIPT):
            os.remove(self.RESUME_SCRIPT)
            self.log.info("Auto-resume removed")

    def _check_pending_minor(self, current):
        """Check if minor updates are available. Returns pending version or None."""
        # Check via configctl firmware
        if shutil.which("configctl"):
            status = self.sh.output("configctl firmware status", timeout=120, include_stderr=True)
            if status:
                _, minor = self.sys._parse_firmware(status, current)
                if minor and minor != current:
                    return minor

        # Check via opnsense-update -c
        if shutil.which("opnsense-update"):
            out = self.sh.output("opnsense-update -c 2>&1")
            if "can be upgraded" in out.lower():
                m = re.search(r"(\d{2}\.\d\S*)", out)
                if m and m.group(1) != current and self.sys.major(m.group(1)) == self.sys.major(current):
                    return m.group(1)

        return None

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    def run_upgrade(self):
        mode = " [DRY RUN]" if self.dry_run else ""
        self.log.header(f"OPNsense Enhanced Upgrade v1.0{mode}")
        self.log.info(f"Target version: {self.target}")
        self.log.info(f"Starting from stage: {Stage.name(self.current_stage)}")

        handlers = {
            Stage.INIT: self.stage_prechecks, Stage.PRECHECKS: self.stage_prechecks,
            Stage.CLEANUP: self.stage_cleanup, Stage.BACKUP: self.stage_backup,
            Stage.BASE_KERNEL: self.stage_base_kernel, Stage.FIX_PKG: self.stage_fix_pkg,
            Stage.PACKAGES: self.stage_packages, Stage.POST_VERIFY: self.stage_post_verify,
        }

        for stage in Stage.ORDER:
            if stage < self.current_stage:
                continue
            if stage == Stage.COMPLETE:
                self.stage_complete()
                return
            if not handlers[stage]():
                sys.exit(1)

    def run(self):
        os.makedirs(self.BACKUP_DIR, exist_ok=True)
        if os.getuid() != 0:
            print("This script must be run as root")
            sys.exit(1)

        self.log.info(f"Script started at: {datetime.now()}")
        name = os.path.basename(self.script_path)

        # -l: query version
        if self.query:
            self.sys.query_latest()
            return

        # -c: clean state
        if self.clean:
            self.state.clear()
            self._remove_auto_resume()
            self.log.success("State cleaned.")
            return

        # -b standalone: just backup and exit
        if self.backup and not self.minor and not self.target and not self.resume:
            self._run_backup()
            return

        # -r: resume
        if self.resume:
            self.log.info("Resume mode requested")
            saved = self.state.load()
            if saved:
                self.current_stage = saved["stage"]
                self.target = saved["version"]
                self.minor = saved.get("minor_only", False)
                self.force = saved.get("force_mode", False)
            else:
                self.log.warning("No saved state found. Detecting system state...")
                detected = self.sys.detect_state(self.target)
                if detected == Stage.COMPLETE:
                    self.log.success("System already fully upgraded")
                    return
                if detected == Stage.INIT:
                    # No state detected yet — try auto-detecting target and re-check
                    if not self.target:
                        self.target = self.sys.query_latest()
                    if self.target:
                        current = self.sys.opnsense_version()
                        if current and self.sys.major(current) != self.sys.major(self.target):
                            self.log.warning(f"Packages on {self.sys.major(current)} but {self.sys.major(self.target)} available")
                            self.log.info("Base/kernel likely already upgraded. Resuming from pkg fix.")
                            detected = Stage.FIX_PKG
                    if detected == Stage.INIT:
                        self.log.info("No incomplete upgrade detected. System is in normal state.")
                        self.log.info("Nothing to resume. Use -t VERSION or run without -r to start a new upgrade.")
                        return
                if not self.target:
                    self.target = self.sys.query_latest()
                    if not self.target:
                        self.log.error("Cannot determine target version. Specify with -t VERSION")
                        sys.exit(1)
                    self.log.info(f"Auto-detected target version: {self.target}")
                self.current_stage = detected

            self.log.info(f"Resuming from stage: {Stage.name(self.current_stage)}")
            self.run_upgrade()
            return

        # Auto-detect version if not specified
        if not self.target:
            # -t without version: user wants a major upgrade, auto-detect it
            wants_major = self.wants_major
            self.log.info("No target version specified, querying latest...")
            self.target = self.sys.query_latest(minor_only=self.minor)
            if not self.target:
                self.log.error("Could not auto-detect target version. Specify with -t VERSION")
                sys.exit(1)
            current = self.sys.opnsense_version()
            if self.target == current:
                self.log.success(f"System is already on latest version ({self.target})")
                return
            self.log.info(f"Auto-detected target version: {self.target}")

            # If -t was used (wants major) but only minor found, tell the user
            if wants_major and current and self.sys.major(self.target) == self.sys.major(current):
                self.log.warning("No major upgrade available")
                self.log.info(f"Only a minor update was found: {current} -> {self.target}")
                self.log.info(f"Use -m to perform the minor update instead: {name} -m")
                return

            # If -m is used, verify the target is a minor update
            if self.minor and current and self.sys.major(self.target) != self.sys.major(current):
                self.log.error(f"Target {self.target} is a major upgrade, not a minor update")
                self.log.error(f"Remove -m flag to perform major upgrade, or use -t to specify minor version")
                sys.exit(1)

            # Auto-detect minor mode if target is in the same branch
            if not self.minor and current and self.sys.major(self.target) == self.sys.major(current):
                self.log.info("Target is within current branch, using minor update mode")
                self.minor = True

        # Auto-detect minor mode when target is explicitly specified in same branch
        if not self.minor and self.target:
            current = self.sys.opnsense_version()
            if current and self.sys.major(self.target) == self.sys.major(current):
                self.log.info("Target is within current branch, using minor update mode")
                self.minor = True

        # Validate on mirror
        if self.minor:
            cur = self.sys.opnsense_version()
            branch = self.sys.major(cur) if cur else ""
            if branch and not self.sys.validate_mirror(branch):
                sys.exit(1)
        elif self.target:
            cur = self.sys.opnsense_version()
            if self.target == cur:
                self.log.success(f"System is already on version {self.target}")
                return
            if not self.sys.validate_mirror(self.target):
                self.log.info("Use -l to see available versions")
                sys.exit(1)

        # Block major upgrade if minor updates are pending
        if not self.minor and self.target:
            current = self.sys.opnsense_version()
            if current and self.sys.major(current) != self.sys.major(self.target):
                pending_minor = self._check_pending_minor(current)
                if pending_minor:
                    self.log.error(f"Minor update available: {current} -> {pending_minor}")
                    self.log.error("OPNsense requires all minor updates before a major upgrade")
                    self.log.error(f"Run minor update first: {name} -x -m -b")
                    sys.exit(1)

        # Check for existing in-progress upgrade
        if self.state.exists():
            saved = self.state.load()
            if saved:
                self.log.warning("Found existing upgrade in progress!")
                self.log.warning(f"Stage: {Stage.name(saved['stage'])}, Version: {saved['version']}")
                print(f"\nOptions:\n  Resume: {name} -r\n  Clean:  {name} -c && {name} -t {self.target} -b")
                sys.exit(1)

        # Confirm before starting
        current = self.sys.opnsense_version()
        is_minor = self.minor or (current and self.target and self.sys.major(current) == self.sys.major(self.target))
        desc = (f"minor update from {current} to {self.target}" if is_minor
                else f"major upgrade from {current} to {self.target}")
        if self.dry_run:
            self.log.info(f"Starting dry run: {desc}")
        elif not self.confirm(f"About to perform {desc}. Proceed?"):
            self.log.info("Upgrade cancelled by user")
            return

        self.current_stage = Stage.INIT
        self.run_upgrade()

    def _run_backup(self):
        """Standalone backup: backup config and package list, then exit."""
        self.log.header("Configuration Backup")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs(self.BACKUP_DIR, exist_ok=True)

        if not os.path.exists("/conf/config.xml"):
            self.log.error("Configuration file /conf/config.xml not found")
            return

        config_path = f"{self.BACKUP_DIR}/config-backup-{ts}.xml"
        pkg_path = f"{self.BACKUP_DIR}/packages-{ts}.txt"

        shutil.copy2("/conf/config.xml", config_path)
        self.log.success(f"Config backed up: {config_path}")

        with open(pkg_path, "w") as f:
            f.write(self.sh.output("pkg query '%n-%v'") + "\n")
        self.log.success(f"Package list saved: {pkg_path}")

        self.log.info("")
        self.log.info("Backup contents:")
        self.log.info(f"  Settings (XML):   {config_path}")
        self.log.info(f"  Package list:     {pkg_path}")
        self.log.info(f"  Original config:  /conf/config.xml")
        self.log.info("")
        self.log.info("To restore settings, copy the XML backup back:")
        self.log.info(f"  cp {config_path} /conf/config.xml")

    def _print_log_location(self):
        """Print log file location at the end of execution."""
        self.log.info(f"Log file: {self.log.log_file}")


# ==========================================================================
# CLI entry point
# ==========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Enhanced stateful OPNsense upgrade with automatic recovery.",
        epilog="All runs are dry runs by default. Use -x to actually execute.\n"
               "Run with -l to query available versions before upgrading.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-t", "--target", metavar="VERSION", nargs="?", const="auto",
                        help="Target version (e.g., 26.1). Auto-detects if version omitted")
    parser.add_argument("-m", "--minor", action="store_true",
                        help="Minor update only (within current branch)")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Force mode (no confirmations)")
    parser.add_argument("-b", "--backup", action="store_true",
                        help="Standalone: backup config and package list, then exit")
    parser.add_argument("-r", "--resume", action="store_true",
                        help="Resume from saved state (after reboot or interruption)")
    parser.add_argument("-c", "--clean", action="store_true",
                        help="Clean state and start fresh")
    parser.add_argument("-x", "--execute", action="store_true",
                        help="Execute for real (default is dry run)")
    parser.add_argument("-l", "--latest", action="store_true",
                        help="Query and display the latest available version")

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    upgrader = OPNsenseUpgrade(args)
    try:
        upgrader.run()
    finally:
        upgrader._print_log_location()


if __name__ == "__main__":
    main()
