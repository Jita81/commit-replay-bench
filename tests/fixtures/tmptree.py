"""Give a test's temporary tree back to its owner so it can be deleted (P-101).

Navigation
----------
What it is:   The one helper that makes a temporary tree removable again after a test made
              parts of it read-only (a sealed dependency set, a locked directory).
What it does: ``restore_removable(root)`` adds the owner's read, write and search bits to
              ``root`` and every directory under it, top down, so ``shutil.rmtree`` and
              pytest's own clean-up can delete it. It never follows a symbolic link: what a
              link points at is not the test's to change.
How:          ``os.walk`` top down, chmod each directory before descending into it; a link is
              skipped by ``lstat``; errors are ignored (a best-effort finaliser).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/conftest.py (the session finaliser over the base temporary directory),
              tests/test_tmp_tree_hygiene.py (the guard), src/crb/provision/store.py
              (``_make_read_only``, which makes the trees this undoes)
Tested by:    tests/test_tmp_tree_hygiene.py
Touch when:   a test makes something other than a directory stop its own deletion.
"""

from __future__ import annotations

import contextlib
import os
import stat
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


__all__ = ["restore_removable"]
