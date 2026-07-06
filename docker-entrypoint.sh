#!/bin/bash
# Launch the MCP server in the container.
#
# Strip the base image's Python 3.9 env vars so the server's Python 3.11
# interpreter isn't polluted by them. `combine` (the compiled binary)
# still gets PATH + LD_LIBRARY_PATH from the image ENV, inherited by the
# subprocess the server spawns.
#
# `exec` so the server replaces this shell as PID 1 and receives signals
# (clean pod shutdown).
unset PYTHONPATH PYTHONHOME
exec /opt/mcp-venv/bin/combine-run-mcp serve \
    --transport streamable-http \
    --host 0.0.0.0 --port 8000 \
    --profile remote
