"""Prefixed short ID generator -- canonical home for all Swarm Suite IDs.

Pattern: `<prefix>-<hex>` where hex is `secrets.token_hex(length)`.
The default length=2 yields IDs like `f-a1b2` (8 chars total) -- short enough
for humans to copy-paste, long enough for low collision probability over a
session lifetime (16 bits = 65536 -> birthday collision at ~256 IDs, which
is acceptable; tools that need more headroom pass length=4).

Conventions used across the suite:
    f-   finding
    fp-  fix proposal
    c-   claim
    r-   reaction
    e-   event
    m-   message
    sess- review session  (date-sequenced via swarm_core.sessions)
    fix- fix session
    arch- arch session
    doc-  doc session
    spec- spec session
"""

from __future__ import annotations

import secrets

_VALID_PREFIX_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def generate_id(prefix: str, length: int = 2) -> str:
    """Return `<prefix>-<hex>` where hex is `secrets.token_hex(length)`.

    Args:
        prefix: short lowercase prefix without the trailing dash. Allowed
            chars: `a-z`, `0-9`, `-`. ValueError on invalid prefix.
        length: byte length passed to `secrets.token_hex`. Each byte is
            two hex chars; default 2 -> 4-char suffix.

    Returns:
        The composed ID string.

    Examples:
        >>> generate_id("f")              # doctest: +SKIP
        'f-a1b2'
        >>> generate_id("fp", length=3)   # doctest: +SKIP
        'fp-a1b2c3'
    """
    if not prefix:
        raise ValueError("prefix must be non-empty")
    if any(c not in _VALID_PREFIX_CHARS for c in prefix):
        raise ValueError(
            f"prefix {prefix!r} contains characters outside [a-z0-9-]"
        )
    if length < 1:
        raise ValueError("length must be >= 1")
    return f"{prefix}-{secrets.token_hex(length)}"
