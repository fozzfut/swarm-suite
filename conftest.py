"""Root conftest: make every package importable from a clean checkout.

Without this, `pytest packages/<tool>/tests` from a fresh clone fails
with `ModuleNotFoundError` because the source directories aren't on
`sys.path` and the packages aren't editable-installed yet.

Editable installs are still preferred for development, but this file
removes the friction for first-time-clone runs and CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_PACKAGES = (
    "swarm-core", "swarm-kb",
    "spec-swarm", "arch-swarm", "review-swarm", "fix-swarm", "doc-swarm",
)

for _pkg in _PACKAGES:
    _src = _REPO_ROOT / "packages" / _pkg / "src"
    if _src.is_dir():
        _src_str = str(_src)
        if _src_str not in sys.path:
            sys.path.insert(0, _src_str)
