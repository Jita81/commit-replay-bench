"""The ``CRB_HOME`` temporary-directory guard (DL-045, F37).

A deployment under ``/tmp``, ``/private/tmp``, ``/var/folders`` or ``$TMPDIR`` loses its
files to the operating system — macOS documents those paths as temporary and its periodic
clean-up removes untouched files there — so ``Settings`` refuses to construct in ``prod``
and warns loudly in ``dev``. ``CRB_ALLOW_TEMP_HOME=true`` is the explicit opt-out for a
throwaway evaluation (the walkthrough harness runs ``dev``, so it only warns).

Navigation
----------
What it is:   The test suite for :func:`crb.server.settings.temp_dir_reason` and the guard in
              ``Settings``.
What it does: Pins that each temporary root is recognised through symlinks (``/tmp`` →
              ``/private/tmp`` on macOS) and ``$TMPDIR``, that a persistent path is not, that
              ``prod`` refuses with the reason and the fix in the message, that ``dev`` warns
              with the same, that the opt-out admits it, and that the refusal comes AFTER the
              secret-key rule (the first error a bare prod shell sees is still the key).
How:          ``tmp_path`` (itself under the OS temp directory on every platform) against
              ``/srv/crb`` — the image's own ``CRB_HOME``, never under a temporary root and
              never created by the test (``Settings`` creates nothing).
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/settings.py (under test), src/crb/cli/commands/service.py (the
              ``home`` doctor line reuses ``temp_dir_reason``), docs/DEPLOYMENT.md (§1.1, the
              rule and the layout), tests/test_cli_doctor.py (the doctor line)
Tested by:    tests/test_settings_home_guard.py
Touch when:   a temporary root is added to ``TEMP_DIR_ROOTS``; the opt-out changes name.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from crb.server.settings import TEMP_DIR_ROOTS, Settings, temp_dir_reason

KEY = SecretStr("k" * 40)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def persistent() -> Path:
    """A path that is NOT under a temporary root — the image's ``CRB_HOME`` (never created:
    ``Settings`` creates nothing, and ``resolve()`` is non-strict)."""
    return Path("/srv/crb")


class TestTempDirReason:
    def test_every_root_is_recognised_including_through_symlinks(self, tmp_path: Path) -> None:
        for root in TEMP_DIR_ROOTS:
            reason = temp_dir_reason(Path(root) / "crb-x" / "home", {})
            assert reason and "OS-managed temporary directory" in reason, root
            assert root in reason or str(Path(root).resolve()) in reason
        # pytest's own tmp_path is under the OS temp directory on macOS ($TMPDIR →
        # /private/var/folders/…) and on Linux (/tmp): the guard must see it either way
        assert temp_dir_reason(tmp_path, dict(os.environ)) is not None

    def test_tmpdir_variable_counts_and_is_named(self, tmp_path: Path, persistent: Path) -> None:
        env = {"TMPDIR": str(persistent / "scratch")}
        assert temp_dir_reason(persistent / "scratch" / "home", env) is not None
        assert "$TMPDIR" in str(temp_dir_reason(persistent / "scratch" / "home", env))
        assert temp_dir_reason(persistent / "home", env) is None

    def test_a_persistent_path_is_not_flagged(self, persistent: Path) -> None:
        assert temp_dir_reason(persistent, {}) is None
        assert temp_dir_reason("~/crb-stack/home", {}) is None
        assert temp_dir_reason("/srv/crb", {}) is None
        # the root itself is temporary; a sibling that merely starts with its name is not
        assert temp_dir_reason("/tmpfs-data/crb", {}) is None


class TestSettingsGuard:
    def test_prod_refuses_a_temporary_home_with_the_reason_and_the_fix(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValidationError) as ei:
            Settings(env="prod", home=tmp_path, secret_key=KEY)
        msg = str(ei.value)
        assert "CRB_HOME" in msg and "OS-managed temporary directory" in msg
        assert "periodic clean-up" in msg and "~/crb-stack" in msg and "docs/DEPLOYMENT.md" in msg
        assert "CRB_ALLOW_TEMP_HOME" in msg

    def test_dev_warns_with_the_same_reason(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.settings"):
            s = Settings(env="dev", home=tmp_path, secret_key=KEY)
        assert s.home == tmp_path
        warning = next(r for r in caplog.records if "CRB_HOME" in r.message)
        assert "OS-managed temporary directory" in warning.message
        assert (
            "periodic clean-up" in warning.message and "CRB_ALLOW_TEMP_HOME" not in warning.message
        )

    def test_opt_out_admits_it_in_prod_and_still_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.settings"):
            s = Settings(env="prod", home=tmp_path, secret_key=KEY, allow_temp_home=True)
        assert s.allow_temp_home is True and s.home == tmp_path
        assert any("CRB_HOME" in r.message for r in caplog.records)

    def test_opt_out_reads_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_HOME", str(tmp_path))
        monkeypatch.setenv("CRB_SECRET_KEY", "k" * 40)
        with pytest.raises(ValidationError, match="CRB_HOME"):
            Settings()
        monkeypatch.setenv("CRB_ALLOW_TEMP_HOME", "true")
        assert Settings().allow_temp_home is True

    def test_a_persistent_home_is_silent(
        self, persistent: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.settings"):
            s = Settings(env="prod", home=persistent, secret_key=KEY)
        assert s.home == persistent
        assert not any("CRB_HOME" in r.message for r in caplog.records)

    def test_the_secret_key_rule_still_comes_first(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="CRB_SECRET_KEY is required"):
            Settings(env="prod", home=tmp_path)
