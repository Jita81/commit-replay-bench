#!/bin/sh
# crb container entrypoint. First argument selects the role; the rest are passed through.
#
#   serve            HTTP API (+ built UI). uvicorn --factory crb.server.app:create_app
#   worker           queue consumer. python -m crb.server.worker_main
#   migrate [args]   python -m crb.store.migrate [upgrade|current|check] (default: upgrade)
#   check            alias for `migrate check` (exit 1 when migrations are pending)
#   shell            /bin/sh (debugging only; the image has no shell for the service user by
#                    default in Helm — see containerSecurityContext)
#   <anything else>  exec'd verbatim (e.g. `python -m crb.cli.main ledger verify`)
#
# Everything is `exec`'d so the role process is PID 1 and receives SIGTERM directly.
# Environment (see docs/DEPLOYMENT.md): CRB_DATABASE_URL, CRB_SECRET_KEY, CRB_BIND_HOST/PORT,
# CRB_FORWARDED_ALLOW_IPS, CRB_WEB_CONCURRENCY, CRB_MIGRATE_ON_START.
#
# Navigation
# ----------
# What it is:   The container entrypoint: one image, the role chosen by the first argument.
# What it does: Refuses to run any role while ``CRB_AUTH__DEV_AUTOLOGIN`` is set (ADR-0027);
#               ``serve`` runs uvicorn on the app factory (optionally migrating first under
#               ``CRB_MIGRATE_ON_START=1`` — single-host convenience only), ``worker`` the queue
#               consumer, ``migrate`` / ``check`` the Alembic CLI, ``shell`` a debugging shell,
#               anything else is exec'd verbatim. Every role is ``exec``'d so it is PID 1 and
#               receives SIGTERM directly.
# How:          A ``case`` on ``$1``; the bind host / port, worker count, forwarded IPs and graceful
#               timeout come from ``CRB_*`` environment variables with safe defaults.
# Layer:        deploy — docs/ARCHITECTURE.md#6-deployment-view
# ADRs:         docs/adr/0027-dev-autologin-on-loopback.md (the automatic sign-in refusal)
# Works with:   deploy/Dockerfile (installs it as ``crb-entrypoint`` and sets it as ENTRYPOINT),
#               deploy/docker-compose.yml and deploy/helm/crb/templates/api-deployment.yaml (pass
#               the role), src/crb/server/app.py (``create_app``), src/crb/server/worker_main.py,
#               src/crb/store/migrate.py, docs/DEPLOYMENT.md (the image and its roles, §2)
# Tested by:    tests/test_server_dev_autologin.py (the automatic sign-in refusal, with uvicorn
#               and python stubbed); the container smoke in .github/workflows/ci.yml runs the
#               ``migrate upgrade`` and ``migrate current`` roles through the built image
# Touch when:   a role is added to the image (a ``case`` arm, docs/DEPLOYMENT.md and the Helm
#               template that runs it); a uvicorn flag changes (keep ``--proxy-headers`` scoped to
#               ``CRB_FORWARDED_ALLOW_IPS``).

set -eu

# Automatic sign-in (ADR-0027) is for a development stack on one machine. A container is
# never that, and `uvicorn --factory --host` binds an address the settings never see, so the
# image refuses to run any role with it set, whatever CRB_BIND_HOST says. No override.
if [ -n "${CRB_AUTH__DEV_AUTOLOGIN:-}" ]; then
    echo "crb-entrypoint: refusing to start: CRB_AUTH__DEV_AUTOLOGIN is set, and automatic" \
        "sign-in is for a development stack on one machine, never a container" \
        "(docs/adr/0027-dev-autologin-on-loopback.md). Unset it." >&2
    exit 64
fi

role="${1:-serve}"
if [ "$#" -gt 0 ]; then
    shift
fi

case "$role" in
    serve)
        if [ "${CRB_MIGRATE_ON_START:-0}" = "1" ]; then
            # Single-host convenience only. In compose/Helm the dedicated migrate step runs
            # first and the API never holds DDL locks.
            python -m crb.store.migrate upgrade
        fi
        exec uvicorn --factory crb.server.app:create_app \
            --host "${CRB_BIND_HOST:-0.0.0.0}" \
            --port "${CRB_BIND_PORT:-8000}" \
            --workers "${CRB_WEB_CONCURRENCY:-1}" \
            --proxy-headers \
            --forwarded-allow-ips "${CRB_FORWARDED_ALLOW_IPS:-127.0.0.1}" \
            --no-server-header \
            --timeout-graceful-shutdown "${CRB_GRACEFUL_TIMEOUT_S:-20}" \
            "$@"
        ;;
    worker)
        exec python -m crb.server.worker_main "$@"
        ;;
    migrate)
        exec python -m crb.store.migrate "$@"
        ;;
    check)
        exec python -m crb.store.migrate check "$@"
        ;;
    shell)
        exec /bin/sh "$@"
        ;;
    *)
        exec "$role" "$@"
        ;;
esac
