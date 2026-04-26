"""Cross-process file lock for read-modify-write storage operations.

Engine stores (judging / verification / pgve / flow / completion) all
follow the load -> mutate -> atomic_write pattern. Atomic write
guarantees the FILE is never corrupt -- but logical updates can still
be lost when two processes interleave. This module bolts on the
cross-process file lock that closes that gap.

Usage:

    with cross_process_lock(record_path.with_suffix(".lock")):
        # Inside this block we have exclusive write access to the
        # record across ALL processes touching this KB. Reload from
        # disk first so we see the latest writes from any other
        # process; mutate; atomic-save while still holding the lock.

The lock is per-record (sibling .lock file next to the JSON), so two
processes operating on different records run in parallel.

Implementation: thin wrapper around `portalocker`. The Lock object
auto-creates the lock file if missing and uses fcntl on POSIX or
LockFileEx on Windows under the hood. Default timeout is 5 s -- if
held longer, raises portalocker.AlreadyLocked which the caller can
catch (engines surface as a transient error to the MCP client).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import portalocker

_log = logging.getLogger("swarm_kb.filelock")


# Default acquisition timeout. 5s is generous for a single store
# read+mutate+write (which is microseconds in normal use); above that
# something is genuinely wrong (deadlocked sibling, stale lock from a
# crashed process holding a fcntl lock that never released).
DEFAULT_TIMEOUT_SECONDS: float = 5.0


@contextmanager
def cross_process_lock(
    lock_path: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock on `lock_path`.

    Creates the lock file if missing. Releases on context exit even
    when the body raises. On timeout, raises `portalocker.AlreadyLocked`
    -- the caller is expected to surface this as a transient error.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # LOCK_EX | LOCK_NB so portalocker can honour `timeout` via internal
    # retry-with-backoff instead of blocking forever; pure LOCK_EX would
    # ignore timeout per portalocker's contract.
    with portalocker.Lock(
        str(lock_path),
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        timeout=timeout,
    ):
        yield


def lock_path_for(record_json: Path) -> Path:
    """Return the sibling .lock path for a record JSON file.

    Convention: `<dir>/<name>.json` -> `<dir>/<name>.lock`. Caller is
    expected to create the parent dir if needed (the cross_process_lock
    context manager does this anyway).
    """
    return record_json.with_suffix(".lock")
