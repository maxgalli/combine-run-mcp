"""Tests for the execution sandbox.

These run real subprocesses, standing in for Combine with the running
Python interpreter (``PYEXE``) plus a couple of coreutils. The
``test_allowlist`` fixture permits exactly those.
"""

from __future__ import annotations

import base64

import pytest

from combine_run_mcp.sandbox import _safe_target, _tail, run_combine
from tests.conftest import PYEXE, require


class TestTail:
    def test_short_text_unchanged(self) -> None:
        text, trunc = _tail("a\nb\nc", 10)
        assert text == "a\nb\nc"
        assert trunc is False

    def test_long_text_keeps_last_lines(self) -> None:
        text, trunc = _tail("\n".join(str(i) for i in range(100)), 10)
        assert trunc is True
        assert text.splitlines() == [str(i) for i in range(90, 100)]


class TestSafeTarget:
    def test_plain_name_ok(self, tmp_path) -> None:  # noqa: ANN001
        assert _safe_target(tmp_path, "datacard.txt").name == "datacard.txt"

    def test_subdir_ok(self, tmp_path) -> None:  # noqa: ANN001
        target = _safe_target(tmp_path, "shapes/card.root")
        assert target.name == "card.root"

    def test_absolute_rejected(self, tmp_path) -> None:  # noqa: ANN001
        with pytest.raises(ValueError, match="unsafe input file name"):
            _safe_target(tmp_path, "/etc/passwd")

    def test_dotdot_rejected(self, tmp_path) -> None:  # noqa: ANN001
        with pytest.raises(ValueError, match="unsafe input file name"):
            _safe_target(tmp_path, "../escape.txt")


class TestRunCombine:
    def test_basic_run(self, test_allowlist: frozenset[str]) -> None:
        result = run_combine(
            f"{PYEXE} -c \"print('hello-combine')\"",
            allowed_executables=test_allowlist,
        )
        assert result.error is None
        assert result.returncode == 0
        assert "hello-combine" in result.stdout
        assert result.timed_out is False

    def test_nonzero_exit_is_not_an_error(
        self, test_allowlist: frozenset[str],
    ) -> None:
        result = run_combine(
            f"{PYEXE} -c \"import sys; sys.exit(3)\"",
            allowed_executables=test_allowlist,
        )
        # A command that runs but fails has a returncode, not an error.
        assert result.error is None
        assert result.returncode == 3

    def test_stderr_captured(self, test_allowlist: frozenset[str]) -> None:
        result = run_combine(
            f"{PYEXE} -c \"import sys; print('oops', file=sys.stderr)\"",
            allowed_executables=test_allowlist,
        )
        assert "oops" in result.stderr

    def test_disallowed_executable(self) -> None:
        result = run_combine(
            "rm -rf /tmp/whatever",
            allowed_executables=frozenset({"echo"}),
        )
        assert result.returncode is None
        assert result.error is not None
        assert "not allowed" in result.error

    def test_empty_command(self, test_allowlist: frozenset[str]) -> None:
        result = run_combine("   ", allowed_executables=test_allowlist)
        assert result.error == "empty command"

    def test_unparseable_command(self, test_allowlist: frozenset[str]) -> None:
        result = run_combine(
            'combine -d "unterminated',
            allowed_executables=test_allowlist,
        )
        assert result.error is not None
        assert "could not parse" in result.error

    def test_executable_not_found(self) -> None:
        result = run_combine(
            "combine -M AsymptoticLimits",
            allowed_executables=frozenset({"combine"}),
        )
        # 'combine' is allowed but not installed in the test env.
        assert result.returncode is None
        assert result.error is not None
        assert "not found on PATH" in result.error

    def test_timeout(self, test_allowlist: frozenset[str]) -> None:
        result = run_combine(
            f"{PYEXE} -c \"import time; time.sleep(30)\"",
            timeout_s=1,
            allowed_executables=test_allowlist,
        )
        assert result.timed_out is True
        assert result.returncode is None

    def test_text_input_materialized_and_read(
        self, test_allowlist: frozenset[str],
    ) -> None:
        script = "print(open('datacard.txt').read().strip())"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            files={"datacard.txt": "imax 1\njmax 1"},
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert "imax 1" in result.stdout

    def test_binary_input_materialized(
        self, test_allowlist: frozenset[str],
    ) -> None:
        payload = b"\x00\x01ROOTish\xff"
        script = (
            "import sys; "
            "sys.stdout.write(str(len(open('shapes.root','rb').read())))"
        )
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            files_b64={"shapes.root": base64.b64encode(payload).decode()},
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == str(len(payload))

    def test_bad_base64_is_error(
        self, test_allowlist: frozenset[str],
    ) -> None:
        result = run_combine(
            f"{PYEXE} -c \"pass\"",
            files_b64={"shapes.root": "not-valid-base64!!!"},
            allowed_executables=test_allowlist,
        )
        assert result.error is not None
        assert "base64" in result.error

    def test_artifacts_reported_inputs_excluded(
        self, test_allowlist: frozenset[str],
    ) -> None:
        script = "open('higgsCombineTest.root','w').write('x'*10)"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            files={"datacard.txt": "content"},
            allowed_executables=test_allowlist,
        )
        names = {a["name"] for a in result.artifacts}
        assert "higgsCombineTest.root" in names
        assert "datacard.txt" not in names  # input, not artifact
        produced = next(
            a for a in result.artifacts if a["name"] == "higgsCombineTest.root"
        )
        assert produced["size_bytes"] == 10

    def test_unsafe_input_name_rejected(
        self, test_allowlist: frozenset[str],
    ) -> None:
        result = run_combine(
            f"{PYEXE} -c \"pass\"",
            files={"../evil.txt": "x"},
            allowed_executables=test_allowlist,
        )
        assert result.error is not None
        assert "unsafe input file name" in result.error

    def test_input_size_cap_enforced(
        self, test_allowlist: frozenset[str],
    ) -> None:
        result = run_combine(
            f"{PYEXE} -c \"pass\"",
            files={"big.txt": "x" * 5000},
            max_total_input_bytes=1000,
            allowed_executables=test_allowlist,
        )
        assert result.error is not None
        assert "limit" in result.error

    def test_output_truncation(
        self, test_allowlist: frozenset[str],
    ) -> None:
        script = "[print(i) for i in range(500)]"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            max_output_lines=10,
            allowed_executables=test_allowlist,
        )
        assert result.stdout_truncated is True
        assert len(result.stdout.splitlines()) == 10

    def test_workspace_is_cleaned_up(
        self, test_allowlist: frozenset[str],
    ) -> None:
        # Capture the cwd the child saw, then assert it's gone.
        script = "import os; print(os.getcwd())"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            allowed_executables=test_allowlist,
        )
        from pathlib import Path
        child_cwd = Path(result.stdout.strip())
        assert not child_cwd.exists()

    def test_echo_via_coreutil(self, test_allowlist: frozenset[str]) -> None:
        require("echo")
        result = run_combine(
            "echo combine-lives",
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert "combine-lives" in result.stdout

    def test_stack_limit_raised_for_subprocess(
        self, test_allowlist: frozenset[str],
    ) -> None:
        # The child should inherit a stack soft limit raised to the hard
        # limit (or unlimited) — the ulimit -s unlimited recommendation.
        script = (
            "import resource;"
            "s,h=resource.getrlimit(resource.RLIMIT_STACK);"
            "print(s==h or s==resource.RLIM_INFINITY)"
        )
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "True"

    def test_extra_env_reaches_subprocess(
        self, test_allowlist: frozenset[str],
    ) -> None:
        script = "import os; print(os.environ.get('COMBINE_TEST_VAR'))"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            extra_env={"COMBINE_TEST_VAR": "pyroot-here"},
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "pyroot-here"

    def test_extra_env_overlays_not_replaces(
        self, test_allowlist: frozenset[str],
    ) -> None:
        # With extra_env set, the child still inherits the rest of the
        # environment (PATH etc.), not just the overlay.
        script = "import os; print(bool(os.environ.get('PATH')))"
        result = run_combine(
            f"{PYEXE} -c \"{script}\"",
            extra_env={"COMBINE_TEST_VAR": "x"},
            allowed_executables=test_allowlist,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "True"
