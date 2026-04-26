"""Filesystem helpers -- atomic writes safe across processes.

`atomic_write_text` is the only sanctioned way to overwrite a file that
other processes may read. Manual `open(path, "w").write(...)` is forbidden
for shared session files (meta.json, claims.json, anything in
~/.swarm-kb/sessions/<tool>/<sid>/).

JSONL append-only files (findings.jsonl, events.jsonl) use `open(path, "a")`
which is atomic for single-line appends on POSIX and Windows.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write `content` to `path`.

    Strategy: write to a sibling tempfile, then `os.replace` (atomic on
    POSIX and Windows when source and dest are on the same filesystem).
    A reader that opens `path` either sees the old contents or the new --
    never a partial write.

    Creates parent directories if missing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl_line(path: Path, line: str, *, encoding: str = "utf-8") -> None:
    """Append a single JSONL line. Creates parent dirs and the file if missing.

    Single-line writes to an `O_APPEND` file are atomic on every OS we
    target; concurrent appenders will not interleave at the byte level
    for lines smaller than `PIPE_BUF` (4096+ bytes everywhere).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not line.endswith("\n"):
        line = line + "\n"
    with open(path, "a", encoding=encoding) as fh:
        fh.write(line)
