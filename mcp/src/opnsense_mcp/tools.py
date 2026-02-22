"""MCP tool definitions for OPNsense."""

import re
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

from .api import OPNsenseAPI
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
                product = status.get("product", {})
                current = product.get("product_version", "unknown")
                latest_minor = product.get("product_latest", "")
                next_major = product.get("CORE_NEXT", "")
                upgrade_packages = status.get("upgrade_packages", [])
                status_msg = status.get("status_msg", "")
                fw_status = status.get("status", "none")

                lines = [f"Current version: {current}"]
                if fw_status == "update":
                    lines.append(f"Minor update available: {latest_minor} ({len(upgrade_packages)} packages)")
                elif latest_minor and latest_minor != current.split("_")[0]:
                    lines.append(f"Minor update available: {latest_minor}")
                else:
                    lines.append("Minor update: up to date")

                if fw_status == "upgrade":
                    lines.append(f"Major upgrade available: {next_major} (use run_upgrade to upgrade)")
                elif next_major:
                    lines.append(f"Next major version: {next_major} (planned, not yet released)")
                else:
                    lines.append("Major upgrade: none available")

                lines.append(f"Status: {status_msg or 'no updates available'}")

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
                return text("\n".join(lines))

            elif name == "get_changelog":
                version = arguments.get("version", "")
                data = api.firmware_changelog(version)
                html = data.get("html", "") or data.get("changelog", "")
                if not html:
                    return text(f"No changelog found for version {version}.")
                clean = re.sub(r"<[^>]+>", "", html).strip()
                clean = re.sub(r"\n{3,}", "\n\n", clean)
                return text(f"Changelog for {version}:\n\n{clean[:4000]}")

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
                if processes:
                    lines.append("\nTop processes:")
                    lines.append(f"  {'PID':<8} {'USERNAME':<12} {'CPU%':<8} {'MEM%':<8} COMMAND")
                    for p in processes:
                        lines.append(
                            f"  {p.get('PID',''):<8} {p.get('USERNAME',''):<12} "
                            f"{p.get('%CPU',''):<8} {p.get('%MEM',''):<8} {p.get('COMMAND','')[:40]}"
                        )
                return text("\n".join(lines))

            elif name == "run_update":
                check_writable()
                # Block if an upgrade/update is already running
                running = api.firmware_upgradestatus()
                if running.get("status") == "running":
                    return text("An upgrade/update is already in progress. Use upgrade_status to monitor it.")
                # Block if already up to date
                status = api.firmware_status()
                if status.get("status") == "none":
                    return text("System is already up to date. No update needed.")
                result = api.firmware_update()
                msg = result.get("msg", "") or result.get("status", str(result))
                return text(f"Update triggered: {msg}\n\nUse upgrade_status to monitor progress.")

            elif name == "run_upgrade":
                check_writable()
                # Block if an upgrade/update is already running
                running = api.firmware_upgradestatus()
                if running.get("status") == "running":
                    return text("An upgrade/update is already in progress. Use upgrade_status to monitor it.")
                # Check firmware status before proceeding
                status = api.firmware_status()
                product = status.get("product", {})
                current = product.get("product_version", "")
                latest_minor = product.get("product_latest", "")
                next_major = product.get("CORE_NEXT", "")
                fw_status = status.get("status", "none")
                current_base = current.split("_")[0] if current else ""

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
                has_minor = fw_status == "update" or (
                    latest_minor and current_base and latest_minor != current_base
                )
                if has_minor:
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
                product = status.get("product", {})
                current = product.get("product_version", "unknown")
                latest_minor = product.get("product_latest", "")
                next_major = product.get("CORE_NEXT", "")
                fw_status = status.get("status", "none")
                current_base = current.split("_")[0] if current else ""

                lines.append(f"Current version: {current}")

                # Minor updates pending?
                has_minor = fw_status == "update" or (
                    latest_minor and current_base and latest_minor != current_base
                )
                if has_minor:
                    lines.append(f"Minor update:    {latest_minor} -- PENDING (must apply before major upgrade)")
                    issues.append(f"Minor update pending ({current} -> {latest_minor}). Run run_update first.")
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
                if reboot_info["needs_reboot"] and not reboot_info["is_stale"]:
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
