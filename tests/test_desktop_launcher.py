"""The desktop launcher's promises: persisted secrets, absolute paths, and an honest ready signal.

Hermetic by construction — a throwaway home under ``tmp_path``, a fake ``crb`` that is never
executed, and a readiness poll driven by injected clocks and probes. No server is started and
no socket is dialled beyond binding a loopback port to see whether it is free.

Navigation
----------
What it is:   The test suite for ``crb.desktop`` — the launcher that turns crb into a local
              application.
What it does: Pins that the secret key and administrator password are generated once,
              persisted 0600 and reused on every later launch; that ``CRB_HOME`` is always
              absolute and never contains a tilde on either platform; that the child
              environment carries every variable ``crb serve`` needs; that pre-flight
              detects a missing ``git`` and names ``xcode-select --install``; that a free
              port is chosen; and that the readiness poll asks ``/api/v1/health/live`` and
              returns False — promptly — when the child exits.
How:          ``tmp_path`` for the state directory, ``monkeypatch`` for ``HOME`` and
              ``sys.platform``, injected ``which`` / ``probe`` / ``sleep`` / ``clock``
              callables for the checks and the poll.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/config.py (the persisted secrets and the environment),
              src/crb/desktop/paths.py (the state directory and the executable),
              src/crb/desktop/server.py (ports and readiness),
              src/crb/desktop/preflight.py (the checks and their remedies),
              src/crb/server/settings.py (the variables the environment must satisfy)
Tested by:    tests/test_desktop_launcher.py
Touch when:   a variable is added to the desktop environment, the readiness endpoint moves,
              or a pre-flight check is added — each needs a case here.
"""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from crb.desktop import config, paths, preflight, server

REQUIRED_ENVIRONMENT_KEYS = (
    "CRB_HOME",
    "CRB_SECRET_KEY",
    "CRB_ENV",
    "CRB_COOKIE_SECURE",
    "CRB_UI_DIST",
    "CRB_ROLE",
    "CRB_SANDBOX__EXECUTOR",
    "CRB_BOOTSTRAP_ADMIN__USERNAME",
    "CRB_BOOTSTRAP_ADMIN__PASSWORD",
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _admin(home: Path) -> config.AdminCredentials:
    return config.ensure_admin_credentials(home)


# --- persisted secrets ---------------------------------------------------------------------


def test_secret_key_is_persisted_and_reused_across_launches(tmp_path: Path) -> None:
    first = config.ensure_secret_key(tmp_path)
    second = config.ensure_secret_key(tmp_path)
    assert first == second
    assert (tmp_path / config.SECRET_KEY_FILE).read_text(encoding="utf-8").strip() == first


def test_secret_key_is_long_enough_for_the_server_to_accept_it(tmp_path: Path) -> None:
    assert len(config.ensure_secret_key(tmp_path)) >= config.MIN_SECRET_KEY_LENGTH


def test_secret_key_file_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    config.ensure_secret_key(tmp_path)
    assert _mode(tmp_path / config.SECRET_KEY_FILE) == 0o600


def test_a_secret_key_file_left_world_readable_is_hardened_on_the_next_launch(
    tmp_path: Path,
) -> None:
    config.ensure_secret_key(tmp_path)
    (tmp_path / config.SECRET_KEY_FILE).chmod(0o644)
    config.ensure_secret_key(tmp_path)
    assert _mode(tmp_path / config.SECRET_KEY_FILE) == 0o600


def test_a_truncated_secret_key_is_refused_rather_than_used(tmp_path: Path) -> None:
    (tmp_path / config.SECRET_KEY_FILE).write_text("short\n", encoding="utf-8")
    with pytest.raises(config.DesktopConfigError):
        config.ensure_secret_key(tmp_path)


def test_admin_password_is_long_enough_and_stable_across_calls(tmp_path: Path) -> None:
    first = _admin(tmp_path)
    second = _admin(tmp_path)
    assert len(first.password) >= config.MIN_ADMIN_PASSWORD_LENGTH
    assert first.password == second.password
    assert first.username == second.username == config.ADMIN_USERNAME


def test_admin_credentials_are_generated_once_and_then_read_back(tmp_path: Path) -> None:
    assert _admin(tmp_path).created is True
    assert _admin(tmp_path).created is False


def test_admin_credentials_file_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    assert _mode(_admin(tmp_path).path) == 0o600


def test_secret_files_are_never_world_readable_even_for_an_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: dict[str, int] = {}
    real_open = os.open

    def recording_open(path: str, flags: int, mode: int = 0o777) -> int:
        modes[str(path)] = mode
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", recording_open)
    config.ensure_secret_key(tmp_path)
    _admin(tmp_path)
    monkeypatch.undo()
    assert modes[str(tmp_path / config.SECRET_KEY_FILE)] == 0o600
    assert modes[str(tmp_path / config.CREDENTIALS_FILE)] == 0o600


def test_an_unparseable_credentials_file_is_refused_rather_than_used(tmp_path: Path) -> None:
    (tmp_path / config.CREDENTIALS_FILE).write_text("nothing useful here\n", encoding="utf-8")
    with pytest.raises(config.DesktopConfigError):
        _admin(tmp_path)


# --- the state directory -------------------------------------------------------------------


def test_state_home_on_macos_is_the_application_support_directory(tmp_path: Path) -> None:
    home = paths.state_home(env={"HOME": str(tmp_path)}, platform="darwin")
    assert home == tmp_path.resolve() / "Library" / "Application Support" / "crb"


def test_state_home_elsewhere_follows_the_xdg_data_directory(tmp_path: Path) -> None:
    default = paths.state_home(env={"HOME": str(tmp_path)}, platform="linux")
    configured = paths.state_home(
        env={"HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path / "data")}, platform="linux"
    )
    assert default == tmp_path.resolve() / ".local" / "share" / "crb"
    assert configured == tmp_path.resolve() / "data" / "crb"


def test_crb_home_is_always_absolute_and_never_contains_a_tilde(tmp_path: Path) -> None:
    for env in (
        {"HOME": str(tmp_path)},
        {"HOME": str(tmp_path), "CRB_HOME": "~/somewhere/crb"},
        {"HOME": str(tmp_path), "CRB_HOME": "relative/crb"},
        {"HOME": str(tmp_path), "XDG_DATA_HOME": "~/xdg"},
    ):
        for platform in ("darwin", "linux"):
            home = paths.state_home(env=env, platform=platform)
            assert home.is_absolute()
            assert "~" not in str(home)


def test_an_explicit_crb_home_wins_over_the_platform_default(tmp_path: Path) -> None:
    home = paths.state_home(
        env={"HOME": str(tmp_path), "CRB_HOME": str(tmp_path / "elsewhere")}, platform="darwin"
    )
    assert home == (tmp_path / "elsewhere").resolve()


def test_the_state_directory_is_created_private_to_its_owner(tmp_path: Path) -> None:
    home = paths.ensure_state_home(tmp_path / "state" / "crb")
    assert home.is_dir()
    assert _mode(home) == 0o700


# --- finding crb and the interface ---------------------------------------------------------


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_a_crb_beside_the_interpreter_is_preferred_over_the_one_on_the_path(
    tmp_path: Path,
) -> None:
    bundled = _executable(tmp_path / "bin" / "crb")
    other = _executable(tmp_path / "elsewhere" / "crb")
    found = paths.resolve_crb_binary(
        env={"PATH": str(other.parent), paths.CRB_BIN_ENV: str(other)},
        executable=str(tmp_path / "bin" / "python3"),
    )
    assert found == bundled.resolve()


def test_the_environment_override_names_the_crb_to_run(tmp_path: Path) -> None:
    override = _executable(tmp_path / "override" / "crb")
    found = paths.resolve_crb_binary(
        env={paths.CRB_BIN_ENV: str(override)},
        executable=str(tmp_path / "empty" / "python3"),
    )
    assert found == override.resolve()


def test_no_crb_anywhere_is_reported_as_none_rather_than_guessed(tmp_path: Path) -> None:
    found = paths.resolve_crb_binary(
        env={"PATH": str(tmp_path / "empty")}, executable=str(tmp_path / "empty" / "python3")
    )
    assert found is None


def test_the_interface_directory_must_hold_an_index_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "repo_ui_dist", lambda: tmp_path / "no-checkout" / "dist")
    empty = tmp_path / "empty-ui"
    empty.mkdir()
    built = tmp_path / "built-ui"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html>", encoding="utf-8")
    executable = str(tmp_path / "nowhere" / "bin" / "python3")
    assert paths.resolve_ui_dist(env={paths.UI_DIST_ENV: str(empty)}, executable=executable) is None
    assert (
        paths.resolve_ui_dist(env={paths.UI_DIST_ENV: str(built)}, executable=executable)
        == built.resolve()
    )


def test_the_interface_is_found_in_the_bundle_without_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layout macos/build_app.sh writes, resolved with no ``CRB_UI_DIST`` to lean on.

    The launcher always exports the variable, so this candidate is only reached on the day
    that export is missed — which is exactly when a wrong guess would be invisible. The SPA
    sits at ``Contents/Resources/ui``, one level ABOVE the embedded runtime, because it is
    not part of the Python installation.
    """
    monkeypatch.setattr(paths, "repo_ui_dist", lambda: tmp_path / "no-checkout" / "dist")
    resources = tmp_path / "crb.app" / "Contents" / "Resources"
    interpreter = resources / "python" / "bin" / "python3"
    interpreter.parent.mkdir(parents=True)
    spa = resources / "ui"
    spa.mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html>", encoding="utf-8")

    assert paths.resolve_ui_dist(env={}, executable=str(interpreter)) == spa.resolve()


# --- the child environment -----------------------------------------------------------------


def _environment(tmp_path: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    ui_dist = tmp_path / "ui"
    ui_dist.mkdir(exist_ok=True)
    return config.build_environment(
        home=tmp_path,
        ui_dist=ui_dist,
        secret_key=config.ensure_secret_key(tmp_path),
        admin=_admin(tmp_path),
        base={} if base is None else base,
    )


def test_the_child_environment_carries_every_variable_the_server_needs(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    assert set(REQUIRED_ENVIRONMENT_KEYS) <= set(env)
    assert all(env[key] for key in REQUIRED_ENVIRONMENT_KEYS)


def test_the_child_environment_keeps_production_settings_with_insecure_cookies(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    assert env["CRB_ENV"] == "prod"
    assert env["CRB_COOKIE_SECURE"] == "false"
    assert env["CRB_ROLE"] == "api"
    assert env["CRB_SANDBOX__EXECUTOR"] == "local"


def test_the_child_environment_overrides_a_conflicting_inherited_value(tmp_path: Path) -> None:
    env = _environment(tmp_path, base={"CRB_ENV": "dev", "CRB_COOKIE_SECURE": "true", "TERM": "x"})
    assert env["CRB_ENV"] == "prod"
    assert env["CRB_COOKIE_SECURE"] == "false"
    assert env["TERM"] == "x"


def test_the_child_environment_never_hands_over_a_relative_or_tilde_path(tmp_path: Path) -> None:
    env = config.build_environment(
        home=Path("~/state/crb"),
        ui_dist=Path("ui/dist"),
        secret_key="k" * config.MIN_SECRET_KEY_LENGTH,
        admin=_admin(tmp_path),
        base={},
    )
    for key in ("CRB_HOME", "CRB_UI_DIST"):
        assert Path(env[key]).is_absolute()
        assert "~" not in env[key]


def test_the_admin_password_reaches_the_child_as_the_bootstrap_password(tmp_path: Path) -> None:
    admin = _admin(tmp_path)
    env = _environment(tmp_path)
    assert env["CRB_BOOTSTRAP_ADMIN__PASSWORD"] == admin.password
    assert env["CRB_BOOTSTRAP_ADMIN__USERNAME"] == admin.username


# --- pre-flight ----------------------------------------------------------------------------


def test_preflight_detects_a_missing_git_and_names_the_remedy() -> None:
    finding = preflight.check_git(lambda _name: None)
    assert finding.ok is False
    assert "xcode-select --install" in finding.remedy


def test_a_missing_git_warns_but_does_not_block_the_launch() -> None:
    finding = preflight.check_git(lambda _name: None)
    assert finding.blocking is False
    assert "503" in finding.detail


def test_preflight_is_satisfied_by_a_git_on_the_path() -> None:
    assert preflight.check_git(lambda _name: "/usr/bin/git").ok is True


def test_preflight_blocks_on_a_missing_crb_or_a_missing_interface() -> None:
    report = preflight.run_preflight(crb_bin=None, ui_dist=None, which=lambda _name: "/usr/bin/git")
    assert report.ok is False
    assert {finding.name for finding in report.blockers} == {"crb", "interface"}
    assert all(finding.remedy for finding in report.blockers)


def test_a_fully_equipped_machine_passes_preflight_without_findings(tmp_path: Path) -> None:
    ui_dist = tmp_path / "ui"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    report = preflight.run_preflight(
        crb_bin=_executable(tmp_path / "bin" / "crb"),
        ui_dist=ui_dist,
        which=lambda _name: "/usr/bin/git",
    )
    assert report.ok is True
    assert report.blockers == ()
    assert len(report.lines()) == 3


# --- ports ---------------------------------------------------------------------------------


def test_the_preferred_port_is_used_when_it_is_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((server.LOOPBACK_HOST, 0))
        free = int(probe.getsockname()[1])
    assert server.choose_port(preferred=free) == free


def test_a_taken_port_is_replaced_by_a_free_one() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind((server.LOOPBACK_HOST, 0))
        taken.listen(1)
        port = int(taken.getsockname()[1])
        assert server.port_is_free(port) is False
        chosen = server.choose_port(preferred=port)
    assert chosen != port
    assert server.port_is_free(chosen) is True


# --- readiness -----------------------------------------------------------------------------


def _exited(status: int = 2) -> SimpleNamespace:
    """A child process that is already gone."""
    return SimpleNamespace(poll=lambda: status)


def _running() -> SimpleNamespace:
    """A child process that never exits."""
    return SimpleNamespace(poll=lambda: None)


def test_the_readiness_url_is_the_liveness_endpoint_not_the_spa_catch_all() -> None:
    assert server.READINESS_PATH == "/api/v1/health/live"
    assert server.readiness_url(8765) == "http://127.0.0.1:8765/api/v1/health/live"


def test_the_readiness_poll_returns_false_when_the_child_exits_immediately() -> None:
    probes: list[str] = []

    def never_ready(url: str) -> bool:
        probes.append(url)
        return False

    def no_sleep(_seconds: float) -> None:
        raise AssertionError("the poll must notice the dead child before it waits")

    ready = server.wait_until_ready(
        server.readiness_url(8765),
        process=_exited(),
        timeout=600.0,
        probe=never_ready,
        sleep=no_sleep,
    )
    assert ready is False
    assert probes == []


def test_the_readiness_poll_gives_up_at_the_deadline_rather_than_hanging() -> None:
    ticks = iter([0.0, 0.0, 1.0, 2.0, 30.0, 300.0])
    slept: list[float] = []
    ready = server.wait_until_ready(
        server.readiness_url(8765),
        process=_running(),
        timeout=5.0,
        probe=lambda _url: False,
        sleep=slept.append,
        clock=lambda: next(ticks),
    )
    assert ready is False
    assert slept  # it backed off between attempts rather than spinning


def test_the_readiness_poll_returns_true_as_soon_as_the_api_answers() -> None:
    answers = iter([False, False, True])
    ready = server.wait_until_ready(
        server.readiness_url(8765),
        process=_running(),
        timeout=30.0,
        probe=lambda _url: next(answers),
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )
    assert ready is True


def test_an_unreachable_port_probes_as_not_ready_instead_of_raising() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((server.LOOPBACK_HOST, 0))
        port = int(probe.getsockname()[1])
    assert server.probe_ready(server.readiness_url(port), timeout=0.5) is False


def test_a_child_that_exits_at_once_surfaces_its_own_words_not_a_timeout(tmp_path: Path) -> None:
    fake_crb = tmp_path / "bin" / "crb"
    fake_crb.parent.mkdir(parents=True)
    fake_crb.write_text(
        "#!/bin/sh\necho 'CRB_SECRET_KEY: too short' >&2\nexit 2\n", encoding="utf-8"
    )
    fake_crb.chmod(0o755)
    log = tmp_path / "desktop-server.log"
    with pytest.raises(server.ServerStartError) as raised:
        server.start_and_wait(fake_crb, env={}, port=8765, log_path=log, timeout=30.0)
    assert "exited with status 2" in str(raised.value)
    assert "too short" in raised.value.log_tail


def test_stopping_a_server_that_is_already_gone_is_not_an_error(tmp_path: Path) -> None:
    fake_crb = tmp_path / "bin" / "crb"
    fake_crb.parent.mkdir(parents=True)
    fake_crb.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    fake_crb.chmod(0o755)
    handle = server.start_server(
        fake_crb, env={}, port=8765, log_path=tmp_path / "desktop-server.log"
    )
    handle.process.wait(timeout=10)
    assert server.stop_server(handle) == 3


def test_the_log_tail_is_what_a_failed_start_shows_the_user(tmp_path: Path) -> None:
    log = tmp_path / "desktop-server.log"
    log.write_text("\n".join(f"line {n}" for n in range(200)), encoding="utf-8")
    tail = server.read_log_tail(log, lines=3)
    assert tail.splitlines() == ["line 197", "line 198", "line 199"]
    assert server.read_log_tail(tmp_path / "absent.log") == ""
