"""MCP tool definitions for OPNsense."""

import re
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
        name="get_config_backup",
        description="Download the current OPNsense configuration XML and return a summary.",
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

            if next_major:
                lines.append(f"Next major version: {next_major} (use run_upgrade to upgrade)")
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
            data = api.firmware_status()
            all_pkgs = data.get("all_packages", [])
            if not all_pkgs:
                return text("Package list not available in firmware status cache. Try check_updates first.")
            lines = [f"{p.get('name', '?'):<40} {p.get('version', '?')}" for p in all_pkgs]
            return text(f"{len(lines)} packages installed:\n\n" + "\n".join(lines))

        elif name == "get_config_backup":
            content = api.backup_download()
            size_kb = len(content) / 1024
            sections = re.findall(rb"<(\w+)>", content[:2000])
            top_sections = list(dict.fromkeys(sections))[:10]
            summary = [
                f"Configuration backup downloaded: {size_kb:.1f} KB",
                f"Top-level sections: {', '.join(s.decode() for s in top_sections)}",
                "",
                "To save locally, ask Claude to write it to a file.",
            ]
            return text("\n".join(summary))

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
            result = api.firmware_update()
            msg = result.get("msg", "") or result.get("status", str(result))
            return text(f"Update triggered: {msg}\n\nUse upgrade_status to monitor progress.")

        elif name == "run_upgrade":
            check_writable()
            version = arguments.get("version", "")
            result = api.firmware_upgrade(version)
            msg = result.get("msg", "") or result.get("status", str(result))
            return text(f"Upgrade triggered: {msg}\n\nUse upgrade_status to monitor. The system will reboot during the upgrade.")

        elif name == "reboot":
            check_writable()
            result = api.firmware_reboot()
            msg = result.get("msg", "") or result.get("status", str(result))
            return text(f"Reboot initiated: {msg}")

        else:
            raise ValueError(f"Unknown tool: {name}")

    return api
