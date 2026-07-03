"""Command-line interface for combine-run-mcp."""

from __future__ import annotations

import argparse

from combine_run_mcp.server import serve


def main() -> None:
    """Entry point for the ``combine-run-mcp`` command."""
    parser = argparse.ArgumentParser(
        prog="combine-run-mcp",
        description="MCP server that executes CMS Combine commands.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the MCP server",
    )
    serve_parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help=(
            "Transport (default: stdio). Use 'streamable-http' for a "
            "remote / PaaS deployment."
        ),
    )
    serve_parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="Bind address for HTTP transport (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    serve_parser.add_argument(
        "--profile",
        choices=["local", "remote"],
        default=None,
        help=(
            "Resource-limit profile. Default: inferred from transport "
            "(stdio -> local, streamable-http -> remote)."
        ),
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve(
            transport=args.transport,
            host=args.host,
            port=args.port,
            profile=args.profile,
        )
    else:
        parser.print_help()
