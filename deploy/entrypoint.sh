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
set -eu

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
