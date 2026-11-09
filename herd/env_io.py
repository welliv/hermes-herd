"""The only place herd touches `.env`, in both directions.

A store belongs to another device, so its payload is input, not truth. Three
guards live here so the write path cannot drift away from them:

* a key must be a POSIX name before it can become a line. A name that carries a
  newline would otherwise write a line nobody asked for, and the value beside it
  could redirect a provider endpoint;
* this machine's skip rules bind on the way in as well as on the way out, so a
  peer cannot set a key the user excluded from syncing;
* a key the administrator pins is refused, with the same message Hermes gives.

Hermes memoizes a parsed `.env` per path, so the write invalidates that cache.
Without it a pulled key stays invisible until the gateway restarts.
"""

from __future__ import annotations

import re
from pathlib import Path

from .util import atomic_write

_KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def key_is_writable(name: object) -> bool:
    """True when *name* is a key that may appear on a `.env` line of its own."""
    return isinstance(name, str) and _KEY_NAME.match(name) is not None


def refusal(name: str) -> str | None:
    """Why Hermes would refuse to write *name* on this machine, or None.

    A managed install and an administrator-pinned key are both closed to a
    plugin; a sync that ignored the refusal would quietly overwrite the value
    the administrator set. Outside Hermes (bare pytest) there is no policy to
    consult, so nothing is refused.
    """
    try:
        from hermes_cli.config import env_write_refusal
    except Exception:  # pragma: no cover - only when Hermes is not importable
        return None
    try:
        return env_write_refusal(name, "set")
    except Exception:  # pragma: no cover - a policy bug must not break a pull
        return None


def invalidate(path: Path) -> None:
    """Drop Hermes's memoized parse of *path* so the next read sees the write."""
    try:
        from agent.secret_scope import invalidate_env_file_cache
    except Exception:  # pragma: no cover - only when Hermes is not importable
        return
    try:
        invalidate_env_file_cache(Path(path))
    except Exception:  # pragma: no cover - a cache bug must not break a pull
        pass


def write(path: Path, text: str) -> None:
    """Replace *path* atomically, owner-only, and let Hermes notice."""
    atomic_write(path, text.encode(), mode=0o600)
    invalidate(path)
