"""Instructions blob describing what this MCP server does.

Embedded into the FastMCP ``instructions`` string so an agent knows
the tool's scope, safety model, and the local-vs-remote trade-off.
"""

from __future__ import annotations

COMBINE_RUN_GUIDE = """\
# CMS Combine — Execution Server

This MCP server runs CMS Combine (HiggsAnalysis-CombinedLimit) commands
in an isolated, throwaway workspace and returns their output. It is the
execution companion to the read-only `combine-mcp` retrieval server.

## Scope

- Runs a single Combine-family command per call: `combine`,
  `combineTool.py`, `text2workspace.py`, `combineCards.py`.
- Arbitrary shell is **not** supported — the command's executable must
  be one of the above. There is no shell interpretation, so pipes and
  redirects are not available.
- Each call is isolated: input files you pass are written into a fresh
  temp directory, the command runs there, output files are reported by
  name, and the directory is deleted afterwards. Nothing persists
  between calls.

## Tool

`run_combine(command, files=None, files_b64=None, timeout_s=None)`
  - `command`: the full command line, e.g.
    `"combine -M AsymptoticLimits -d datacard.txt -m 120"`.
  - `files`: text inputs as `{filename: content}` (datacards, configs).
  - `files_b64`: binary inputs as `{filename: base64}` (ROOT shape
    files).
  - `timeout_s`: optional; clamped to this server's ceiling.

Returns JSON: `returncode`, `stdout`, `stderr` (tails, with truncation
flags), `artifacts` (output files produced, by name + size),
`elapsed_s`, `timed_out`, and `error` (set only for setup failures like
a disallowed executable or a missing Combine install).

## Typical use — reproduce and diagnose

The main use case is debugging: a user reports a Combine command that
errors or gives a wrong result. Reproduce it here, then cross-check the
output against the `combine-mcp` sources (docs / code / forum) to
explain and fix.

1. `run_combine(command=<their command>, files={<their datacard>})`.
2. Read `returncode` / `stderr`. If it failed, search `combine-mcp`
   (`source="combine-forum"` for the error text, `source="combine-code"`
   for what the code checks) to explain the cause.
3. Propose a corrected command and, if useful, re-run it to confirm.

## Local vs remote

The same tool may be served two ways:

- **local** (stdio, on the user's machine): no upload limits, longer
  timeouts. Requires a working Combine environment where the server
  process runs.
- **remote** (this server, if reached over HTTP on CERN PaaS): shared
  resource, so inputs are size-capped and timeouts are shorter. For
  large datacards or long fits, prefer a local server.

If `error` says the executable was not found on PATH, the server's
process has no Combine environment sourced — tell the user rather than
guessing at results.
"""
