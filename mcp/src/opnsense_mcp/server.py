"""MCP server entry point for OPNsense integration."""

import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server

from .config import Config
from .tools import register_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("opnsense_mcp")


async def main():
    try:
        config = Config.from_env()
    except ValueError as e:
        log.error("Configuration error: %s", e)
        sys.exit(1)

    log.info("Starting OPNsense MCP server (url=%s, read_only=%s)", config.url, config.read_only)

    server = Server("opnsense")
    api = register_tools(server, config)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        api.close()
        log.info("OPNsense MCP server stopped.")


def run():
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()
