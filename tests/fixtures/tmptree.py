"""Give a test's temporary tree back to its owner so it can be deleted (P-101).

Navigation
----------
What it is:   The one helper that makes a temporary tree removable again after a test made
              parts of it read-only (a sealed dependency set, a locked directory).
What it does: ``restore_removable(root)`` adds the owner's read, write and search bits to
              ``root`` and every directory under it, top down, so ``shutil.rmtree`` and
              pytest's own clean-up can delete it. It never follows a symbolic link: what a
              link points at is not the test's to change. ``permissions_bind()`` says whether
              the mode bits refuse this process at all — uid 0 with ``CAP_DAC_OVERRIDE`` is
              not refused — so a test expects a refusal only where one can happen (P-108).
How:          ``os.walk`` top down, chmod each directory before descending into it; a link is
              skipped by ``lstat``; errors are ignored (a best-effort finaliser). The probe
              seals a directory with a file in it and asks ``shutil.rmtree`` to remove it.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/conftest.py (the session finaliser over the base temporary directory),
              tests/test_tmp_tree_hygiene.py (the guard), src/crb/provision/store.py
              (``_make_read_only``, which makes the trees this undoes),
              tests/test_provision_store.py (asks ``permissions_bind`` before expecting a
              write into a sealed set to be refused)
Tested by:    tests/test_tmp_tree_hygiene.py
Touch when:   never for a new repository (it cleans up after this suite's own tests); a
              test makes something other than a directory stop its own deletion, or expects
              the operating system to refuse something on the mode bits.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path


def _open_dir(path: str) -> None:
    with contextlib.suppress(OSError):
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode) and (st.st_mode & stat.S_IRWXU) != stat.S_IRWXU:
            os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IRWXU)


def restore_removable(root: Path) -> None:
    """Add ``u+rwx`` to ``root`` and every directory below it; never through a link."""
    top = str(root)
    if not os.path.lexists(top) or os.path.islink(top):
        return
    _open_dir(top)
    for dirpath, dirnames, _files in os.walk(top, topdown=True, followlinks=False):
        for name in dirnames:
            _open_dir(os.path.join(dirpath, name))


def permissions_bind() -> bool:
    """True when the mode bits refuse this process: ``shutil.rmtree`` cannot remove a
    directory whose own mode is ``0o555``. False for uid 0 with ``CAP_DAC_OVERRIDE``, whom
    the kernel lets through — a test must not REQUIRE a refusal there (P-108)."""
    with tempfile.TemporaryDirectory(prefix="crb-perm-probe-") as d:
        sealed = Path(d) / "sealed"
        sealed.mkdir()
        (sealed / "f").write_text("x", encoding="utf-8")
        sealed.chmod(0o555)
        try:
            shutil.rmtree(sealed)
        except OSError:
            return True
        finally:
            restore_removable(Path(d))
    return False


__all__ = ["permissions_bind", "restore_removable"]
