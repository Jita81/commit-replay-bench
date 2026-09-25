"""Python fixture WITH a pinned dependency: ``pkg`` imports ``cfxdep`` from a requirements lock.

The parent pins ``cfxdep==1.0.0`` (no hash: the fetch records one) and the feat (gold) commit
pins ``cfxdep==1.1.0 --hash=…`` (committed: the fetch verifies it) and adds ``pkg/bye.py``,
which calls ``cfxdep.farewell`` — only ``1.1.0`` has it. So the parent's and the gold's locks
select different sealed sets, one per lockfile (ADR-0019).

Layout::

    requirements.txt    cfxdep==1.0.0                         \\  commit 1
    pkg/__init__.py     hello() → cfxdep.greet()               |
    tests/test_core.py  test_hello                            /
    requirements.txt    cfxdep==1.1.0 --hash=sha256:…         \\  commit 2 (the feat)
    pkg/bye.py          bye() → cfxdep.farewell()              |
    tests/test_bye.py   test_bye                              /

Navigation
----------
What it is:   The Python fixture with a locked third-party dependency whose version the feat
              commit bumps.
What it does: Builds the two-commit repository whose parent and gold locks select different
              sealed site sets, for the Python recipe's daemon test.
How:          ``two_commit_repo`` over inline sources; the gold's hash from ``pkgmirror.wheel_hash``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/fixtures/pkgmirror.py (the wheels it pins), tests/fixtures/langs/__init__.py
              (the two-commit shape), tests/test_provision_python.py (the consumer)
Tested by:    tests/test_provision_python.py
Touch when:   the Python recipe needs another lock shape (an include, a marker).
"""

from __future__ import annotations

from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from .. import pkgmirror
from . import two_commit_repo

SRC_BYE = "pkg/bye.py"
TEST_BYE = "tests/test_bye.py"

_INITIAL = {
    "requirements.txt": "cfxdep==1.0.0\n",
    "pkg/__init__.py": "import cfxdep\n\n\ndef hello():\n    return cfxdep.greet()\n",
    "tests/test_core.py": "from pkg import hello\n\n\ndef test_hello():\n    assert hello() == 'hello'\n",
}

_FEAT = {
    "requirements.txt": f"cfxdep==1.1.0 --hash={pkgmirror.wheel_hash('1.1.0')}\n",
    SRC_BYE: "import cfxdep\n\n\ndef bye():\n    return cfxdep.farewell()\n",
    TEST_BYE: "from pkg.bye import bye\n\n\ndef test_bye():\n    assert bye() == 'goodbye'\n",
}


def build(tmp_path: Path) -> tuple[Path, str]:
    return two_commit_repo(Path(tmp_path) / "pyrepo_deps", _INITIAL, _FEAT)


def config() -> RepoConfig:
    return RepoConfig(
        name="pydeps",
        language=Language.PYTHON,
        runner="pytest",
        src_prefix="pkg/",
        test_prefix="tests/",
        ext=".py",
        belt_scope=BELT_BARE,
    )


__all__ = ["SRC_BYE", "TEST_BYE", "build", "config"]
