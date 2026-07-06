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

# `combine` shells out to text2workspace.py (Python) to turn a text
# datacard into a workspace, and that script needs PyROOT on PYTHONPATH.
# But that PYTHONPATH points at Python 3.9 packages that would break our
# 3.11 server if it inherited them — so the entrypoint unsets PYTHONPATH
# for the server, and we stash the Combine value here under a different
# name. The server re-injects it for the spawned command only. Keep this
# in sync with the base image's PYTHONPATH.
ENV COMBINE_RUN_PYTHONPATH=/code/HiggsAnalysis/CombinedLimit/build/python:/usr/local/lib:/usr/local/lib/python3.9/site-packages

# Make the launcher executable.
RUN chmod 0755 /opt/combine-run-mcp/docker-entrypoint.sh

# OpenShift runs the pod as a random, non-root UID in group 0. Make the
# dirs the server or ROOT may write to group-owned by 0 and
# group-writable, so an arbitrary UID can use them. (Per-run Combine
# workspaces live under /tmp, which is already world-writable.)
RUN chgrp -R 0 /home/cmsusr /code /opt/mcp-venv /opt/uv-python /opt/combine-run-mcp \
    && chmod -R g=u /home/cmsusr /code /opt/mcp-venv /opt/uv-python /opt/combine-run-mcp

USER cmsusr

EXPOSE 8000

# Explicit entrypoint to a real launcher script. A non-empty ENTRYPOINT
# reliably REPLACES the base image's `bash -l -c` entrypoint on every
# builder (an empty `ENTRYPOINT []` is honored by BuildKit but ignored by
# buildah, which OpenShift uses in-cluster — that mismatch causes a
# CrashLoopBackOff). The script strips PYTHONPATH/PYTHONHOME so the 3.11
# server interpreter stays clean, then execs the server; `combine` on PATH
# + LD_LIBRARY_PATH are inherited from the base image ENV, and the Python
# Combine tools (text2workspace.py, combineTool.py, combineCards.py) get
# their PyROOT PYTHONPATH re-injected per-subprocess via
# COMBINE_RUN_PYTHONPATH (see above), so Impacts and friends work too.
ENTRYPOINT ["/opt/combine-run-mcp/docker-entrypoint.sh"]
