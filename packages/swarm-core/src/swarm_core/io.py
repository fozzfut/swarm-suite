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
import sys
import tempfile
import time
from pathlib import Path

# Windows os.replace can transiently fail with PermissionError [WinError 5]
# when an antivirus, a recently-released file handle, or the OS's own
# file-bookkeeping briefly holds either the source tempfile or the
# destination -- typical under heavy concurrent writes from sibling
# processes (cross-process file locks released the critical section, but
# the kernel hasn't yet released the handle). Retry with short backoff;
# on POSIX this loop never runs because os.replace doesn't have this
# class of transient failure.
_REPLACE_MAX_ATTEMPTS = 8
_REPLACE_BACKOFF_BASE_S = 0.01    # first sleep 10ms; doubles each retry


def _replace_with_retry(src: str, dst: str) -> None:
    last_exc: BaseException | None = None
    for attempt in range(_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_exc = exc
            # Windows-only path. Sleep briefly and try again.
            if sys.platform != "win32":
                raise
            time.sleep(_REPLACE_BACKOFF_BASE_S * (2 ** attempt))
    # Exhausted: re-raise the last exception so caller sees the real cause.
    assert last_exc is not None
    raise last_exc


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write `content` to `path`.

    Strategy: write to a sibling tempfile, then `os.replace` (atomic on
    POSIX and Windows when source and dest are on the same filesystem).
    A reader that opens `path` either sees the old contents or the new --
    never a partial write.

    Creates parent directories if missing. On Windows, `os.replace` is
    retried with backoff for transient `PermissionError` (see
    `_replace_with_retry`).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
        _replace_with_retry(tmp, str(path))
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
