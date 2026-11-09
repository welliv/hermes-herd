"""The sync store: encrypted, content-addressed, append-only per device.

Layout::

    store.json                 public metadata (salt, store id, key check)
    devices/<device_id>.json   that device's item manifest — only it ever writes it
    objects/<oid>              sealed blobs, named by a keyed hash of the plaintext

Because every device owns exactly one file, simultaneous pushes cannot lose an
update: git merges two different files, and each item is resolved by (rev,
device id). Objects are immutable, so they merge trivially.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import crypto
from .util import atomic_write, now, read_json, write_json

STORE_VERSION = 1


class StoreError(RuntimeError):
    """A store could not be read, unlocked or published."""


@dataclass
class Entry:
    item_id: str
    oid: str
    kind: str
    rev: int
    device_id: str
    mtime: float = 0.0
    size: int = 0
    deleted: bool = False
    # The entry this change was made on top of. It is what tells a fast-forward
    # ("they built on what I published") from a real disagreement ("we both
    # started from the same older value").
    parent_rev: int = 0
    parent_dev: str = ""

    def to_json(self) -> dict:
        return {
            "oid": self.oid,
            "kind": self.kind,
            "rev": self.rev,
            "mtime": self.mtime,
            "size": self.size,
            "deleted": self.deleted,
            "parent_rev": self.parent_rev,
            "parent_dev": self.parent_dev,
        }

    @property
    def key(self) -> tuple:
        # Higher rev wins; device id breaks ties deterministically on every machine.
        return (self.rev, self.device_id)


@dataclass
class Store:
    root: Path
    meta: dict = field(default_factory=dict)

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def open(cls, root: str | Path) -> "Store":
        root = Path(root).expanduser()
        store = cls(root=root, meta=read_json(root / "store.json", {}) or {})
        return store

    @property
    def initialized(self) -> bool:
        return bool(self.meta.get("store_id") and self.meta.get("salt"))

    def init(self, key: bytes) -> None:
        if self.initialized:
            raise StoreError(f"{self.root} is already a Herd store.")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "devices").mkdir(exist_ok=True)
        (self.root / "objects").mkdir(exist_ok=True)
        salt = os.urandom(16)
        store_id = f"herd_{crypto.random_id(16)}"
        self.meta = {
            "version": STORE_VERSION,
            "store_id": store_id,
            "cipher": "aes-256-gcm",
            "kdf": "scrypt-n32768-r8-p1",
            "salt": base64.b64encode(salt).decode(),
            # The store must verify the *derived* key: that is what unlock()
            # reproduces from the recovery code on another machine.
            "check": crypto.store_check(crypto.derive_key(key, salt)),
            "created_at": now(),
        }
        write_json(self.root / "store.json", self.meta, mode=0o644)
        self._write_gitignore()

    def _write_gitignore(self) -> None:
        gi = self.root / ".gitignore"
        if gi.exists():
            return
        atomic_write(
            gi,
            b"# Keep the store clean: git bookkeeping only.\n.git/\n*.tmp\n.DS_Store\n",
            mode=0o644,
        )

    @property
    def store_id(self) -> str:
        if not self.initialized:
            raise StoreError("This folder is not a Herd store yet.")
        return str(self.meta["store_id"])

    @property
    def salt(self) -> bytes:
        return base64.b64decode(self.meta["salt"])

    def unlock(self, code: str) -> bytes:
        """Derive the key from a recovery code and prove it opens this store."""
        if not self.initialized:
            raise StoreError("This folder is not a Herd store yet.")
        key = crypto.derive_key(code, self.salt)
        if not crypto.verify_code(key, self.meta.get("check", "")):
            raise crypto.BadCode(
                "That recovery code does not open this store. Check the code from "
                "`hermes sync code` on a machine that already syncs here."
            )
        return key

    # ── objects ──────────────────────────────────────────────────────────────
    def _object_path(self, oid: str) -> Path:
        return self.root / "objects" / oid[:2] / oid

    def put(self, key: bytes, plaintext: bytes) -> str:
        oid = crypto.object_id(key, plaintext)
        path = self._object_path(oid)
        if path.exists():
            return oid
        atomic_write(path, crypto.seal(key, plaintext, self.store_id), mode=0o644)
        return oid

    def get(self, key: bytes, oid: str) -> bytes:
        path = self._object_path(oid)
        try:
            blob = path.read_bytes()
        except OSError as exc:
            raise StoreError(
                f"Object {oid[:10]}… is missing from the store. Run `hermes sync status` "
                "on the other machine and push again."
            ) from exc
        return crypto.open_sealed(key, blob, self.store_id)

    def objects(self) -> list[tuple[str, Path, float]]:
        """Every sealed object as ``(oid, path, mtime)`` — for housekeeping only."""
        out: list[tuple[str, Path, float]] = []
        root = self.root / "objects"
        if not root.exists():
            return out
        for path in root.glob("*/*"):
            if path.is_file():
                try:
                    out.append((path.name, path, path.stat().st_mtime))
                except OSError:
                    continue
        return out

    # ── manifests ────────────────────────────────────────────────────────────
    def device_path(self, device_id: str) -> Path:
        return self.root / "devices" / f"{device_id}.json"

    def read_device(self, device_id: str) -> dict:
        return read_json(self.device_path(device_id), {}) or {}

    def write_device(self, device: dict, items: dict[str, Entry], clock: int) -> None:
        write_json(
            self.device_path(device["id"]),
            {
                "version": STORE_VERSION,
                "device": {k: device.get(k) for k in ("id", "name", "platform", "created_at")},
                "clock": clock,
                "updated_at": now(),
                "items": {iid: e.to_json() for iid, e in sorted(items.items())},
            },
            mode=0o644,
        )

    def other_manifests(self, self_id: str) -> list[dict]:
        out = []
        for path in sorted((self.root / "devices").glob("*.json")):
            if path.stem == self_id:
                continue
            data = read_json(path, {}) or {}
            if data.get("items") is not None:
                out.append(data)
        return out

    def merged(self) -> dict[str, Entry]:
        """Newest entry per item across every device manifest."""
        best: dict[str, Entry] = {}
        for path in sorted((self.root / "devices").glob("*.json")):
            data = read_json(path, {}) or {}
            for item_id, raw in (data.get("items") or {}).items():
                try:
                    entry = Entry(
                        item_id=item_id,
                        oid=raw.get("oid", ""),
                        kind=raw.get("kind", "file"),
                        rev=int(raw.get("rev", 0)),
                        device_id=str((data.get("device") or {}).get("id") or path.stem),
                        mtime=float(raw.get("mtime") or 0),
                        size=int(raw.get("size") or 0),
                        deleted=bool(raw.get("deleted")),
                        parent_rev=int(raw.get("parent_rev") or 0),
                        parent_dev=str(raw.get("parent_dev") or ""),
                    )
                except (TypeError, ValueError):
                    continue
                if item_id not in best or entry.key > best[item_id].key:
                    best[item_id] = entry
        return best

    def max_clock(self) -> int:
        clocks = [int((read_json(p, {}) or {}).get("clock") or 0) for p in self.root.glob("devices/*.json")]
        return max(clocks, default=0)

    # ── transport ────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Pull the latest from the remote, if this store has one. Never fatal."""

    def publish(self, message: str) -> dict:
        """Commit and push. Returns {committed, pushed, detail}."""
        return {"committed": False, "pushed": False, "detail": "local folder"}


# ── git transport ────────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=check
        )
    except FileNotFoundError as exc:  # pragma: no cover - git is a hard requirement
        raise StoreError("git is not installed. Use a plain folder store, or install git.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise StoreError(f"git {' '.join(args)} failed: {detail[-1] if detail else 'unknown error'}") from exc


class GitStore(Store):
    """A clone of a git remote. Ciphertext is all git ever sees."""

    def has_remote(self) -> bool:
        try:
            return bool(_git(["remote"], self.root).stdout.strip())
        except StoreError:
            return False

    def refresh(self) -> None:
        if not self.root.exists() or not (self.root / ".git").exists():
            return
        if not self.has_remote():
            return
        try:
            _git(["fetch", "--quiet", "origin"], self.root)
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip() or "main"
            _git(["rebase", "--autostash", "--quiet", f"origin/{branch}"], self.root)
        except StoreError:
            # A dirty rebase is the one case worth surfacing: the user must choose.
            _git(["rebase", "--abort"], self.root, check=False)
            raise

    def publish(self, message: str) -> dict:
        if not self.root.exists():
            return {"committed": False, "pushed": False, "detail": "no store"}
        if not (self.root / ".git").exists():
            _git(["init", "--quiet"], self.root)
        _git(["add", "-A"], self.root)
        status = _git(["status", "--porcelain"], self.root).stdout.strip()
        committed = False
        if status:
            _git(["-c", "user.name=Herd", "-c", "user.email=herd@localhost", "commit", "--quiet", "-m", message], self.root)
            committed = True
        if not self.has_remote():
            return {"committed": committed, "pushed": False, "detail": "no remote configured"}
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip() or "main"
        try:
            _git(["push", "--quiet", "-u", "origin", branch], self.root, timeout=120)
            return {"committed": committed, "pushed": True, "detail": f"pushed to origin/{branch}"}
        except StoreError as exc:
            return {"committed": committed, "pushed": False, "detail": f"saved locally, push failed: {exc}"}


def open_store(root: str | Path) -> Store:
    root = Path(root).expanduser()
    if (root / ".git").exists():
        return GitStore.open(root)
    # A bare remote URL is cloned by the caller before this point.
    return Store.open(root)


def clone(remote: str, dest: str | Path) -> Path:
    dest = Path(dest).expanduser()
    if dest.exists() and any(dest.iterdir()):
        raise StoreError(f"{dest} already exists and is not empty.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", "--quiet", remote, str(dest)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise StoreError(f"Could not clone {remote}: {detail[-1] if detail else 'git error'}") from exc
    # A bare remote whose HEAD points at a branch we never pushed leaves the
    # clone with an empty working tree; check out whichever branch has the store.
    if not (dest / "store.json").exists():
        for branch in ("main", "master"):
            subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", branch],
                           capture_output=True, text=True)
            if (dest / "store.json").exists():
                break
    return dest


def init_git_store(dest: str | Path, remote: str = "") -> Path:
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        _git(["init", "--quiet", "-b", "main"], dest)
    if remote:
        _git(["remote", "add", "origin", remote], dest, check=False)
        existing = _git(["remote", "get-url", "origin"], dest, check=False).stdout.strip()
        if existing and existing != remote:
            _git(["remote", "set-url", "origin", remote], dest)
    return dest


def looks_like_git(remote: str) -> bool:
    return remote.endswith(".git") or remote.startswith(("git@", "ssh://", "https://", "http://"))


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def dump_json(obj) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False).encode() + b"\n"
