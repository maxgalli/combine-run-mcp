# Execution-server image: layer combine-run-mcp on top of the official,
# self-contained Combine *standalone* image. That image compiles Combine
# and all its dependencies (ROOT, Boost, GSL, ...) into the image, so it
# needs no CVMFS at runtime — ideal for a PaaS/OpenShift pod. `combine`
# is already on PATH via the base image's ENV, so no activation step is
# needed here.
#
# Pin COMBINE_IMAGE to the tag matching the Combine version you want
# (align it with combine-mcp's `combine-code` source, v10.6.0).
ARG COMBINE_IMAGE=gitlab-registry.cern.ch/cms-cloud/combine-standalone:v10.6.0
FROM ${COMBINE_IMAGE}

# The base image drops to `cmsusr`; we need root to install and to relax
# permissions for OpenShift's arbitrary-UID model.
USER root

# The base ships Python 3.9 (for PyROOT) and reshapes the system Python
# so heavily that `dnf` and the system interpreter are unusable from our
# layer. The MCP SDK needs Python >=3.10 anyway, so we sidestep the base
# Python entirely: `uv` is a self-contained (Rust) binary that provides a
# standalone Python 3.11 with no dependency on the system package
# manager. Combine itself is a compiled binary we invoke as a
# subprocess, so the two Python runtimes never interact.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Keep the downloaded interpreter in a fixed, group-writable location.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python

COPY . /opt/combine-run-mcp

# Build the server venv (Python 3.11, auto-downloaded by uv) and install
# the server into it. Strip the base image's Python env vars for these
# steps so the fresh 3.11 interpreter isn't polluted by the Combine 3.9
# module paths.
RUN env -u PYTHONPATH -u PYTHONHOME bash -c '\
      uv venv --python 3.11 /opt/mcp-venv && \
      uv pip install --python /opt/mcp-venv --no-cache /opt/combine-run-mcp'

# OpenShift runs the pod as a random, non-root UID in group 0. Make the
# dirs the server or ROOT may write to group-owned by 0 and
# group-writable, so an arbitrary UID can use them. (Per-run Combine
# workspaces live under /tmp, which is already world-writable.)
RUN chgrp -R 0 /home/cmsusr /code /opt/mcp-venv /opt/uv-python \
    && chmod -R g=u /home/cmsusr /code /opt/mcp-venv /opt/uv-python

USER cmsusr

EXPOSE 8000

# `combine` (the binary) is on PATH and needs LD_LIBRARY_PATH — both come
# from the base image ENV and are inherited by the combine subprocess. We
# strip only PYTHONPATH/PYTHONHOME so the 3.11 server interpreter isn't
# polluted by the base image's Python 3.9 module paths.
#
# NOTE: this means the Python-based Combine tools (text2workspace.py,
# combineCards.py), which need the 3.9 PYTHONPATH, won't resolve their
# modules yet. The `combine` binary — the primary use case — works. A
# follow-up will re-inject the Combine PYTHONPATH per-subprocess.
ENTRYPOINT []
CMD ["env", "-u", "PYTHONPATH", "-u", "PYTHONHOME", \
     "/opt/mcp-venv/bin/combine-run-mcp", "serve", \
     "--transport", "streamable-http", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--profile", "remote"]
