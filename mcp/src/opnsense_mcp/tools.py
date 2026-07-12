"""MCP tool definitions for OPNsense."""

import re
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

from .api import OPNsenseAPI, batch_summary
from .config import Config

# Tool definitions (name, description, input schema)
TOOLS = [
    Tool(
        name="get_version",
        description="Get current OPNsense version, FreeBSD base, and next available major version.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="check_updates",
        description="Check for available minor updates and major upgrades, and report reboot status.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="upgrade_status",
        description="Monitor an in-progress firmware update or upgrade.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="get_changelog",
        description="Show the changelog for a specific OPNsense version.",
        inputSchema={
            "type": "object",
            "properties": {
                "version": {"type": "string", "description": "Version string, e.g. '26.1.2' or '26.7'"},
            },
            "required": ["version"],
        },
    ),
    Tool(
        name="list_packages",
        description="List installed OPNsense packages with versions.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="system_info",
        description="Get system uptime, load average, and top processes.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="run_update",
        description="Trigger a minor firmware update. Ask the user to confirm before calling this.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="run_upgrade",
        description="Trigger a major version upgrade. Ask the user to confirm before calling this.",
        inputSchema={
            "type": "object",
            "properties": {
                "version": {"type": "string", "description": "Target version, e.g. '26.7'. Leave empty to auto-detect."},
            },
            "required": [],
        },
    ),
    Tool(
        name="reboot",
        description="Reboot the OPNsense firewall. Ask the user to explicitly confirm before calling this.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="pre_upgrade_check",
        description=(
            "Run a pre-upgrade health assessment before triggering any update or upgrade. "
            "Checks: pending minor updates (must be applied before a major upgrade), "
            "reboot status (genuine vs stale), in-progress upgrade detection, "
            "and next major version availability. Returns a go/no-go verdict."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]


def _repo_error(status: dict) -> str | None:
    """Return status_msg when it signals an unreachable/missing pkg repo, else None.

    An unreachable repo (e.g. a third-party SunnyValley/Zenarmor mirror) makes pkg
    hang on the catalog fetch before installing anything. Matches the error signature
    ("repositor" + an error word) without false-flagging benign messages like
    "no updates available on the selected mirror".
    """
    msg = status.get("status_msg", "") or ""
    low = msg.lower()
    if "repositor" in low and any(
        w in low for w in ("could not", "not found", "unable", "fail", "unreachable", "error")
    ):
        return msg
    return None


def _version_state(status: dict) -> dict:
    """Firmware-version fields shared by the update/upgrade/check handlers.

    has_minor is True when a minor update is pending (status 'update', or a
    product_latest that differs from the suffix-stripped current version).
    """
    product = status.get("product", {})
    current = product.get("product_version", "")
    latest_minor = product.get("product_latest", "")
    current_base = current.split("_")[0] if current else ""
    fw_status = status.get("status", "none")
    has_minor = fw_status == "update" or bool(
        latest_minor and current_base and latest_minor != current_base
    )
    return {
        "current": current,
        "latest_minor": latest_minor,
        "next_major": product.get("CORE_NEXT", ""),
        "fw_status": fw_status,
        "has_minor": has_minor,
    }


def _package_lines(batch: dict) -> list[str]:
    """One indented line per pending package: name, version change, repo, action."""
    lines = []
    for p in batch["packages"]:
        if p["new_version"]:
            change = f"{p['current_version']} -> {p['new_version']}"
        else:
            change = p["current_version"]
        action = "" if p["action"] == "upgrade" else f" [{p['action']}]"
        lines.append(f"  {p['name']:<24} {change}  ({p['repository']}){action}")
    return lines


def _update_lines(vs: dict, batch: dict) -> list[str]:
    """Availability lines for check_updates.

    Distinguishes a real OPNsense version bump from a batch where the version
    stays put (e.g. a plugin-only SunnyValley/Zenarmor release, which the bare
    'Minor update available: <version>' wording used to misrepresent as an
    OPNsense point release — observed live with os-sensei 2.6.1, 2026-07-12).
    """
    current = vs["current"]
    latest_minor = vs["latest_minor"]
    current_base = current.split("_")[0] if current else ""
    version_bump = bool(latest_minor and current_base and latest_minor != current_base)

    if batch["packages"]:
        n = len(batch["packages"])
        if version_bump:
            lines = [f"Minor update available: {latest_minor} ({n} packages)"]
        elif batch["has_core"]:
            lines = [f"Package updates available: {n} (OPNsense version stays {current})"]
        else:
            lines = [
                f"Package updates available: {n} "
                f"(third-party only, OPNsense stays {current})"
            ]
        lines.extend(_package_lines(batch))
        return lines
    if vs["has_minor"]:
        # Stale daemon cache: product_latest is ahead but no package list yet.
        return [f"Minor update available: {latest_minor}"]
    return ["Minor update: up to date"]


def _repo_blocked_text(status_msg: str) -> str:
    """Guidance shown when a write tool refuses because a repo is unreachable."""
    return (
        "Blocked: a configured pkg repository is unreachable.\n"
        f"  {status_msg}\n\n"
        "pkg fetches every repo's catalog before installing, so this would hang. "
        "Disable the offending third-party repo on the firewall (e.g. "
        "SunnyValley/Zenarmor), then retry:\n"
        "  mv /usr/local/etc/pkg/repos/SunnyValley.conf{,.disabled}"
    )


def register_tools(server: Server, config: Config) -> OPNsenseAPI:
    api = OPNsenseAPI(config)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        def text(s: str) -> list[TextContent]:
            return [TextContent(type="text", text=s)]

        def check_writable():
            if config.read_only:
                raise ValueError("MCP server is in read-only mode. Set OPNSENSE_READ_ONLY=false to enable write operations.")

        try:
            if name == "get_version":
                status = api.firmware_status()
                product = status.get("product", {})
                lines = [
                    f"OPNsense version:  {product.get('product_version', 'unknown')}",
                    f"FreeBSD base:      {status.get('os_version', 'unknown')}",
                    f"Product series:    {product.get('product_series', 'unknown')}",
                    f"Next major:        {product.get('CORE_NEXT') or 'none available'}",
                    f"Repository:        {product.get('product_repos', 'unknown')}",
                ]
                # Supplement with base/kernel package versions from firmware_info
                try:
                    info = api.firmware_info()
                    pkgs = {p["name"]: p["version"] for p in info.get("package", [])
                            if p.get("installed") == "1" and p.get("name") in ("base", "kernel")}
                    if pkgs.get("base"):
                        lines.append(f"Base package:      {pkgs['base']}")
                    if pkgs.get("kernel"):
                        lines.append(f"Kernel package:    {pkgs['kernel']}")
                except Exception:
                    pass
                return text("\n".join(lines))

            elif name == "check_updates":
                status = api.firmware_status()
                vs = _version_state(status)
                current = vs["current"] or "unknown"
                next_major = vs["next_major"]
                fw_status = vs["fw_status"]
                status_msg = status.get("status_msg", "")

                lines = [f"Current version: {current}"]
                lines.extend(_update_lines(vs, batch_summary(status)))

                if fw_status == "upgrade":
                    lines.append(f"Major upgrade available: {next_major} (use run_upgrade to upgrade)")
                elif next_major:
                    lines.append(f"Next major version: {next_major} (planned, not yet released)")
                else:
                    lines.append("Major upgrade: none available")

                lines.append(f"Status: {status_msg or 'no updates available'}")
                if _repo_error(status):
                    lines.append(
                        "WARNING: a pkg repository is unreachable -- update/upgrade would hang "
                        "on the catalog fetch. Run pre_upgrade_check for details."
                    )

                reboot_info = api.check_needs_reboot()
                if reboot_info["needs_reboot"]:
                    lines.append(f"\nReboot status: {reboot_info['explanation']}")
                else:
                    lines.append("\nReboot status: not required")

                return text("\n".join(lines))

            elif name == "upgrade_status":
                data = api.firmware_upgradestatus()
                log_lines = data.get("log", "")
                fw_status = data.get("status", "unknown")
                pkg_progress = data.get("progress", "")
                lines = [f"Status: {fw_status}"]
                if pkg_progress:
                    lines.append(f"Progress: {pkg_progress}")
                if log_lines:
                    lines.append("\nLog (last 20 lines):")
                    lines.extend(log_lines.strip().splitlines()[-20:])
                # A "running" status with an unreachable repo is the classic stall:
                # pkg blocks on the catalog fetch and the log stops advancing.
                if fw_status == "running":
                    # Best-effort: a wedged pkg can also wedge the firmware API, and
                    # this warning must not cost the status/log report already gathered.
                    try:
                        rerr = _repo_error(api.firmware_status())
                    except Exception:
                        rerr = None
                    if rerr:
                        lines.append(
                            f"\nWARNING: a pkg repository is unreachable ({rerr}). The run is "
                            "likely stalled on the catalog fetch. If the log is not advancing, it "
                            "may need manual recovery on the firewall: kill the stuck pkg process, "
                            "disable the offending repo, then retry."
                        )
                return text("\n".join(lines))

            elif name == "get_changelog":
                version = arguments.get("version", "")
                data = api.firmware_changelog(version)
                html = data.get("html", "") or data.get("changelog", "")
                if not html:
                    return text(f"No changelog found for version {version}.")
                clean = re.sub(r"<[^>]+>", "", html).strip()
                clean = re.sub(r"\n{3,}", "\n\n", clean)
                limit = 4000
                if len(clean) > limit:
                    clean = clean[:limit].rstrip() + (
                        f"\n\n... [truncated {len(clean) - limit} more characters; "
                        "see the full changelog in the OPNsense web UI]"
                    )
                return text(f"Changelog for {version}:\n\n{clean}")

            elif name == "list_packages":
                # firmware_info (POST) forces a fresh fetch; fall back to cached status if needed
                try:
                    data = api.firmware_info()
                    all_pkgs = data.get("package") or data.get("all_packages") or data.get("packages") or []
                except Exception:
                    all_pkgs = []
                if not all_pkgs:
                    data = api.firmware_status()
                    all_pkgs = data.get("all_packages", [])
                if not all_pkgs:
                    return text("Package list not available. The firmware daemon may still be initializing; try again shortly.")
                installed = [p for p in all_pkgs if p.get("installed") == "1"]
                if not installed:
                    installed = all_pkgs  # fallback: list returned without installed flag
                lines = [f"{p.get('name', '?'):<40} {p.get('version', '?')}" for p in installed]
                return text(f"{len(lines)} packages installed:\n\n" + "\n".join(lines))

            elif name == "system_info":
                data = api.system_activity()
                headers = data.get("headers", [])
                header_str = headers[0] if headers else "unavailable"
                processes = data.get("details", [])[:10]
                lines = [f"System: {header_str.strip()}"]

                def _first(d, *keys):
                    """First non-empty value among candidate keys (API key names vary)."""
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, ""):
                            return v
                    return ""

                if processes:
                    lines.append("\nTop processes:")
                    # getActivity (top -aHSTn thread mode) exposes WCPU and RES,
                    # not %CPU/%MEM — fall back through the names that actually appear.
                    lines.append(f"  {'PID':<8} {'USERNAME':<12} {'CPU%':<8} {'RES':<8} COMMAND")
                    for p in processes:
                        cpu = _first(p, "%CPU", "WCPU", "CPU", "C")
                        mem = _first(p, "%MEM", "MEM", "RES", "SIZE")
                        lines.append(
                            f"  {_first(p, 'PID'):<8} {_first(p, 'USERNAME'):<12} "
                            f"{cpu:<8} {mem:<8} {_first(p, 'COMMAND')[:40]}"
                        )
                return text("\n".join(lines))

            elif name == "run_update":
                check_writable()
                # Block if an upgrade/update is already running
                running = api.firmware_upgradestatus()
                if running.get("status") == "running":
                    return text("An upgrade/update is already in progress. Use upgrade_status to monitor it.")
                # Block if already up to date — use same two-condition logic as check_updates
                # to handle stale firmware daemon cache (status="none" but product_latest > product_version)
                status = api.firmware_status()
                # Refuse if a repo is unreachable — triggering would hang on the catalog fetch
                rerr = _repo_error(status)
                if rerr:
                    return text(_repo_blocked_text(rerr))
                if not _version_state(status)["has_minor"]:
                    return text("System is already up to date. No update needed.")
                batch = batch_summary(status)
                result = api.firmware_update()
                msg = result.get("msg", "") or result.get("status", str(result))
                lines = [f"Update triggered: {msg}"]
                if batch["packages"]:
                    lines.append("\nApplying:")
                    lines.extend(_package_lines(batch))
                lines.append("\nUse upgrade_status to monitor progress.")
                return text("\n".join(lines))

            elif name == "run_upgrade":
                check_writable()
                # Block if an upgrade/update is already running
                running = api.firmware_upgradestatus()
                if running.get("status") == "running":
                    return text("An upgrade/update is already in progress. Use upgrade_status to monitor it.")
                # Check firmware status before proceeding
                status = api.firmware_status()
                # Refuse if a repo is unreachable — triggering would hang on the catalog fetch
                rerr = _repo_error(status)
                if rerr:
                    return text(_repo_blocked_text(rerr))
                vs = _version_state(status)
                current, latest_minor = vs["current"], vs["latest_minor"]
                next_major, fw_status = vs["next_major"], vs["fw_status"]

                # Block if the major upgrade is not actually available on the mirror yet
                if fw_status != "upgrade":
                    if next_major:
                        return text(
                            f"Major upgrade to {next_major} is not yet available on the mirror.\n\n"
                            f"CORE_NEXT shows {next_major} as the next planned version, but OPNsense has "
                            f"not released it yet. Check back after the release date."
                        )
                    return text("No major upgrade is available. System is up to date.")

                # Block if minor updates are pending (must apply minor updates before major upgrade)
                if vs["has_minor"]:
                    return text(
                        f"Minor update pending: {current} -> {latest_minor}\n\n"
                        "OPNsense requires all minor updates to be applied before a major upgrade. "
                        "Run run_update first, then retry the major upgrade."
                    )
                version = arguments.get("version", "")
                result = api.firmware_upgrade(version)
                msg = result.get("msg", "") or result.get("status", str(result))
                return text(f"Upgrade triggered: {msg}\n\nUse upgrade_status to monitor. The system will reboot during the upgrade.")

            elif name == "reboot":
                check_writable()
                result = api.firmware_reboot()
                msg = result.get("msg", "") or result.get("status", str(result))
                return text(f"Reboot initiated: {msg}")

            elif name == "pre_upgrade_check":
                issues = []
                lines = ["Pre-Upgrade Assessment", "=" * 40, ""]

                # Firmware status (single call, reused below)
                status = api.firmware_status()
                vs = _version_state(status)
                current = vs["current"] or "unknown"
                latest_minor = vs["latest_minor"]
                next_major = vs["next_major"]
                fw_status = vs["fw_status"]
                has_minor = vs["has_minor"]

                lines.append(f"Current version: {current}")

                # Repository/mirror reachability — an unreachable repo (e.g. a third-party
                # Zenarmor/SunnyValley mirror) makes pkg hang on the catalog fetch. OPNsense
                # surfaces this in status_msg; flag it so the verdict reflects the real risk.
                rerr = _repo_error(status)
                if rerr:
                    lines.append(f"Repository:      UNREACHABLE -- {rerr}")
                    issues.append(
                        f"A configured pkg repository is unreachable ({rerr}). "
                        "pkg will hang on the catalog fetch. Disable the offending "
                        "third-party repo (e.g. SunnyValley/Zenarmor) before updating."
                    )

                # Minor updates pending? Distinguish a version bump from a plugin-only
                # batch (OPNsense version unchanged) — both must be applied before a
                # major upgrade, but they read very differently.
                batch = batch_summary(status)
                current_base = current.split("_")[0]
                pending_line = (
                    f"Minor update:    {latest_minor} -- PENDING "
                    "(must apply before major upgrade)"
                )
                pending_issue = (
                    f"Minor update pending ({current} -> {latest_minor}). "
                    "Run run_update first."
                )
                if has_minor and latest_minor and latest_minor != current_base:
                    lines.append(pending_line)
                    lines.extend(_package_lines(batch))
                    issues.append(pending_issue)
                elif has_minor and batch["packages"]:
                    n = len(batch["packages"])
                    scope = "" if batch["has_core"] else "third-party only, "
                    lines.append(
                        f"Package updates: {n} pending ({scope}OPNsense stays {current})"
                    )
                    lines.extend(_package_lines(batch))
                    names = ", ".join(p["name"] for p in batch["packages"][:5])
                    issues.append(
                        f"Package updates pending ({names}). Run run_update first."
                    )
                elif has_minor:
                    lines.append(pending_line)
                    issues.append(pending_issue)
                else:
                    lines.append("Minor update:    up to date")

                # Major upgrade available?
                if fw_status == "upgrade":
                    if has_minor:
                        lines.append(f"Major upgrade:   {next_major} -- available but blocked by pending minor update")
                    else:
                        lines.append(f"Major upgrade:   {next_major} -- available and ready")
                elif next_major:
                    lines.append(f"Major upgrade:   {next_major} -- planned, not yet released on mirror")
                else:
                    lines.append("Major upgrade:   none available")

                # Reboot status
                reboot_info = api.check_needs_reboot()
                if reboot_info.get("pending_update_reboot"):
                    # The pending batch will reboot the system when applied — expected
                    # behavior, not a blocker. Never list it as an issue.
                    lines.append(
                        "Reboot:          pending update will reboot the system when "
                        "applied (not a blocker)"
                    )
                elif reboot_info["needs_reboot"] and not reboot_info["is_stale"]:
                    lines.append(f"Reboot:          REQUIRED -- {reboot_info['explanation']}")
                    issues.append(f"Reboot required before upgrading.")
                elif reboot_info["needs_reboot"] and reboot_info["is_stale"]:
                    lines.append(f"Reboot:          flag set but stale, safe to ignore")
                else:
                    lines.append("Reboot:          not required")

                # Upgrade already in progress?
                running = api.firmware_upgradestatus()
                if running.get("status") == "running":
                    lines.append("In-progress:     YES -- upgrade/update is running now")
                    issues.append("An upgrade/update is already in progress. Use upgrade_status to monitor.")
                else:
                    lines.append("In-progress:     none")

                # Obsolete Python 3.7 packages (the python upgrade script explicitly checks for these)
                try:
                    info = api.firmware_info()
                    py37_pkgs = [p["name"] for p in info.get("package", [])
                                 if p.get("installed") == "1" and p.get("name", "").startswith("py37-")]
                    if py37_pkgs:
                        lines.append(f"Obsolete py37:   {len(py37_pkgs)} package(s) found -- should be removed before upgrading")
                        issues.append(f"Obsolete Python 3.7 packages installed: {', '.join(py37_pkgs[:5])}{'...' if len(py37_pkgs) > 5 else ''}. Remove via SSH before upgrading.")
                    else:
                        lines.append("Obsolete py37:   none found")
                except Exception:
                    lines.append("Obsolete py37:   check unavailable")

                # Verdict
                lines.append("")
                lines.append("-" * 40)
                if issues:
                    lines.append("VERDICT: NOT READY")
                    lines.append("Issues to resolve:")
                    for issue in issues:
                        lines.append(f"  - {issue}")
                elif fw_status == "upgrade" and not has_minor:
                    lines.append(f"VERDICT: READY for major upgrade to {next_major}")
                    lines.append("Use run_upgrade to proceed.")
                elif has_minor:
                    lines.append("VERDICT: READY to apply minor update")
                    lines.append("Use run_update to proceed.")
                elif next_major:
                    lines.append(f"VERDICT: System is up to date. Major upgrade to {next_major} is planned but not yet released.")
                else:
                    lines.append("VERDICT: System is fully up to date. No upgrades needed.")

                return text("\n".join(lines))

            else:
                raise ValueError(f"Unknown tool: {name}")

        except httpx.ConnectError:
            return text(
                "Cannot connect to OPNsense. Check that the firewall is reachable "
                "and the URL in mcp/.env is correct."
            )
        except httpx.TimeoutException:
            return text(
                "Request to OPNsense timed out. The firewall may be busy or unreachable."
            )
        except httpx.HTTPStatusError as e:
            return text(
                f"OPNsense API error: HTTP {e.response.status_code}. "
                "Check that the API key has the required privileges."
            )
        except ValueError:
            raise  # re-raise: read-only mode blocks and unknown tool names
        except Exception as e:
            return text(f"Unexpected error: {e}")

    return api
