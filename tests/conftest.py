from __future__ import annotations

import asyncio
import shutil
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from combine_run_mcp.config import Limits

# A python interpreter we can rely on in tests to stand in for Combine.
PYEXE = sys.executable


@pytest.fixture
def test_allowlist() -> frozenset[str]:
    """Executables the sandbox tests are allowed to invoke.

    Includes the basename of the running interpreter so ``PYEXE`` is
    accepted, plus a couple of coreutils used by individual tests.
    """
    from pathlib import PurePosixPath
    names = {PurePosixPath(PYEXE).name, "echo", "sleep"}
    return frozenset(names)


@pytest.fixture
def test_limits(test_allowlist: frozenset[str]) -> Limits:
    """Tight, fast limits with the test allowlist."""
    return Limits(
        default_timeout_s=5,
        max_timeout_s=10,
        max_total_input_bytes=1_000_000,
        max_concurrency=2,
        max_output_lines=50,
        allowed_executables=test_allowlist,
    )


@pytest.fixture
def mock_ctx(test_limits: Limits) -> MagicMock:
    """Mock FastMCP Context carrying the lifespan dict."""
    ctx: MagicMock = MagicMock()
    ctx.request_context.lifespan_context = {
        "limits": test_limits,
        "semaphore": asyncio.Semaphore(test_limits.max_concurrency),
    }
    return ctx


def capture_tools(register_func: Any) -> dict[str, Any]:
    """Capture tools registered by a register() function for direct calling."""
    mcp = MagicMock()
    tools: dict[str, Any] = {}

    def capture_tool() -> Any:
        def decorator(func: Any) -> Any:
            tools[func.__name__] = func
            return func
        return decorator

    mcp.tool = capture_tool
    register_func(mcp)
    return tools


def require(binary: str) -> None:
    """Skip a test if ``binary`` isn't on PATH."""
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} not available")
