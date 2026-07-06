"""Execute a single Combine command in an isolated workspace.

This module is transport-agnostic and has no MCP dependency, so it is
trivially unit-testable. The MCP tool in :mod:`combine_run_mcp.tools.run`
is a thin async wrapper around :func:`run_combine`.

Design:

- Each call gets a fresh :class:`tempfile.TemporaryDirectory`. Caller-
  supplied input files are materialized inside it (with path-traversal
  guards); the command runs with that dir as cwd; the dir is deleted
  when the call returns. Output files the command produced are reported
  by name (not content) as ``artifacts``.
- The command's ``argv[0]`` (by basename) must be in an allowlist —
  this tool runs Combine, not arbitrary shell. The command is parsed
  with :func:`shlex.split` and executed **without** a shell, so there
  is no shell-injection surface.
- The child runs in its own process group; on timeout the whole group
  is killed (Combine can spawn helper subprocesses).
"""

from __future__ import annotations

import base64
import binascii
import os
import shlex
import signal
import subprocess  # noqa: S404 — executing Combine is the whole point
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from combine_run_mcp.config import DEFAULT_ALLOWED_EXECUTABLES

__all__ = ["RunResult", "run_combine"]

_DEFAULT_TIMEOUT_S = 120
_DEFAULT_MAX_OUTPUT_LINES = 400


@dataclass
class RunResult:
    """Outcome of one ``run_combine`` call.

    ``error`` is set (and ``returncode`` left ``None``) for failures
    that happen *before or instead of* running the command — bad
    command string, disallowed executable, oversized input, executable
    not found on PATH. A command that runs but exits non-zero is *not*
    an error here: it has a ``returncode`` and its ``stderr``.
    """

    command: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    elapsed_s: float = 0.0
    timed_out: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tail(text: str, max_lines: int) -> tuple[str, bool]:
    """Return the last ``max_lines`` lines of ``text`` and a truncated flag."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    kept = lines[-max_lines:]
    return "\n".join(kept), True


def _safe_target(base: Path, name: str) -> Path:
    """Resolve ``name`` under ``base``, rejecting escapes.

    Rejects absolute paths and any ``..`` traversal. Parent
    directories implied by ``name`` (e.g. ``shapes/card.root``) are
    allowed and created by the caller.
    """
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        msg = f"unsafe input file name: {name!r}"
        raise ValueError(msg)
    target = (base / pure).resolve()
    base_resolved = base.resolve()
    if base_resolved != target and base_resolved not in target.parents:
        msg = f"input file escapes workspace: {name!r}"
        raise ValueError(msg)
    return target


def _materialize_inputs(
    workspace: Path,
    files: dict[str, str] | None,
    files_b64: dict[str, str] | None,
) -> set[str]:
    """Write input files into ``workspace``; return their relative names.

    Text files come through ``files``; binary (e.g. ROOT shape files)
    through ``files_b64`` as base64. Raises ``ValueError`` on unsafe
    names or malformed base64.
    """
    written: set[str] = set()

    def _write(name: str, data: bytes) -> None:
        target = _safe_target(workspace, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.add(PurePosixPath(name).as_posix())

    for name, content in (files or {}).items():
        _write(name, content.encode("utf-8"))

    for name, b64 in (files_b64 or {}).items():
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            msg = f"invalid base64 for input file {name!r}: {exc}"
            raise ValueError(msg) from exc
        _write(name, data)

    return written


def _total_input_bytes(
    files: dict[str, str] | None,
    files_b64: dict[str, str] | None,
) -> int:
    """Estimate materialized input size without writing anything."""
    total = 0
    for content in (files or {}).values():
        total += len(content.encode("utf-8"))
    for b64 in (files_b64 or {}).values():
        # 4 base64 chars -> 3 bytes; good enough for a pre-flight check.
        total += (len(b64) * 3) // 4
    return total


def _collect_artifacts(
    workspace: Path, inputs: set[str],
) -> list[dict[str, Any]]:
    """List files produced by the run (everything not supplied as input)."""
    artifacts: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        if rel in inputs:
            continue
        artifacts.append({"name": rel, "size_bytes": path.stat().st_size})
    return artifacts


def _run_in_workspace(
    argv: list[str],
    workspace: Path,
    timeout_s: int,
    env: dict[str, str] | None = None,
) -> tuple[int | None, str, str, bool]:
    """Run ``argv`` in ``workspace``; return (rc, stdout, stderr, timed_out).

    The child is launched in its own process group so that a timeout
    can kill the whole tree (Combine may spawn helpers). Output is
    decoded permissively so odd bytes never crash the reader. ``env``
    is the full environment for the child; ``None`` inherits the
    parent's.
    """
    proc = subprocess.Popen(  # noqa: S603 — argv is allowlisted, no shell
        argv,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return proc.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        stdout, stderr = proc.communicate()
        return None, stdout, stderr, True


def run_combine(
    command: str,
    *,
    files: dict[str, str] | None = None,
    files_b64: dict[str, str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    max_output_lines: int = _DEFAULT_MAX_OUTPUT_LINES,
    max_total_input_bytes: int | None = None,
    allowed_executables: frozenset[str] = DEFAULT_ALLOWED_EXECUTABLES,
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    """Run one Combine command in a throwaway workspace.

    Args:
        command: The full command line, e.g.
            ``"combine -M AsymptoticLimits -d datacard.txt -m 120"``.
            Parsed with :func:`shlex.split`; executed without a shell.
        files: Text input files, ``{name: content}``, written into the
            workspace before the run (datacards, configs, …).
        files_b64: Binary input files, ``{name: base64}`` (e.g. ROOT
            shape files).
        timeout_s: Wall-clock timeout. On expiry the process group is
            killed and ``timed_out`` is set.
        max_output_lines: Tail length per stream returned to the caller.
        max_total_input_bytes: Reject the call if inputs exceed this
            (``None`` = no cap).
        allowed_executables: Permitted ``argv[0]`` basenames.
        extra_env: Environment overrides merged over the inherited
            environment *for the spawned command only*. Used to hand the
            Combine subprocess variables the server itself deliberately
            drops — e.g. a ``PYTHONPATH`` that points at PyROOT, which
            ``combine`` needs when it invokes ``text2workspace.py`` but
            which would pollute the server's own interpreter.

    Returns:
        A :class:`RunResult`. Setup problems populate ``error`` and
        leave ``returncode`` ``None``; a command that ran populates
        ``returncode`` (and ``timed_out`` if it was killed).
    """
    started = time.monotonic()

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return RunResult(command=command, error=f"could not parse command: {exc}")
    if not argv:
        return RunResult(command=command, error="empty command")

    executable = PurePosixPath(argv[0]).name
    if executable not in allowed_executables:
        allowed = ", ".join(sorted(allowed_executables))
        return RunResult(
            command=command,
            error=(
                f"executable {executable!r} is not allowed. This server "
                f"only runs Combine commands. Allowed: {allowed}."
            ),
        )

    if max_total_input_bytes is not None:
        size = _total_input_bytes(files, files_b64)
        if size > max_total_input_bytes:
            mb = max_total_input_bytes / (1024 * 1024)
            return RunResult(
                command=command,
                error=(
                    f"input files total {size} bytes, over this server's "
                    f"{mb:.0f} MB limit. Run a local combine-run server for "
                    "large inputs."
                ),
            )

    with TemporaryDirectory(prefix="combine-run-") as tmp:
        workspace = Path(tmp)
        try:
            inputs = _materialize_inputs(workspace, files, files_b64)
        except ValueError as exc:
            return RunResult(command=command, error=str(exc))

        child_env = {**os.environ, **extra_env} if extra_env else None
        try:
            rc, stdout, stderr, timed_out = _run_in_workspace(
                argv, workspace, timeout_s, env=child_env,
            )
        except FileNotFoundError:
            return RunResult(
                command=command,
                error=(
                    f"{executable!r} was not found on PATH. Is the Combine "
                    "environment set up (e.g. a CMSSW area sourced) for the "
                    "process running this server?"
                ),
            )

        artifacts = _collect_artifacts(workspace, inputs)

    stdout_t, stdout_trunc = _tail(stdout, max_output_lines)
    stderr_t, stderr_trunc = _tail(stderr, max_output_lines)

    return RunResult(
        command=command,
        returncode=rc,
        stdout=stdout_t,
        stderr=stderr_t,
        stdout_truncated=stdout_trunc,
        stderr_truncated=stderr_trunc,
        artifacts=artifacts,
        elapsed_s=round(time.monotonic() - started, 3),
        timed_out=timed_out,
    )
