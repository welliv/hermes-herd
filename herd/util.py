"""Small shared helpers: paths, atomic writes, file locking, time formatting."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import socket
import tempfile
import time
import time
from pathlib import Path

try:  # Hermes ships this for every profile-aware path decision.
    from hermes_constants import get_hermes_home  # type: ignore
except Exception:  # pragma: no cover - exercised outside Hermes
    get_hermes_home = None


def hermes_home() -> Path:
    """Resolve the live Hermes home the way Hermes itself would.

    Hermes' resolver checks a context-local override before ``HERMES_HOME``, so
    under a gateway routing several profiles it names the profile this turn
    belongs to. Reading the env var first would sync the launch profile instead.
    """
    if get_hermes_home is not None:
        with contextlib.suppress(Exception):
            return Path(str(get_hermes_home())).expanduser().resolve()
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".hermes").resolve()


def sync_dir(home: Path | None = None) -> Path:
    return (home or hermes_home()) / "sync"


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts if ts is not None else now()))


def human_age(ts: float) -> str:
    if not ts:
        return "never"
    delta = max(0.0, now() - ts)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= size:
            return f"{int(delta // size)}{unit} ago"
    return "just now"


def default_device_name() -> str:
    name = socket.gethostname().split(".")[0].strip()
    return name or "hermes"


def _replace(tmp: str, path: Path, attempts: int = 12, delay: float = 0.05) -> None:
    """Rename over the target, retrying while Windows holds the old handle.

    POSIX replaces atomically even while another process has the file open;
    Windows refuses with ``WinError 5`` until that reader closes it. Three
    machines syncing at once is exactly the case that trips it, so wait for the
    peer's read to finish instead of failing the sync.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write via a sibling temp file + rename so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        _replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_json(path: Path, obj, mode: int = 0o600) -> None:
    atomic_write(path, json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False).encode() + b"\n", mode)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class LockBusy(RuntimeError):
    pass


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 10.0):
    """Serialise sync runs between a CLI call, the gateway hook and a cron job."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    deadline = now() + timeout
    try:
        while True:
            try:
                if os.name == "nt":  # pragma: no cover - Windows
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise
                if now() >= deadline:
                    raise LockBusy("another sync is running") from exc
                time.sleep(0.1)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n".encode())
        fh.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
