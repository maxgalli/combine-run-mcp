"""Tests for the run_combine MCP tool wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from combine_run_mcp.tools import run
from tests.conftest import PYEXE, capture_tools


def _get_tool():  # noqa: ANN202
    return capture_tools(run.register)["run_combine"]


class TestRunTool:
    async def test_returns_json_with_output(self, mock_ctx: MagicMock) -> None:
        tool = _get_tool()
        raw = await tool(
            command=f"{PYEXE} -c \"print('via-tool')\"",
            ctx=mock_ctx,
        )
        payload = json.loads(raw)
        assert payload["returncode"] == 0
        assert "via-tool" in payload["stdout"]

    async def test_disallowed_surfaces_error(self, mock_ctx: MagicMock) -> None:
        tool = _get_tool()
        raw = await tool(command="rm -rf /tmp/x", ctx=mock_ctx)
        payload = json.loads(raw)
        assert payload["returncode"] is None
        assert "not allowed" in payload["error"]

    async def test_timeout_clamped_to_ceiling(
        self, mock_ctx: MagicMock,
    ) -> None:
        # test_limits ceiling is 10s; requesting 99999 must not run that long.
        # A fast command still returns promptly; this just asserts the
        # clamp path doesn't reject or hang.
        tool = _get_tool()
        raw = await tool(
            command=f"{PYEXE} -c \"print('ok')\"",
            timeout_s=99999,
            ctx=mock_ctx,
        )
        payload = json.loads(raw)
        assert payload["returncode"] == 0

    async def test_files_passed_through(self, mock_ctx: MagicMock) -> None:
        tool = _get_tool()
        script = "print(open('d.txt').read().strip())"
        raw = await tool(
            command=f"{PYEXE} -c \"{script}\"",
            files={"d.txt": "hello-file"},
            ctx=mock_ctx,
        )
        payload = json.loads(raw)
        assert "hello-file" in payload["stdout"]

    async def test_input_cap_enforced_via_limits(
        self, mock_ctx: MagicMock,
    ) -> None:
        # mock_ctx limits cap input at 1_000_000 bytes; exceed it.
        tool = _get_tool()
        raw = await tool(
            command=f"{PYEXE} -c print('x')",
            files={"big.txt": "x" * 2_000_000},
            ctx=mock_ctx,
        )
        payload = json.loads(raw)
        assert payload["error"] is not None
        assert "limit" in payload["error"]
