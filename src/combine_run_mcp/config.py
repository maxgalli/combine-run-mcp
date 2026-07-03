"""Execution limits and profiles.

The same package powers two deployments with very different risk
profiles:

- **local** (stdio): the server runs on the user's own machine, in
  their own Combine environment. Generous timeouts, no upload cap,
  higher concurrency — the user is only ever hurting themselves.
- **remote** (streamable-HTTP on CERN PaaS): a shared pod. Tighter
  timeouts, a payload cap (large inputs should go to a local server),
  and low concurrency so one user can't starve the pod.

The two are expressed as :class:`Limits` instances built by
:func:`local_limits` / :func:`remote_limits`. The CLI picks one based
on transport (see :mod:`combine_run_mcp.server`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "DEFAULT_ALLOWED_EXECUTABLES",
    "Limits",
    "clamp_timeout",
    "local_limits",
    "remote_limits",
]

# The command's argv[0] (by basename) must be one of these. This makes
# the tool do what it says on the tin — run Combine — and nothing else.
# Arbitrary shell is deliberately out of scope; that's what a general
# shell tool is for. Extend here if new Combine-family entry points are
# needed.
DEFAULT_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({
    "combine",
    "combineTool.py",
    "text2workspace.py",
    "combineCards.py",
})


@dataclass(frozen=True)
class Limits:
    """Resource + safety limits applied to a single ``run_combine`` call."""

    default_timeout_s: int
    """Timeout used when the caller doesn't pass one."""

    max_timeout_s: int
    """Hard ceiling; a caller-supplied timeout is clamped to this."""

    max_total_input_bytes: int | None
    """Reject the call if the total size of materialized input files
    exceeds this. ``None`` means no cap (local)."""

    max_concurrency: int
    """How many ``run_combine`` calls may execute at once on this
    server. Enforced with a semaphore in the server lifespan."""

    max_output_lines: int
    """Per-stream (stdout / stderr) tail length returned to the caller.
    Longer output is truncated with a flag."""

    allowed_executables: frozenset[str] = field(
        default_factory=lambda: DEFAULT_ALLOWED_EXECUTABLES,
    )
    """Permitted command entry points (matched on ``argv[0]`` basename)."""


def local_limits() -> Limits:
    """Generous limits for a stdio server on the user's own machine."""
    return Limits(
        default_timeout_s=300,
        max_timeout_s=1800,
        max_total_input_bytes=None,
        max_concurrency=4,
        max_output_lines=400,
    )


def remote_limits() -> Limits:
    """Tight limits for a shared PaaS pod."""
    return Limits(
        default_timeout_s=120,
        max_timeout_s=300,
        max_total_input_bytes=10 * 1024 * 1024,  # 10 MB
        max_concurrency=2,
        max_output_lines=400,
    )


def clamp_timeout(requested: int | None, limits: Limits) -> int:
    """Resolve the effective timeout for a call.

    ``None`` -> the profile default. A value above the ceiling is
    clamped down; a non-positive value falls back to the default.
    """
    if requested is None or requested <= 0:
        return limits.default_timeout_s
    return min(requested, limits.max_timeout_s)
