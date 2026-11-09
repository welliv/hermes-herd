"""The sync engine: init, join, pull, push, and the safety net around writes.

Every function takes the Hermes home explicitly so a whole two-device exchange
can be exercised in one process during tests, instead of only in production.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config_merge, crypto, items as items_mod, store as store_mod, yamlutil
from . import env_io
from .policy import Policy
from .store import Entry, Store, StoreError
from .util import atomic_write, file_lock, human_age, iso, now, read_json, write_json

PLUGIN_ID = "herd"
STATE_VERSION = 1


def data_dir(home: Path) -> Path:
    """Per-profile, per-machine state. plugin-data survives plugin updates."""
    try:
        from plugins.plugin_storage import plugin_data_dir  # type: ignore

        return plugin_data_dir(PLUGIN_ID)
    except Exception:
        return home / "plugin-data" / PLUGIN_ID


class HerdError(RuntimeError):
    """A user-actionable failure: bad store, wrong code, unsafe state."""


# ── state ────────────────────────────────────────────────────────────────────
@dataclass
class Context:
    home: Path
    data: Path
    state: dict
    identity: dict
    policy: Policy
    store: Store
    key: bytes

    @property
    def device(self) -> dict:
        return self.state.get("device") or {}

    @property
    def lock(self):
        return file_lock(self.data / ".lock")


def load_state(data: Path) -> dict:
    return read_json(data / "state.json", {}) or {}


def _identity(data: Path, name: str | None = None) -> dict:
    ident = read_json(data / "identity.json", {}) or {}
    if not ident.get("device_id"):
        ident = {
            "device_id": crypto.random_id(10),
            "device_name": (name or _default_name()),
            "created_at": now(),
        }
        write_json(data / "identity.json", ident)
    return ident


def _default_name() -> str:
    from .util import default_device_name

    return default_device_name()


def _save_base(ctx: Context, items: dict[str, Entry], base_config: dict, base_env: dict) -> None:
    write_json(
        ctx.data / "base.json",
        {
            "version": STATE_VERSION,
            "items": {k: {"oid": e.oid, "rev": e.rev, "kind": e.kind} for k, e in items.items()},
            "config": base_config,
            "env": base_env,
            "saved_at": now(),
        },
    )


def _load_base(ctx: Context) -> dict:
    return read_json(ctx.data / "base.json", {}) or {"items": {}, "config": {}, "env": {}}


def open_context(home: Path, *, create: bool = False) -> Context:
    """Load identity, policy, store and key. Raises HerdError when not set up."""
    home = Path(home)
    data = data_dir(home)
    state = load_state(data)
    if not state.get("store"):
        if create:
            state = {"version": STATE_VERSION, "device": {}, "created_at": now()}
        else:
            raise HerdError("This machine is not syncing yet. Run `hermes sync init`.")
    ident = _identity(data, state.get("device_name"))
    state["device"] = state.get("device") or {
        "id": ident["device_id"],
        "name": ident["device_name"],
        "platform": items_mod.current_platform(),
        "created_at": ident["created_at"],
    }
    policy = Policy.load(data / "policy.yaml")
    store = store_mod.open_store(state["store"])
    if not store.initialized:
        raise HerdError(f"The sync store at {state['store']} is empty or was wiped.")
    key = store.unlock(ident.get("code", ""))
    return Context(home=home, data=data, state=state, identity=ident, policy=policy, store=store, key=key)


# ── init / join ──────────────────────────────────────────────────────────────
def init(home: Path, store_path: str, *, remote: str = "", name: str | None = None,
         sync_secrets: bool = True, include_cron: bool = False) -> dict:
    """Create a new store (and a new identity) on this machine."""
    home = Path(home)
    data = data_dir(home)
    data.mkdir(parents=True, exist_ok=True)

    existing = load_state(data)
    if existing.get("store"):
        raise HerdError(
            f"This machine already syncs to {existing['store']}. "
            "Use `hermes sync join` on a second machine, or `hermes sync leave` first."
        )

    if remote:
        target = Path(store_path).expanduser()
        store_mod.init_git_store(target, remote)
        root = target
    else:
        root = Path(store_path).expanduser()
    store = store_mod.open_store(root)

    key = crypto.new_key()
    code = crypto.format_code(key)
    store.init(key)
    store = store_mod.open_store(root)
    if not store.initialized:
        raise HerdError("Could not create the store.")

    ident = _identity(data, name)
    ident["code"] = code
    write_json(data / "identity.json", ident)

    policy = Policy.load(data / "policy.yaml")
    policy.sync_secrets = bool(sync_secrets)
    policy.save(data / "policy.yaml")

    state = {
        "version": STATE_VERSION,
        "store": str(root),
        "remote": remote or "",
        "sync_cron": bool(include_cron),
        "created_at": now(),
        "device": {
            "id": ident["device_id"],
            "name": ident["device_name"],
            "platform": items_mod.current_platform(),
            "created_at": ident["created_at"],
        },
    }
    write_json(data / "state.json", state)

    ctx = open_context(home)
    report = push(ctx)
    return {
        "ok": True,
        "store": str(root),
        "remote": remote or None,
        "device": ctx.device,
        "code": code,
        **report,
    }


def join(home: Path, store_path: str, code: str, *, name: str | None = None) -> dict:
    """Attach this machine to an existing store and take its state on."""
    home = Path(home)
    data = data_dir(home)
    data.mkdir(parents=True, exist_ok=True)
    existing = load_state(data)
    if existing.get("store"):
        raise HerdError(f"This machine already syncs to {existing['store']}. Run `hermes sync leave` first.")

    remote = ""
    path = Path(store_path).expanduser()
    bare_or_missing = not path.exists() or not (path / "store.json").exists()
    if store_mod.looks_like_git(store_path) and bare_or_missing:
        path = store_mod.clone(store_path, data / "store")
        remote = store_path
    store = store_mod.open_store(path)
    if not store.initialized:
        raise HerdError(f"{path} is not a Herd store. Check the path or the git URL.")
    store.unlock(code)  # raises BadCode with a clear message

    ident = _identity(data, name)
    ident["code"] = code.strip()
    write_json(data / "identity.json", ident)

    policy = Policy.load(data / "policy.yaml")
    policy.save(data / "policy.yaml")

    state = {
        "version": STATE_VERSION,
        "store": str(path),
        "remote": remote,
        "created_at": now(),
        "device": {
            "id": ident["device_id"],
            "name": ident["device_name"],
            "platform": items_mod.current_platform(),
            "created_at": ident["created_at"],
        },
    }
    write_json(data / "state.json", state)
    ctx = open_context(home)
    pulled = pull(ctx, prefer="remote")
    pushed = push(ctx)
    return {"ok": True, "store": str(path), "device": ctx.device, "pulled": pulled, "pushed": pushed}


def leave(home: Path) -> dict:
    """Stop syncing on this machine. Local files are untouched."""
    data = data_dir(Path(home))
    state = load_state(data)
    if not state.get("store"):
        raise HerdError("This machine is not syncing.")
    for name in ("state.json", "base.json", "conflicts.json"):
        try:
            (data / name).unlink()
        except OSError:
            pass
    return {"ok": True, "left": True, "store": state.get("store")}


# ── push ─────────────────────────────────────────────────────────────────────
def push(ctx: Context) -> dict:
    with ctx.lock:
        base = _load_base(ctx)
        include_cron = bool(ctx.state.get("sync_cron"))
        local = items_mod.scan(ctx.home, ctx.policy, include_cron=include_cron)
        mine = ctx.store.read_device(ctx.device["id"])
        my_items: dict[str, Entry] = {}
        for item_id, raw in (mine.get("items") or {}).items():
            try:
                my_items[item_id] = Entry(
                    item_id=item_id, oid=raw.get("oid", ""), kind=raw.get("kind", "file"),
                    rev=int(raw.get("rev", 0)), device_id=ctx.device["id"],
                    mtime=float(raw.get("mtime") or 0), size=int(raw.get("size") or 0),
                    deleted=bool(raw.get("deleted")),
                )
            except (TypeError, ValueError):
                continue

        merged = ctx.store.merged()
        clock = ctx.store.max_clock()
        changed, unchanged, removed = [], [], []
        left: set[str] = set(local)

        for item_id, item in local.items():
            oid = ctx.store.put(ctx.key, item.payload)
            previous = (base.get("items") or {}).get(item_id) or {}
            own = my_items.get(item_id)
            if oid == previous.get("oid") and own is not None and own.oid == oid:
                own.mtime = item.mtime
                unchanged.append(item_id)
                continue
            rev = max(clock, int(previous.get("rev") or 0), (my_items[item_id].rev if item_id in my_items else 0),
                      merged[item_id].rev if item_id in merged else 0) + 1
            clock = rev
            my_items[item_id] = Entry(item_id=item_id, oid=oid, kind=item.kind, rev=rev,
                                      device_id=ctx.device["id"], mtime=item.mtime, size=item.size)
            changed.append(item_id)

        for item_id in set(base.get("items") or {}) - left:
            previous = my_items.get(item_id)
            rev = max(clock, int((base["items"][item_id] or {}).get("rev") or 0),
                      previous.rev if previous else 0, merged[item_id].rev if item_id in merged else 0) + 1
            clock = rev
            my_items[item_id] = Entry(item_id=item_id, oid="", kind=(previous.kind if previous else "file"),
                                      rev=rev, device_id=ctx.device["id"], deleted=True)
            removed.append(item_id)

        ctx.store.write_device({**ctx.device, "created_at": ctx.device.get("created_at", now())}, my_items, clock)
        published = ctx.store.publish(f"herd: {ctx.device.get('name', 'device')} push {len(changed)} item(s)")

        base_items = dict(base.get("items") or {})
        for item_id, entry in my_items.items():
            base_items[item_id] = {"oid": entry.oid, "rev": entry.rev, "kind": entry.kind}
        # The merge base must have the same shape as what the store holds: the
        # config as scrubbed. Storing the live dict here makes every local-only
        # section look deleted by the remote on the next pull.
        _save_base(ctx, my_items, items_mod.scrub(_local_dict(local, "config"), ctx.policy),
                   _local_dict(local, "env"))

        ctx.state["last_push"] = now()
        ctx.state["last_sync"] = now()
        write_json(ctx.data / "state.json", ctx.state)
        return {
            "pushed": changed,
            "removed": removed,
            "unchanged": len(unchanged),
            "transport": published,
        }


def _local_dict(local: dict, item_id: str) -> dict:
    item = local.get(item_id)
    if not item:
        return {}
    if item_id == "config":
        return item.extra.get("live") or {}
    return item.extra.get("live") or {}


# ── pull ─────────────────────────────────────────────────────────────────────
def pull(ctx: Context, prefer: str = "local") -> dict:
    with ctx.lock:
        ctx.store.refresh()
        base = _load_base(ctx)
        merged = ctx.store.merged()
        base_items = dict(base.get("items") or {})
        applied, skipped, conflicts, removed = [], [], [], []
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

        local = items_mod.scan(ctx.home, ctx.policy, include_cron=bool(ctx.state.get("sync_cron")))
        for item_id, entry in sorted(merged.items()):
            if entry.device_id == ctx.device["id"]:
                continue
            known = base_items.get(item_id) or {}
            if known.get("oid") == entry.oid and known.get("rev") == entry.rev:
                skipped.append(item_id)
                continue

            if entry.deleted:
                if _remove_item(ctx, item_id, stamp):
                    removed.append(item_id)
                base_items[item_id] = {"oid": "", "rev": entry.rev, "kind": entry.kind}
                continue

            try:
                payload = ctx.store.get(ctx.key, entry.oid)
            except (StoreError, crypto.TamperedBlob) as exc:
                skipped.append(f"{item_id}: {exc}")
                continue

            if entry.kind == "config":
                result = _apply_config(ctx, payload, base, local, prefer, stamp)
                conflicts.extend({**c, "item": item_id} for c in result["conflicts"])
                if result["changed"]:
                    applied.append(item_id)
                base["config"] = result["remote"]
            elif entry.kind == "env":
                result = _apply_env(ctx, payload, base, stamp)
                conflicts.extend({**c, "item": item_id} for c in result["conflicts"])
                if result["changed"]:
                    applied.append(item_id)
                base["env"] = result["remote"]
            elif entry.kind == "skill":
                item = local.get(item_id)
                local_oid = crypto.object_id(ctx.key, item.payload) if item else ""
                base_oid = (base_items.get(item_id) or {}).get("oid")
                if item and base_oid and local_oid != base_oid and local_oid != entry.oid:
                    # Both machines edited the same skill. Keep this one, but put
                    # the other side somewhere the user can reach — a skill is a
                    # directory, so "merge" would be a guess.
                    saved = ctx.data / "conflicts" / stamp / f"{item_id.split(':', 1)[1]}.tar.gz"
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes(payload)
                    conflicts.append({
                        "item": item_id,
                        "path": "(entire skill)",
                        "local": "kept this machine's version",
                        "remote": f"other version saved to {saved}",
                        "kept": "local",
                    })
                else:
                    _apply_skill(ctx, item_id, payload, stamp)
                    applied.append(item_id)
            elif entry.kind == "memory":
                dest = ctx.home / "memories" / items_mod.MEMORY_FILES.get(item_id, "MEMORY.md")
                _backup_path(ctx, stamp, dest)
                atomic_write(dest, payload, mode=0o600)
                applied.append(item_id)
            elif entry.kind == "file":
                dest = ctx.home / {"file:soul": "SOUL.md", "file:cron": "cron/jobs.json"}.get(
                    item_id, item_id.removeprefix("file:")
                )
                _backup_path(ctx, stamp, dest)
                atomic_write(dest, payload, mode=dest.stat().st_mode & 0o777 if dest.exists() else 0o600)
                applied.append(item_id)

            base_items[item_id] = {"oid": entry.oid, "rev": entry.rev, "kind": entry.kind}

        base_doc = _load_base(ctx)
        base_doc["items"] = base_items
        base_doc["config"] = base.get("config") or base_doc.get("config") or {}
        base_doc["env"] = base.get("env") or base_doc.get("env") or {}
        base_doc["saved_at"] = now()
        write_json(ctx.data / "base.json", base_doc)

        _record_conflicts(ctx, conflicts)
        ctx.state["last_pull"] = now()
        ctx.state["last_sync"] = now()
        write_json(ctx.data / "state.json", ctx.state)
        return {
            "applied": applied,
            "removed": removed,
            "already_current": len(skipped),
            "conflicts": conflicts,
            "backup": str(ctx.data / "backups" / stamp) if applied or removed else None,
        }


def _apply_config(ctx: Context, payload: bytes, base: dict, local: dict, prefer: str, stamp: str) -> dict:
    remote = json.loads(payload.decode())
    item = local.get("config")
    local_dict = (item.extra.get("live") if item else None) or {}
    local_text = (item.extra.get("text") if item else "") or ""
    base_conf = base.get("config") or {}

    if not base_conf:
        prefer = "remote"  # first pull on a new device: the store is the source of truth
    result = config_merge.merge(base_conf, local_dict, remote, ctx.policy.is_local_only, prefer=prefer)
    # Conflicts are reported even when the merge changes nothing: "both sides
    # edited this key, you kept yours" is exactly what the person needs to see.
    conflicts = [c.to_json() for c in result.conflicts]
    if result.merged == local_dict:
        return {"changed": False, "conflicts": conflicts, "remote": remote}

    text, _preserved = config_merge.render(local_text, result.merged)
    dest = ctx.home / "config.yaml"
    mode = dest.stat().st_mode & 0o777 if dest.exists() else 0o600
    _backup_path(ctx, stamp, dest)
    atomic_write(dest, text.encode(), mode=mode)
    return {"changed": True, "conflicts": conflicts, "remote": remote}


def _apply_env(ctx: Context, payload: bytes, base: dict, stamp: str) -> dict:
    remote = json.loads(payload.decode())
    path = ctx.home / ".env"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    local = {k: v for k, v in items_mod.parse_env(text).items() if ctx.policy.secret_allowed(k)}
    base_env = base.get("env") or {}
    result = config_merge.merge(base_env, local, remote, lambda _p: False,
                                prefer="remote" if not base_env else "local")
    updates: dict[str, str] = {}
    skipped: list[str] = []
    for key, value in result.merged.items():
        # The store is remote input. A key has to be a name this machine would
        # accept, and the skip rules have to bind on the way in too, or the
        # policy is only a promise the other device can ignore.
        if not env_io.key_is_writable(key) or not ctx.policy.secret_allowed(str(key)):
            skipped.append(str(key))
            continue
        if env_io.refusal(str(key)):
            skipped.append(str(key))
            continue
        updates[str(key)] = str(value)
    removals = {k for k in local if k not in updates}
    if updates == local and not removals:
        return {"changed": False, "conflicts": [], "remote": remote, "skipped": skipped}
    rendered = items_mod.render_env(text, updates, removals)
    _backup_path(ctx, stamp, path)
    env_io.write(path, rendered)
    conflicts = [c.to_json() for c in result.conflicts if c.path in updates]
    return {"changed": True, "conflicts": conflicts, "remote": remote, "skipped": skipped}


def _apply_skill(ctx: Context, item_id: str, payload: bytes, stamp: str) -> None:
    name = item_id.split(":", 1)[1]
    existing = items_mod.iter_skills(ctx.home).get(name)
    if existing:
        _backup_path(ctx, stamp, existing)
    dest = existing or (items_mod.skill_root(ctx.home) / name)
    if dest.exists():
        shutil.rmtree(dest)
    items_mod.unpack_dir(payload, dest)


def _remove_item(ctx: Context, item_id: str, stamp: str) -> bool:
    if item_id.startswith("skill:"):
        name = item_id.split(":", 1)[1]
        path = items_mod.iter_skills(ctx.home).get(name)
        if path is None:
            return False
        _backup_path(ctx, stamp, path)
        shutil.rmtree(path)
        return True
    targets = {
        "memory:agent": ctx.home / "memories" / "MEMORY.md",
        "memory:user": ctx.home / "memories" / "USER.md",
        "file:soul": ctx.home / "SOUL.md",
        "file:cron": ctx.home / "cron" / "jobs.json",
    }
    dest = targets.get(item_id)
    if dest and dest.exists():
        _backup_path(ctx, stamp, dest)
        dest.unlink()
        return True
    return False


# ── backups ──────────────────────────────────────────────────────────────────
def _backup_path(ctx: Context, stamp: str, src: Path) -> None:
    """Copy one path into this pull's snapshot; never fail a sync over a backup."""
    try:
        rel = src.relative_to(ctx.home)
    except ValueError:
        return
    dest = ctx.data / "backups" / stamp / rel
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        elif src.exists():
            shutil.copy2(src, dest)
    except OSError:
        return
    try:
        old = sorted(p for p in (ctx.data / "backups").iterdir() if p.is_dir())[:-10]
        for p in old:
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def undo(home: Path) -> dict:
    """Restore the files from the newest backup snapshot."""
    data = data_dir(Path(home))
    bases = data / "backups"
    if not bases.exists():
        raise HerdError("No backup to restore yet.")
    snaps = sorted(p for p in bases.iterdir() if p.is_dir())
    if not snaps:
        raise HerdError("No backup to restore yet.")
    latest = snaps[-1]
    restored = []
    for src in latest.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(latest)
        dest = Path(home) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        restored.append(str(rel))
    return {"ok": True, "restored_from": str(latest), "files": restored}


# ── status / diff ────────────────────────────────────────────────────────────
def status(home: Path) -> dict:
    ctx = open_context(home)
    ctx.store.refresh()
    base = _load_base(ctx)
    local = items_mod.scan(ctx.home, ctx.policy, include_cron=bool(ctx.state.get("sync_cron")))
    merged = ctx.store.merged()
    rows = []
    for item_id in sorted(set(local) | set(merged) | set(base.get("items") or {})):
        mine = local.get(item_id)
        remote = merged.get(item_id)
        known = (base.get("items") or {}).get(item_id) or {}
        local_oid = crypto.object_id(ctx.key, mine.payload) if mine else ""
        if remote and remote.device_id == ctx.device["id"] and not mine:
            state = "only-here"
        elif mine and remote and remote.deleted:
            state = "removed-elsewhere"
        elif mine and not remote:
            state = "not-pushed"
        elif mine and remote and local_oid != remote.oid:
            state = "differs"
        elif mine:
            state = "in-sync"
        else:
            state = "not-local"
        rows.append({
            "item": item_id,
            "kind": (mine.kind if mine else (remote.kind if remote else "unknown")),
            "state": state,
            "size": mine.size if mine else (remote.size if remote else 0),
        })
    devices = []
    for path in sorted((ctx.store.root / "devices").glob("*.json")):
        doc = read_json(path, {}) or {}
        d = doc.get("device") or {}
        devices.append({
            "id": d.get("id") or path.stem,
            "name": d.get("name") or path.stem,
            "platform": d.get("platform") or "?",
            "last_push": doc.get("updated_at"),
            "items": len(doc.get("items") or {}),
            "this_device": (d.get("id") or path.stem) == ctx.device["id"],
        })
    return {
        "device": ctx.device,
        "store": str(ctx.store.root),
        "remote": ctx.state.get("remote") or None,
        "last_sync": ctx.state.get("last_sync"),
        "last_sync_human": human_age(ctx.state.get("last_sync") or 0),
        "secrets": ctx.policy.sync_secrets,
        "items": rows,
        "counts": {
            "in_sync": sum(1 for r in rows if r["state"] == "in-sync"),
            "differs": sum(1 for r in rows if r["state"] == "differs"),
            "not_pushed": sum(1 for r in rows if r["state"] == "not-pushed"),
            "not_local": sum(1 for r in rows if r["state"] == "not-local"),
        },
        "devices": devices,
    }


def diff(home: Path) -> dict:
    """What a sync would do, without doing it."""
    state = status(home)
    return {
        "would_push": [r["item"] for r in state["items"] if r["state"] in ("differs", "not-pushed")],
        "would_pull": [r["item"] for r in state["items"] if r["state"] in ("not-local", "removed-elsewhere")],
        "in_sync": [r["item"] for r in state["items"] if r["state"] == "in-sync"],
        "device": state["device"],
    }


def conflicts(home: Path) -> list[dict]:
    """Conflicts the user still has to decide.

    Entries are filtered against the live config: if the value this machine
    holds now equals the one the store offered, the disagreement has been
    settled by hand and must not keep showing up in the list.
    """
    data = data_dir(Path(home))
    entries = (read_json(data / "conflicts.json", {}) or {}).get("entries", []) or []
    if not entries:
        return []
    try:
        live = yamlutil.safe_load((Path(home) / "config.yaml").read_text()) or {}
    except Exception:
        return entries
    settled = []
    for row in entries:
        path = row.get("path") or ""
        node = live
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if row.get("item") == "config" and node is not None and str(node) == str(row.get("remote")):
            continue
        settled.append(row)
    return settled


def _record_conflicts(ctx: Context, found: list[dict]) -> None:
    """Record the disagreements the last pull actually met.

    Not an append-only log: once the two sides agree again the entry has to go,
    otherwise `hermes sync conflicts` lists every disagreement the machine has
    ever had and the command becomes noise the user learns to ignore.
    """
    path = ctx.data / "conflicts.json"
    stamp = iso()
    entries = [dict(row, at=stamp) for row in found]
    write_json(path, {"entries": entries[-200:]})


def sync(home: Path) -> dict:
    """Pull first when clean, push first when this device has unsynced edits."""
    ctx = open_context(home)
    base = _load_base(ctx)
    local = items_mod.scan(ctx.home, ctx.policy, include_cron=bool(ctx.state.get("sync_cron")))
    dirty = False
    for item_id, item in local.items():
        known = (base.get("items") or {}).get(item_id) or {}
        if not known or known.get("oid") != crypto.object_id(ctx.key, item.payload):
            dirty = True
            break
    first = push(ctx) if dirty else pull(ctx)
    second = pull(ctx) if dirty else push(ctx)
    return {"ok": True, "order": "push-then-pull" if dirty else "pull-then-push", "first": first, "second": second}
