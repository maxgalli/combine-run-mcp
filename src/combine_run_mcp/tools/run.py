"""``run_combine`` — execute one Combine command and return its output.

Thin async wrapper over :func:`combine_run_mcp.sandbox.run_combine`.
The blocking subprocess work is pushed to a worker thread so the event
loop stays responsive, and a lifespan-scoped semaphore bounds how many
runs execute at once (see :mod:`combine_run_mcp.server`).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from combine_run_mcp import sandbox
from combine_run_mcp.config import Limits, clamp_timeout  # noqa: TC001

# Name of the env var that carries a PYTHONPATH to hand to the spawned
# Combine command (but NOT to the server's own interpreter). Set by the
# container image: `combine` invokes text2workspace.py, which needs
# PyROOT on PYTHONPATH, but that same PYTHONPATH points at Python 3.9
# packages that would break the 3.11 server if it inherited them.
_SUBPROCESS_PYTHONPATH_ENV = "COMBINE_RUN_PYTHONPATH"


def _subprocess_extra_env() -> dict[str, str] | None:
    """Build the per-subprocess env overlay from the deployment config."""
    pythonpath = os.environ.get(_SUBPROCESS_PYTHONPATH_ENV)
    if pythonpath:
        return {"PYTHONPATH": pythonpath}
    return None


def register(mcp: FastMCP) -> None:
    """Register the run tool."""

    @mcp.tool()
    async def run_combine(
        command: str,
        files: dict[str, str] | None = None,
        files_b64: dict[str, str] | None = None,
        timeout_s: int | None = None,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Run one CMS Combine command in an isolated workspace.

        Only Combine-family executables are permitted (`combine`,
        `combineTool.py`, `text2workspace.py`, `combineCards.py`); the
        command is executed without a shell. Input files you pass are
        written into a throwaway directory that is the command's working
        directory, then deleted after the run.

        Args:
            command: Full command line, e.g.
                ``"combine -M AsymptoticLimits -d datacard.txt -m 120"``.
            files: Text input files as ``{filename: content}`` (e.g. the
                datacard). Filenames are relative to the workspace;
                subdirectories are allowed, ``..`` and absolute paths
                are rejected.
            files_b64: Binary input files as ``{filename: base64}`` —
                use this for ROOT shape files a datacard references.
            timeout_s: Wall-clock timeout in seconds. Optional; if
                omitted or above this server's ceiling it is clamped.

        Returns:
            JSON with ``returncode``, ``stdout``, ``stderr`` (tails,
            plus ``stdout_truncated`` / ``stderr_truncated``),
            ``artifacts`` (files produced: name + size), ``elapsed_s``,
            ``timed_out``, and ``error`` (set only for setup failures,
            e.g. a disallowed executable or a missing Combine install).
        """
        ctxd = ctx.request_context.lifespan_context
        limits: Limits = ctxd["limits"]
        semaphore: asyncio.Semaphore = ctxd["semaphore"]

        effective_timeout = clamp_timeout(timeout_s, limits)

        async with semaphore:
            result = await asyncio.to_thread(
                sandbox.run_combine,
                command,
                files=files,
                files_b64=files_b64,
                timeout_s=effective_timeout,
                max_output_lines=limits.max_output_lines,
                max_total_input_bytes=limits.max_total_input_bytes,
                allowed_executables=limits.allowed_executables,
                extra_env=_subprocess_extra_env(),
            )

        return json.dumps(result.to_dict(), default=str)
