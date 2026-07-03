"""Tests for limits profiles and timeout clamping."""

from __future__ import annotations

from combine_run_mcp.config import (
    DEFAULT_ALLOWED_EXECUTABLES,
    clamp_timeout,
    local_limits,
    remote_limits,
)


class TestProfiles:
    def test_local_is_uncapped_on_input(self) -> None:
        assert local_limits().max_total_input_bytes is None

    def test_remote_caps_input(self) -> None:
        assert remote_limits().max_total_input_bytes == 10 * 1024 * 1024

    def test_remote_timeout_ceiling_lower_than_local(self) -> None:
        assert remote_limits().max_timeout_s < local_limits().max_timeout_s

    def test_both_default_to_combine_allowlist(self) -> None:
        assert local_limits().allowed_executables == DEFAULT_ALLOWED_EXECUTABLES
        assert remote_limits().allowed_executables == DEFAULT_ALLOWED_EXECUTABLES

    def test_combine_family_in_allowlist(self) -> None:
        assert "combine" in DEFAULT_ALLOWED_EXECUTABLES
        assert "text2workspace.py" in DEFAULT_ALLOWED_EXECUTABLES


class TestClampTimeout:
    def test_none_uses_default(self) -> None:
        assert clamp_timeout(None, remote_limits()) == 120

    def test_zero_or_negative_uses_default(self) -> None:
        assert clamp_timeout(0, remote_limits()) == 120
        assert clamp_timeout(-5, remote_limits()) == 120

    def test_above_ceiling_clamped(self) -> None:
        assert clamp_timeout(99999, remote_limits()) == 300

    def test_within_range_passes_through(self) -> None:
        assert clamp_timeout(90, remote_limits()) == 90
