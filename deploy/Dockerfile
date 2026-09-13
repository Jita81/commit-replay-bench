# syntax=docker/dockerfile:1.7
#
# Commit Replay Bench (crb) — production image. Build from the REPOSITORY ROOT:
#
#     docker build -f deploy/Dockerfile -t crb:local .
#
# One image, three roles, selected by the first argument to the entrypoint:
#     serve    uvicorn --factory crb.server.app:create_app   (HTTP API + the built UI)
#     worker   python -m crb.server.worker_main              (queue consumer: mine → build → grade)
#     migrate  python -m crb.store.migrate upgrade           (alembic upgrade head; one-shot)
#
# Stages
#   ui-builder   node — builds ui/ → ui/dist IF the build context has ui/package.json
#                (the UI lands in a parallel workstream; without it the image is API-only)
#   uv / cli     pinned tool images we copy single binaries out of (uv, docker CLI)
#   runtime      python:3.12-slim, non-root user crb (uid/gid 10001), venv under /app/.venv,
#                read-only-root-compatible (writable paths: /tmp, /home/crb, $CRB_HOME)
#
# Security posture (see docs/DEPLOYMENT.md):
#   * runs as uid 10001, no shell for the user, no setuid helpers installed;
#   * the docker CLI is present (client ONLY — no daemon). The worker needs a daemon socket to
#     create sandbox containers; mounting it is an explicit opt-in in compose / Helm values,
#     never a default. Without it the executor fails CLOSED (runs become `blocked`);
#   * base images are pinned by exact tag; nothing is `latest`. Re-pin via the ARGs below.
#   * secrets arrive ONLY through the environment at run time (CRB_SECRET_KEY, CRB_DATABASE_URL,
#     model API keys); nothing secret is baked into a layer.

ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm
ARG NODE_IMAGE=node:22.19.0-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.13
ARG DOCKER_CLI_IMAGE=docker:28.4.0-cli

# ---------------------------------------------------------------------------
# Stage 1 — UI build (tolerant: the UI directory may not exist yet)
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS ui-builder
WORKDIR /src
# The whole (dockerignored) context is copied because `COPY ui/ …` would fail the build when
# ui/ is absent; the runtime stage copies only ui/dist out of this stage.
COPY . /src/
RUN set -eu; \
    if [ -f ui/package.json ]; then \
        npm ci --prefix ui --no-audit --no-fund && npm run build --prefix ui && test -d ui/dist; \
    else \
        mkdir -p ui/dist && printf 'no ui/ in build context: API-only image\n' > ui/dist/.no-ui; \
    fi

# ---------------------------------------------------------------------------
# Tool stages — copy single pinned binaries, no package-manager churn at runtime
# ---------------------------------------------------------------------------
FROM ${UV_IMAGE} AS uv
FROM ${DOCKER_CLI_IMAGE} AS docker-cli

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG CRB_UID=10001
ARG CRB_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

# git: the core clones / creates worktrees. ca-certificates: TLS to the model endpoint and
# the OIDC issuer. Nothing else — no curl, no build tools, no shells for the service user.
# Debian security updates roll the exact versions; pinning them here would make the build
# fail the day a mirror drops the old package, so we track the pinned base image instead.
# hadolint ignore=DL3008
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid "${CRB_GID}" crb; \
    useradd --uid "${CRB_UID}" --gid "${CRB_GID}" --create-home --home-dir /home/crb \
            --shell /usr/sbin/nologin crb

COPY --from=uv /uv /usr/local/bin/uv
# Docker CLIENT only (static binary). Talks to a daemon only if a socket is mounted.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

# Dependency layer: resolved from pyproject.toml alone so it caches independently of src/.
COPY pyproject.toml README.md LICENSE /app/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    set -eu; \
    uv venv /app/.venv --python /usr/local/bin/python3; \
    UV_NO_CACHE=0 uv pip install --python /app/.venv/bin/python \
        -r /app/pyproject.toml --extra server --extra postgres

# The package itself (non-editable; alembic.ini + migrations ship inside the wheel).
COPY src/ /app/src/
RUN uv pip install --python /app/.venv/bin/python --no-deps /app \
    && /app/.venv/bin/python -c "import crb.store.migrate, crb.core; print('crb import ok')" \
    && rm -rf /app/src /app/build

# The built UI (or the .no-ui marker) and the entrypoint.
COPY --from=ui-builder /src/ui/dist/ /app/ui/dist/
COPY deploy/entrypoint.sh /usr/local/bin/crb-entrypoint

# Writable state root. Bind-mount or PVC it; everything else can be read-only.
RUN set -eu; \
    chmod 0755 /usr/local/bin/crb-entrypoint; \
    mkdir -p /srv/crb; \
    chown "${CRB_UID}:${CRB_GID}" /srv/crb; \
    chmod 0750 /srv/crb

ENV PATH="/app/.venv/bin:${PATH}" \
    HOME=/home/crb \
    CRB_HOME=/srv/crb \
    CRB_UI_DIST=/app/ui/dist \
    CRB_BIND_HOST=0.0.0.0 \
    CRB_BIND_PORT=8000 \
    CRB_LOG_FORMAT=json

USER ${CRB_UID}:${CRB_GID}
EXPOSE 8000

# Liveness for the `serve` role. The worker role disables this in compose / uses its own
# heartbeat in the runs table (see docs/DEPLOYMENT.md).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('CRB_BIND_PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/v1/health', timeout=4).status==200 else 1)"]

ENTRYPOINT ["crb-entrypoint"]
CMD ["serve"]
