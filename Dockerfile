FROM python:3.12-slim AS base

# git is needed for scanner's `git log -1 --format=%cI` and for the
# in-tree origin URL parsing on mounted repos. Node + npm-installed
# Claude Code CLI handles the actual subprocess we spawn.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY pub_auditor ./pub_auditor
RUN pip install --no-cache-dir -e .

# Default bind for container deployments — see SECURITY.md for the
# AUDITOR_TOKEN requirement when host != loopback.
ENV AUDITOR_HOST=0.0.0.0 \
    AUDITOR_PORT=6020 \
    AUDITOR_REPOS_DIR=/work \
    AUDITOR_AUDIT_LOG_PATH=/data/audit.log
EXPOSE 6020

# Non-root for safety. /work and /data are intended as bind-mount
# targets; the operator owns them on the host side.
RUN useradd --uid 1000 --shell /bin/bash --create-home auditor \
 && mkdir -p /work /data \
 && chown -R auditor:auditor /work /data
USER auditor

CMD ["python", "-m", "pub_auditor.server"]
