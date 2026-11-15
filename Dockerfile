# Ouroboros — Docker images for the web UI runtime
# Usage (recipes: packaging/docker/compose.yaml, explained in docs/DEPLOYMENT.md):
#   docker build -t ouroboros-web .
#   docker run --rm -p 8765:8765 ouroboros-web
# The RUN --mount caches and --build-context need BuildKit, Docker's default builder.

FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

# CPython 3.10.22 and SQLite 3.53.1 from python-build-standalone 20261009:
# the same install_only_stripped assets as scripts/download_python_standalone.sh.
# Debian python:3.10-slim froze on SQLite 3.46.1. This build links only glibc
# (floor 2.17); OpenSSL and SQLite are inside it.
FROM debian:trixie-slim AS python-standalone
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && case "${TARGETARCH}" in \
         amd64) PLATFORM="x86_64-unknown-linux-gnu"; SHA256="caa66b308e10f35b8114054df7d927903f971f631cfa3237b84c40d5d5f35549" ;; \
         arm64) PLATFORM="aarch64-unknown-linux-gnu"; SHA256="ecbe978a7ecbeb3a9aed67bb5d161180701513b4fa8101037b2a3f1ac11e96be" ;; \
         *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && FILENAME="cpython-3.10.22+20261009-${PLATFORM}-install_only_stripped.tar.gz" \
    && curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/${FILENAME}" -o /tmp/python.tar.gz \
    && echo "${SHA256}  /tmp/python.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/python-standalone \
    && tar -xzf /tmp/python.tar.gz -C /opt/python-standalone --strip-components=1 \
    && rm /tmp/python.tar.gz \
    && /opt/python-standalone/bin/python3 -c "import sqlite3,sys; version=sys.version.split()[0]; sqlite=tuple(int(part) for part in sqlite3.sqlite_version.split('.')); assert version=='3.10.22', version; assert sqlite>=(3, 51, 3), sqlite3.sqlite_version"

FROM debian:trixie-slim AS runtime

COPY --from=uv /uv /uvx /bin/
COPY --from=python-standalone /opt/python-standalone /opt/python-standalone

# Browsers first, dependencies second, sources last: every release rewrites
# pyproject.toml/uv.lock, so anything below the lock copy is rebuilt per
# release while the apt packages and the Chromium/WebKit downloads above it
# are reused. The Playwright pin must equal the locked version so the
# downloaded browser revisions match the venv's driver
# (tests/test_build_scripts.py::TestDockerfile). The installer runs from an
# ephemeral uvx tool environment, so the image carries one Playwright: the
# venv's. Browsers live in a shared path the runtime honors as-is
# (ouroboros/tools/browser.py) — not inside the package tree, which the
# per-release dependency layer would rebuild.
ARG PLAYWRIGHT_VERSION=1.62.0
ENV PATH="/opt/python-standalone/bin:${PATH}" \
    LANG=C.UTF-8 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# System dependencies: what the python:3.10-slim base used to carry (CA
# certificates for HTTPS and git, netbase, tzdata), git for the agent's own
# history and updates, plus every Chromium/WebKit native library from
# Playwright's authoritative list.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg git netbase tzdata \
    && uvx --from "playwright==${PLAYWRIGHT_VERSION}" playwright install-deps chromium webkit \
    && uvx --from "playwright==${PLAYWRIGHT_VERSION}" playwright install chromium webkit

# Working directory
ENV APP_HOME=/app \
    PATH="/app/.venv/bin:$PATH"
WORKDIR ${APP_HOME}

# Resolve only from the reviewed lock; the project itself is installed after
# the source copy so source edits reuse this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --python /opt/python-standalone/bin/python3 --no-dev --extra browser --no-install-project

# Copy application
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --python /opt/python-standalone/bin/python3 --no-dev --extra browser --no-editable

# Yourmung fork: optional transcription stack, off by default (build args).
#   --build-arg OUROBOROS_INSTALL_TRANSCRIPTION=1  faster-whisper (local STT)
#   --build-arg OUROBOROS_INSTALL_DIARIZATION=1    pyannote speaker diarization (large: PyTorch)
#   --build-arg OUROBOROS_INSTALL_WHISPERX=1       WhisperX forced alignment (large: PyTorch)
#   --build-arg OUROBOROS_INSTALL_TRACING=1        Phoenix/OpenInference tracing
ARG OUROBOROS_INSTALL_TRANSCRIPTION=0
ARG OUROBOROS_INSTALL_DIARIZATION=0
ARG OUROBOROS_INSTALL_WHISPERX=0
ARG OUROBOROS_INSTALL_TRACING=0
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$OUROBOROS_INSTALL_TRANSCRIPTION" = "1" ]; then \
         uv pip install --python /app/.venv/bin/python "faster-whisper==1.2.1"; \
       fi \
    && if [ "$OUROBOROS_INSTALL_DIARIZATION" = "1" ]; then \
         uv pip install --python /app/.venv/bin/python -r requirements-diarization.txt; \
       fi \
    && if [ "$OUROBOROS_INSTALL_WHISPERX" = "1" ]; then \
         uv pip install --python /app/.venv/bin/python -r requirements-whisperx.txt; \
       fi \
    && if [ "$OUROBOROS_INSTALL_TRACING" = "1" ]; then \
         uv pip install --python /app/.venv/bin/python "arize-phoenix-otel>=0.16.1,<0.17.0" "openinference-instrumentation-openai>=0.1.52,<0.2.0"; \
       fi

# Default environment
ENV OUROBOROS_SERVER_HOST=0.0.0.0 \
    OUROBOROS_SERVER_PORT=8765 \
    OUROBOROS_FILE_BROWSER_DEFAULT=${APP_HOME}

EXPOSE 8765

ENTRYPOINT ["python", "server.py"]

# The ordinary immutable image stays the default target.
FROM runtime
