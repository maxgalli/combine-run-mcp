#!/usr/bin/env python3
"""Standalone smoke test for the combine-run-mcp execution engine.

Runs a *real* Combine command through the sandbox against a tiny,
self-contained counting datacard — no MCP server, no agent, just
:func:`combine_run_mcp.sandbox.run_combine`. Use it to confirm the
engine actually drives Combine in an environment where Combine is set
up (lxplus with a CMSSW area sourced, a Combine container, the PaaS
pod, ...).

Usage:

    # in a shell where `which combine` resolves:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --method FitDiagnostics --timeout 120

Exit code is 0 on success, 1 on failure, so it can be used in CI on a
Combine-enabled image.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running straight from a repo checkout without installing.
try:
    from combine_run_mcp.sandbox import run_combine
except ModuleNotFoundError:  # pragma: no cover - convenience fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from combine_run_mcp.sandbox import run_combine


# A minimal, fully self-contained counting datacard: 1 channel, 1
# signal, 1 background, 1 nuisance. No external shape files, so it needs
# nothing but Combine itself.
DATACARD = """\
imax 1  number of channels
jmax 1  number of backgrounds
kmax 1  number of nuisance parameters
------------
bin          b1
observation  1
------------
bin      b1    b1
process  sig   bkg
process  0     1
rate     2     1
------------
lumi  lnN  1.10  1.10
"""


def _print_header(text: str) -> None:
    print(f"\n{'=' * 60}\n{text}\n{'=' * 60}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        default="AsymptoticLimits",
        help="Combine method to run (default: AsymptoticLimits)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="timeout in seconds (default: 120)",
    )
    args = parser.parse_args(argv)

    command = f"combine -M {args.method} datacard.txt"

    _print_header(f"Running: {command}")
    print("Datacard:\n")
    print(DATACARD)

    result = run_combine(
        command,
        files={"datacard.txt": DATACARD},
        timeout_s=args.timeout,
    )

    _print_header("Result")
    print(f"returncode : {result.returncode}")
    print(f"timed_out  : {result.timed_out}")
    print(f"elapsed_s  : {result.elapsed_s}")
    print(f"error      : {result.error}")

    if result.stdout:
        _print_header("stdout" + (" (truncated)" if result.stdout_truncated else ""))
        print(result.stdout)
    if result.stderr:
        _print_header("stderr" + (" (truncated)" if result.stderr_truncated else ""))
        print(result.stderr)

    _print_header("Artifacts produced")
    if result.artifacts:
        for art in result.artifacts:
            print(f"  {art['name']}  ({art['size_bytes']} bytes)")
    else:
        print("  (none)")

    # ---- verdict ------------------------------------------------------
    _print_header("Verdict")

    if result.error and "not found on PATH" in result.error:
        print("FAIL: Combine was not found on PATH.")
        print("      Source your Combine environment first, e.g.:")
        print("        cd <CMSSW area>/src && cmsenv")
        print("      then re-run this script.")
        return 1

    if result.error:
        print(f"FAIL: setup error -> {result.error}")
        return 1

    if result.timed_out:
        print(f"FAIL: command timed out after {args.timeout}s.")
        return 1

    produced_root = any(
        a["name"].endswith(".root") for a in result.artifacts
    )
    if result.returncode == 0 and produced_root:
        print("PASS: Combine ran, exited 0, and produced a ROOT output file.")
        print("      The execution engine works against real Combine.")
        return 0

    if result.returncode == 0:
        print("PARTIAL: Combine exited 0 but produced no .root artifact.")
        print("         Check the method / datacard; the engine itself ran fine.")
        return 1

    print(f"FAIL: Combine exited with code {result.returncode}. See stderr above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
