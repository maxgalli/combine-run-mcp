"""FastMCP server setup for the Combine execution MCP."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from combine_run_mcp.config import Limits, local_limits, remote_limits
from combine_run_mcp.nomenclature import COMBINE_RUN_GUIDE
from combine_run_mcp.tools import run

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# stdio is the local, on-your-machine deployment; streamable-http is the
# shared remote pod. The mapping is a sensible default, overridable with
# an explicit --profile.
_PROFILE_FOR_TRANSPORT = {
    "stdio": "local",
    "streamable-http": "remote",
}


def resolve_limits(transport: str, profile: str | None) -> Limits:
    """Pick the limits profile for a run.

    An explicit ``profile`` wins; otherwise it's inferred from the
    transport (stdio -> local, streamable-http -> remote).
    """
    resolved = profile or _PROFILE_FOR_TRANSPORT.get(transport, "remote")
    if resolved == "local":
        return local_limits()
    if resolved == "remote":
        return remote_limits()
    msg = f"unknown profile {resolved!r} (expected 'local' or 'remote')"
    raise ValueError(msg)


def _make_mcp(
    limits: Limits,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Build a configured FastMCP instance bound to ``limits``."""

    @asynccontextmanager
    async def _lifespan(
        _server: FastMCP,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Expose the limits and a shared concurrency semaphore.

        The semaphore bounds how many ``run_combine`` calls run at once,
        so a burst of requests can't spawn an unbounded number of
        Combine processes on the host.
        """
        yield {
            "limits": limits,
            "semaphore": asyncio.Semaphore(limits.max_concurrency),
        }

    mcp = FastMCP(
        "combine-run-mcp",
        lifespan=_lifespan,
        instructions=COMBINE_RUN_GUIDE,
        host=host,
        port=port,
    )
    run.register(mcp)
    return mcp


def serve(
    transport: str = "stdio",
    host: str = "0.0.0.0",  # noqa: S104 - container binds public by design
    port: int = 8000,
    profile: str | None = None,
) -> None:
    """Start the execution MCP server.

    Args:
        transport: ``"stdio"`` (local) or ``"streamable-http"`` (remote).
        host: Bind address for HTTP transport.
        port: Port for HTTP transport.
        profile: ``"local"`` or ``"remote"`` to force a limits profile;
            defaults to the transport-appropriate one.
    """
    limits = resolve_limits(transport, profile)
    mcp = _make_mcp(limits, host=host, port=port)
    mcp.run(transport=transport)
