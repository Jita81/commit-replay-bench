"""``crb serve`` / ``crb worker`` / ``crb doctor`` / ``crb migrate`` — the service verbs.

These import the server layer lazily: the core CLI must keep working on a host
that has only the base package installed (``pip install commit-replay-bench``
without the ``[server]`` extra).

Navigation
----------
What it is:   ``crb serve | worker | migrate | doctor`` — the service verbs, importing the
              server layer lazily so the base CLI works without the ``[server]`` extra.
What it does: ``serve`` hands off to uvicorn; ``worker`` forwards its flags to the worker
              entry point; ``migrate`` runs Alembic to head; ``doctor`` is one report, a named
              line per check with ``ok`` / ``warn`` / ``fail`` (``skip`` for a check that does
              not apply) and the fix in the sentence: toolchains, sandbox, builders, the Claude
              Code token store (its no-tool Haiku turn ONLY with ``--live``), the GitHub App
              (configured, key parses, one installation reachable), the server settings, the
              ``CRB_HOME`` location and the secrets directory mode and owner, the database
              (initialised, every append-only trigger present, an UPDATE refused), the
              migration head, the worker heartbeat and the built UI with its help bundle
              (exit 1 only on a fail). ``probe_claude_code`` never prints a token — a
              fingerprint of at most four characters.
How:          Each ``cmd_*`` imports inside the function and turns ``ImportError`` into a
              ``CliError`` naming the extra; ``doctor`` = ``probes.aggregate`` over the
              observability probes plus the server's ``probe_append_only`` (the trigger
              count AND the refused UPDATE, as ``/health`` reads it), the store's
              ``head_status`` rendered by the SAME ``migrations_result`` as ``/health``, the
              server's ``probe_worker``, ``temp_dir_reason`` and ``resolve_ui_dist``; the
              settings are read from the environment as ``crb serve`` would, or (when they
              would refuse) a dev-relaxed copy so the non-secret fields still read. The text
              form maps the shared vocabulary ``ok / degraded / down / skipped`` to
              ``ok / warn / fail / skip``; ``--json`` keeps the vocabulary ``/health`` uses.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/system.py (``migrations_result``, ``probe_append_only``
              and ``probe_worker`` — the same readings as ``/health``),
              src/crb/store/migrate.py (``upgrade``; ``head_status`` for the doctor line), src/crb/server/settings.py (``Settings``,
              ``temp_dir_reason``), src/crb/server/github_app.py (``GitHubApp`` — the
              installation listing), src/crb/server/app.py (``resolve_ui_dist``; ``serve``
              and ``worker`` hand off to src/crb/server/main.py and worker_main.py),
              src/crb/observability/probes.py (the probe vocabulary and ``aggregate``),
              src/crb/builders/claude_code.py (``auth_status`` / ``verify_login``),
              docs/OPERATOR.md#11-check-the-installation-crb-doctor
Tested by:    tests/test_cli_doctor.py, tests/test_cli.py
Touch when:   never for a new repository; when a worker flag is added (mirror it in the
              forwarding table and in src/crb/server/worker_main.py); when a new probe
              should appear in ``doctor``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.cli.commands import EXIT_OK, CliError

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker

    from crb.observability.probes import ProbeResult
    from crb.server.settings import GitHubAppSettings, Settings

_SERVER_HINT = "the server layer is not installed — `pip install 'commit-replay-bench[server]'`"

#: The guides the UI bundles as lazy chunks (``ui/src/help/docs.ts``; each lands in
#: ``ui/dist/assets/<NAME>-<hash>.js``). ``/help/docs/<NAME>`` is empty without its chunk.
HELP_GUIDES: tuple[str, ...] = (
    "ONBOARDING-A-REPO",
    "OPERATOR",
    "EVIDENCE-AND-CLAIMS",
    "GITHUB-APP",
    "SECURITY",
    "DATA-RETENTION",
    "LEARNING-LOOP",
    "DEPLOYMENT",
)
#: The text form's labels for the shared probe vocabulary (``--json`` keeps the vocabulary).
DOCTOR_LABELS: dict[str, str] = {
    "ok": "ok",
    "degraded": "warn",
    "down": "fail",
    "skipped": "skip",
}


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb serve``, ``crb worker``, ``crb migrate`` and ``crb doctor``."""
    serve = sub.add_parser("serve", help="run the HTTP API (+ the UI when built)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--database-url", default=None, help="overrides CRB_DATABASE_URL")
    serve.set_defaults(func=cmd_serve)

    mcp = sub.add_parser(
        "mcp",
        help="run the MCP server on stdio (Claude Code: `claude mcp add crb -- crb mcp`)",
    )
    mcp.add_argument("--list", action="store_true", help="print the tool names and exit")
    mcp.set_defaults(func=cmd_mcp)

    worker = sub.add_parser("worker", help="run the job worker (mine / replay / oracle / probe)")
    worker.add_argument("--database-url", default=None)
    worker.add_argument("--home", default=None, help="evidence + events dir (CRB_HOME)")
    worker.add_argument("--executor", choices=("local", "docker"), default=None)
    worker.add_argument("--image", default=None, help="sandbox image for --executor docker")
    worker.add_argument("--worker-id", default=None)
    worker.add_argument("--poll", type=float, default=None, help="seconds between queue polls")
    worker.add_argument("--once", action="store_true", help="process one job then exit")
    worker.set_defaults(func=cmd_worker)

    migrate = sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    migrate.add_argument("--database-url", default=None)
    migrate.set_defaults(func=cmd_migrate)

    doctor = sub.add_parser(
        "doctor",
        help="check the installation: toolchains, sandbox, builders, Claude Code login, GitHub "
        "App, settings, CRB_HOME, database, migration head, worker, UI + help bundle",
    )
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--database-url", default=None)
    doctor.add_argument(
        "--live",
        "--verify",
        dest="live",
        action="store_true",
        help="also run the Claude Code login probe — one no-tool Haiku turn on the stored "
        "token (~2 s when invalid); never run without this flag (--verify is the old name)",
    )
    doctor.set_defaults(func=cmd_doctor)


def cmd_serve(args: argparse.Namespace) -> int:
    """Block in uvicorn (``--database-url`` becomes ``CRB_DATABASE_URL`` for the app)."""
    if args.database_url:
        os.environ["CRB_DATABASE_URL"] = args.database_url
    try:
        from crb.server.main import serve
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    serve(host=args.host, port=args.port)
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    """The MCP server over the API named by ``CRB_API_URL`` (docs/MCP.md); ``--list``
    prints the tool names without connecting."""
    try:
        from crb.mcp.server import describe
        from crb.mcp.server import main as mcp_main
    except ImportError as e:
        raise CliError(f"the MCP server needs `pip install commit-replay-bench[mcp]` ({e})") from e
    if args.list:
        print(describe())
        return EXIT_OK
    return mcp_main()


def cmd_worker(args: argparse.Namespace) -> int:
    """Forward the flags to the worker entry point (which owns the defaults)."""
    try:
        import crb.server.worker_main as worker_main_mod
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    argv: list[str] = []
    for flag, value in (
        ("--database-url", args.database_url),
        ("--home", args.home),
        ("--executor", args.executor),
        ("--image", args.image),
        ("--worker-id", args.worker_id),
        ("--poll", args.poll),
    ):
        if value is not None:
            argv += [flag, str(value)]
    if args.once:
        argv.append("--once")
    return int(worker_main_mod.main(argv))


def cmd_migrate(args: argparse.Namespace) -> int:
    """Alembic to head (plus the append-only triggers) on the resolved URL."""
    try:
        import crb.store.migrate as migrate_mod
        from crb.store.db import database_url
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    url = database_url(args.database_url)
    migrate_mod.upgrade(url)
    print(f"migrated {url}")
    return EXIT_OK


def probe_claude_code(*, verify: bool = False) -> ProbeResult:
    """The ``claude_code`` builder's readiness for ``auth: cli``: where the login would
    come from (``env`` | ``secrets_file`` (…xxxx) | ``keychain`` | ``none``), whether
    ``claude`` is on PATH and its version, and — with ``verify`` — the real probe.

    ``down`` when the secrets file exists but is refused (group/world readable): that
    is a finding, not a nuisance. ``degraded`` when the CLI is missing, when neither a
    cli-mode login nor ``ANTHROPIC_API_KEY`` is available, or when the probe does not
    come back ``ok``. Never prints or returns a token; the fingerprint is ≤4 chars.
    """
    from crb.builders import claude_code as cc
    from crb.core.secrets_file import resolve_secrets_dir
    from crb.observability import probes

    source, fp, detail = cc.auth_status()
    version = cc.cli_version()
    cli_present = bool(version) or bool(shutil.which("claude"))
    data: dict[str, Any] = {
        "auth": source,
        "fingerprint": fp,
        "cli": cli_present,
        "cli_version": version,
        "secrets_dir": str(resolve_secrets_dir()),
        "api_key": bool(os.environ.get(cc.API_KEY_ENV, "").strip()),
    }
    label = {
        cc.TOKEN_SOURCE_ENV: "env",
        cc.TOKEN_SOURCE_SECRETS_FILE: f"secrets file (…{fp})" if fp else "secrets file",
        cc.TOKEN_SOURCE_KEYCHAIN: "keychain",
        cc.TOKEN_SOURCE_NONE: "none",
        cc.VERIFY_CLI_MISSING: "unknown (no CLI)",
        cc.VERIFY_ERROR: "REFUSED",
    }.get(source, source)
    parts = [f"auth: {label}"]
    if source == cc.VERIFY_ERROR:
        parts.append(detail)
    parts.append(f"claude {version}" if version else "claude: not on PATH")
    parts.append(f"secrets dir {data['secrets_dir']}")
    if source == cc.VERIFY_ERROR:
        status = probes.DOWN
    elif not cli_present:
        status = probes.DEGRADED
    elif source in {cc.TOKEN_SOURCE_NONE, cc.VERIFY_CLI_MISSING} and not data["api_key"]:
        status = probes.DEGRADED
        parts.append("no cli-mode login and no ANTHROPIC_API_KEY — run `claude setup-token`")
    else:
        status = probes.OK
    if verify and status != probes.DOWN:
        check = cc.verify_login()
        data["verify"] = check.to_dict()
        parts.append(f"verify: {check.status} ({check.duration_s:.1f}s)")
        if check.status != cc.VERIFY_OK:
            status = probes.DEGRADED
            if check.detail:
                parts.append(check.detail)
    return probes.ProbeResult("claude_code", status, " · ".join(parts), data)


def load_settings() -> tuple[Settings | None, str]:
    """The server settings as ``crb serve`` would read them — and, when they would refuse
    (``CRB_ENV=prod`` without ``CRB_SECRET_KEY`` on a bare shell, a temporary ``CRB_HOME``),
    a dev-relaxed copy so the non-secret fields (the GitHub App, the UI directory, the
    heartbeat threshold) still read. Returns ``(settings, refusal)``: ``refusal`` is the
    first validation message (``""`` when they construct), reported on the ``settings``
    line; ``settings`` is ``None`` only when even the relaxed copy refuses."""
    from pydantic import SecretStr, ValidationError

    from crb.server.settings import Settings

    try:
        return Settings(), ""
    except ValidationError as e:
        refusal = "; ".join(str(err.get("msg", "")) for err in e.errors()[:2])
    try:
        relaxed = Settings(env="dev", allow_temp_home=True, secret_key=SecretStr("x" * 32))
    except ValidationError:
        return None, refusal
    return relaxed, refusal


def probe_settings(settings: Settings | None, refusal: str) -> ProbeResult:
    """``settings``: would ``crb serve`` start with this environment? ``fail`` names the
    first refusal (the fix is in the message the settings raise)."""
    from crb.observability import probes

    if not refusal:
        assert settings is not None
        return probes.ProbeResult(
            "settings",
            probes.OK,
            f"CRB_ENV={settings.env} · home {settings.home} · database {settings.database_dialect}",
            {"env": settings.env, "home": str(settings.home)},
        )
    refusal = refusal.removeprefix("Value error, ")
    return probes.ProbeResult(
        "settings",
        probes.DOWN,
        f"the server would refuse to start: {refusal}",
        {"env": os.environ.get("CRB_ENV", "prod"), "refusal": refusal},
    )


def probe_home() -> ProbeResult:
    """``home``: where ``CRB_HOME`` resolves and whether the OS may delete it (DL-045 —
    ``fail`` in prod, ``warn`` in dev or with ``CRB_ALLOW_TEMP_HOME``), plus the secrets
    directory's mode and owner (``fail`` when group/world accessible or owned by another
    uid — ``SecretsStore._check_dir_for_write`` refuses both; mode alone is not enough)."""
    from crb.core.secrets_file import resolve_secrets_dir
    from crb.observability import probes
    from crb.server.settings import TEMP_HOME_ADVICE, temp_dir_reason

    home = Path(os.environ.get("CRB_HOME", ".crb")).expanduser()
    env = (os.environ.get("CRB_ENV") or "prod").strip().lower()
    allowed = (os.environ.get("CRB_ALLOW_TEMP_HOME") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    secrets_dir = resolve_secrets_dir()
    data: dict[str, Any] = {
        "home": str(home),
        "resolved": str(home.resolve()),
        "exists": home.is_dir(),
        "env": env,
        "secrets_dir": str(secrets_dir),
    }
    reason = temp_dir_reason(home)
    parts: list[str] = []
    status = probes.OK
    if reason:
        data["temporary"] = reason
        status = probes.DEGRADED if env == "dev" or allowed else probes.DOWN
        parts.append(f"CRB_HOME {reason} — {TEMP_HOME_ADVICE}")
    else:
        parts.append(f"CRB_HOME {home}" + ("" if home.is_dir() else " (not created yet)"))
    if secrets_dir.is_dir():
        st = secrets_dir.stat()
        mode = stat.S_IMODE(st.st_mode)
        me = os.geteuid()
        data["secrets_dir_mode"] = f"{mode:04o}"
        data["secrets_dir_uid"] = st.st_uid
        if mode & 0o077:
            status = probes.DOWN
            parts.append(
                f"secrets dir {secrets_dir} is mode {mode:04o} (group/world accessible) — "
                f"`chmod 0700 {secrets_dir}`"
            )
        elif st.st_uid != me:
            status = probes.DOWN
            parts.append(
                f"secrets dir {secrets_dir} is owned by uid {st.st_uid}, not the current user "
                f"(uid {me}) — the store refuses it; `chown {me} {secrets_dir}`"
            )
        else:
            parts.append(f"secrets dir {secrets_dir} mode {mode:04o}")
    else:
        parts.append(f"secrets dir {secrets_dir} (not created yet)")
    return probes.ProbeResult("home", status, " · ".join(parts), data)


def probe_github_app(
    github: GitHubAppSettings | None, client: httpx.Client | None = None
) -> ProbeResult:
    """``github_app``: not configured → ``skip`` (optional; the fix names the two settings);
    half configured or a key file that cannot be read → ``fail``; a key that does not parse
    (the app JWT cannot be minted) → ``fail``; GitHub refusing or unreachable → ``fail`` with
    GitHub's (redacted) message; reachable with no installation → ``warn`` (install it on
    an organisation); otherwise ``ok`` with the installations and how many can deliver.
    ``client`` is injectable (tests pass an ``httpx.MockTransport``)."""
    from crb.observability import probes

    if github is None:
        return probes.ProbeResult(
            "github_app", probes.DEGRADED, "not checked: the server settings refused (see above)"
        )
    app_id = github.app_id.strip()
    key_file = github.private_key_file.strip()
    inline = bool(github.private_key and github.private_key.get_secret_value().strip())
    data: dict[str, Any] = {
        "configured": github.enabled,
        "app_id": app_id,
        "app_slug": github.app_slug,
        "api_url": github.api_url,
        "key_source": "inline" if inline else ("file" if key_file else "none"),
    }
    if not app_id and not inline and not key_file:
        return probes.ProbeResult(
            "github_app",
            probes.SKIPPED,
            "not configured (optional) — set CRB_GITHUB__APP_ID and CRB_GITHUB__PRIVATE_KEY_FILE "
            "to connect repositories from GitHub (docs/GITHUB-APP.md)",
            data,
        )
    if key_file and not inline:
        data["key_file"] = key_file
        try:
            readable = bool(Path(key_file).expanduser().read_text(encoding="utf-8").strip())
        except OSError as e:
            readable = False
            data["key_file_error"] = e.strerror or type(e).__name__
        if not readable:
            why = data.get("key_file_error", "empty")
            return probes.ProbeResult(
                "github_app",
                probes.DOWN,
                f"CRB_GITHUB__PRIVATE_KEY_FILE={key_file} cannot be read ({why}) — mount the "
                "app's PEM there, readable by the user running crb",
                data,
            )
    if not github.enabled:
        missing = (
            "CRB_GITHUB__APP_ID" if not app_id else "a private key (CRB_GITHUB__PRIVATE_KEY_FILE)"
        )
        return probes.ProbeResult(
            "github_app",
            probes.DOWN,
            f"half configured: {missing} is missing — the app needs both (docs/GITHUB-APP.md §2)",
            data,
        )
    from crb.server.github_app import GitHubApp, GitHubAppError

    app = GitHubApp(github, client, timeout_s=10.0)
    try:
        app.app_jwt()
    except Exception as e:  # authlib raises its own hierarchy for a malformed key
        return probes.ProbeResult(
            "github_app",
            probes.DOWN,
            f"the private key does not parse as the app's RSA PEM ({type(e).__name__}) — "
            "download a fresh key from the app's settings page (docs/GITHUB-APP.md §2)",
            data,
        )
    try:
        installations = app.installations()
    except GitHubAppError as e:
        data["github_status"] = e.status
        return probes.ProbeResult(
            "github_app",
            probes.DOWN,
            f"app {app_id}: {e} — check the app id, the key, CRB_GITHUB__API_URL and egress "
            f"to {github.api_url}",
            data,
        )
    data["installations"] = [i.to_dict() for i in installations]
    if not installations:
        return probes.ProbeResult(
            "github_app",
            probes.DEGRADED,
            f"app {app_id} reachable, no installation yet — install it on an organisation "
            f"(Settings → GitHub App, or {github.install_url or 'docs/GITHUB-APP.md §3'})",
            data,
        )
    names = ", ".join(i.account_login for i in installations[:5])
    deliver = sum(1 for i in installations if i.can_deliver)
    n = len(installations)
    return probes.ProbeResult(
        "github_app",
        probes.OK,
        f"app {app_id}: {n} installation{'s' if n != 1 else ''} ({names}) · {deliver} can deliver",
        data,
    )


def probe_ui(settings: Settings | None) -> ProbeResult:
    """``ui``: the built UI the API would serve (``CRB_UI_DIST``, else ``ui/dist`` /
    ``/app/ui/dist``) and whether the help bundle is in it — one lazy chunk per guide
    (``assets/<NAME>-<hash>.js``, a non-empty regular file: a zero-byte chunk serves an
    empty page); without them ``/help/docs/<NAME>`` is empty."""
    from crb.observability import probes

    if settings is None:
        return probes.ProbeResult(
            "ui", probes.DEGRADED, "not checked: the server settings refused (see above)"
        )
    from crb.server.app import resolve_ui_dist

    dist = resolve_ui_dist(settings)
    if dist is None:
        return probes.ProbeResult(
            "ui",
            probes.DEGRADED,
            "no built UI (CRB_UI_DIST unset and ui/dist absent): the API serves no screens and "
            "/help is empty — `npm --prefix ui run build`, or set CRB_UI_DIST",
            {"dist": None, "ui_dist_setting": settings.ui_dist},
        )
    missing = [
        g for g in HELP_GUIDES if not any(map(_is_chunk, (dist / "assets").glob(f"{g}-*.js")))
    ]
    data = {"dist": str(dist), "guides": len(HELP_GUIDES), "missing_guides": missing}
    if missing:
        return probes.ProbeResult(
            "ui",
            probes.DEGRADED,
            f"UI at {dist} · help bundle incomplete: {len(HELP_GUIDES) - len(missing)}/"
            f"{len(HELP_GUIDES)} guides, missing {', '.join(missing)} — rebuild the UI from "
            "this checkout (`npm --prefix ui run build`)",
            data,
        )
    return probes.ProbeResult(
        "ui",
        probes.OK,
        f"UI at {dist} · {len(HELP_GUIDES)}/{len(HELP_GUIDES)} help guides bundled",
        data,
    )


def _is_chunk(path: Path) -> bool:
    """A built chunk: a regular file with bytes in it (not a directory, not zero-byte)."""
    try:
        st = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size > 0


def probe_database(engine: Engine, factory: sessionmaker[Session], url: str) -> ProbeResult:
    """``database``: the store answers and is initialised (``grades`` exists), and the
    append-only guarantee holds the way ``/health`` proves it — ``probe_append_only``:
    every trigger present (counted against ``APPEND_ONLY_TABLES``) AND an UPDATE on
    ``grades`` refused. ``assert_append_only`` alone returns on an empty ``grades`` table,
    which would pass a store whose triggers were never installed."""
    from sqlalchemy import inspect

    from crb.observability import probes
    from crb.server.routes.system import probe_append_only

    data: dict[str, Any] = {"url": _redact_url(url)}
    try:
        initialised = "grades" in inspect(engine).get_table_names()
    except Exception as exc:
        return probes.ProbeResult("database", probes.DOWN, f"{type(exc).__name__}: {exc}", data)
    if not initialised:
        return probes.ProbeResult(
            "database", probes.DOWN, "database not initialised — run `crb migrate`", data
        )
    ao = probe_append_only(factory)
    data.update(ao.data)
    if ao.status != probes.OK:
        return probes.ProbeResult("database", probes.DOWN, f"{ao.detail} — run `crb migrate`", data)
    return probes.ProbeResult("database", probes.OK, f"answers · {ao.detail}", data)


def cmd_doctor(args: argparse.Namespace) -> int:
    """One report over every readiness probe; exit 1 only when something is ``down``
    (``fail`` in the text form)."""
    from crb.observability import probes

    results = [
        probes.probe_toolchains(),
        probes.probe_docker(),
        probes.probe_builders(),
        probe_claude_code(verify=bool(getattr(args, "live", False))),
    ]
    try:
        from crb.server.routes.system import migrations_result, probe_worker
        from crb.store import migrate as migrate_mod
        from crb.store.db import database_url, make_engine, make_session_factory
    except ImportError:
        results.append(probes.ProbeResult("database", probes.DEGRADED, _SERVER_HINT))
        return _finish_doctor(results, as_json=bool(args.json))

    settings, refusal = load_settings()
    results.append(probe_settings(settings, refusal))
    results.append(probe_home())
    results.append(probe_github_app(settings.github if settings else None))

    url = database_url(args.database_url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    try:
        db = probe_database(engine, factory, url)
        results.append(db)

        def _head() -> probes.ProbeResult:
            with engine.connect() as connection:
                return migrations_result(migrate_mod.head_status_on(connection))

        try:
            results.append(_head())
        except Exception as exc:
            results.append(
                probes.ProbeResult("migrations", probes.DOWN, f"{type(exc).__name__}: {exc}")
            )
        stale_s = settings.worker_heartbeat_stale_s if settings else 120
        if db.status == probes.OK:
            results.append(probe_worker(factory, stale_s))
        else:
            results.append(
                probes.ProbeResult(
                    "worker", probes.DEGRADED, "not checked: the database line failed"
                )
            )
    finally:
        engine.dispose()
    results.append(probe_ui(settings))
    return _finish_doctor(results, as_json=bool(args.json))


def _finish_doctor(results: list[ProbeResult], *, as_json: bool) -> int:
    """Render the report (``--json``: the ``/health`` shape; text: one labelled line per
    probe, ``ok / warn / fail / skip``) and return the exit code."""
    from crb.observability import probes

    report = probes.aggregate(results)
    if as_json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        for r in report["probes"]:
            label = DOCTOR_LABELS.get(r["status"], r["status"])
            print(f"{label:>6}  {r['name']:<12} {r['detail']}")
        print(f"\noverall: {DOCTOR_LABELS.get(report['status'], report['status'])}")
    return EXIT_OK if report["status"] != probes.DOWN else 1


def _redact_url(url: str) -> str:
    """A database URL with its password replaced (the user name is kept)."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:[REDACTED]@{host}"
    return url


__all__: Sequence[str] = (
    "DOCTOR_LABELS",
    "HELP_GUIDES",
    "load_settings",
    "probe_claude_code",
    "probe_github_app",
    "probe_home",
    "probe_settings",
    "probe_ui",
    "register",
)
