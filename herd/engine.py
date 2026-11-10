"""The sync engine: init, join, pull, push, and the safety net around writes.

Every function takes the Hermes home explicitly so a whole two-device exchange
can be exercised in one process during tests, instead of only in production.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config_merge, crypto, items as items_mod, pairing, store as store_mod, yamlutil
from . import env_io
from .policy import Policy
from .store import Entry, Store, StoreError
from .util import atomic_write, file_lock, human_age, iso, now, read_json, write_json

PLUGIN_ID = "herd"
STATE_VERSION = 1
DEFAULT_STORE = "~/herd-store"

# The only item ids that may name a file on disk. Anything else is either an
# unknown kind or a path someone made up, and both are refused.
FILE_TARGETS = {"file:soul": "SOUL.md", "file:cron": "cron/jobs.json"}
_SKILL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _inside(home: Path, target: Path) -> bool:
    """True when *target* resolves inside *home* (the containment check)."""
    try:
        target.resolve().relative_to(home.resolve())
        return True
    except (ValueError, OSError):
        return False


def _row(entry) -> dict:
    return {"oid": entry.oid, "rev": entry.rev, "kind": entry.kind, "device": entry.device_id}


def _decision(local_oid: str, base_row: dict | None, pushed_row: dict | None, entry) -> str:
    """same | adopt | conflict, from causality rather than who pushed last."""
    base_row = base_row or {}
    pushed_row = pushed_row or {}
    if local_oid and local_oid == entry.oid:
        return "same"
    if base_row.get("rev") and str(entry.oid or "") == str(base_row.get("oid") or ""):
        # They still hold the agreed value. If we changed it without publishing
        # something that outranks the herd, this is a disagreement, not a
        # private edit — otherwise both sides republish forever.
        if local_oid != str(base_row.get("oid") or ""):
            pushed_rev = int(pushed_row.get("rev") or 0)
            # Only a *published* change can lose to a newer herd revision. An
            # unpublished edit is simply this machine's news to send.
            if pushed_rev and int(entry.rev) > pushed_rev:
                return "conflict"
        return "local"                       # only this side changed it: no conflict
    if local_oid == str(base_row.get("oid") or ""):
        # Unchanged here. Take theirs only when theirs descends from the entry we
        # agreed on; a sibling edit must surface as a conflict instead.
        if not base_row.get("rev"):
            return "adopt"
        if (entry.parent_rev, entry.parent_dev) == (int(base_row["rev"]), str(base_row.get("device") or "")):
            return "adopt"
        return "conflict"
    if local_oid == str(pushed_row.get("oid") or "") and pushed_row.get("rev") and (
            entry.parent_rev, entry.parent_dev) == (int(pushed_row["rev"]), str(pushed_row.get("device") or "")):
        return "adopt"                       # they extended exactly what we published
    return "conflict"


def _deletable(item_id: str) -> bool:
    """Only ids this build knows how to scan may be tombstoned."""
    return (item_id in FILE_TARGETS or item_id in items_mod.MEMORY_FILES
            or item_id in ("config", "env") or item_id.startswith("skill:"))


def data_dir(home: Path) -> Path:
    """Per-profile, per-machine state. plugin-data survives plugin updates."""
    # The caller's home is authoritative. Resolving it through the process keeps
    # working in a single-profile CLI and breaks in a gateway thread, where the
    # active profile is not the one this call was given.
    return Path(home) / "plugin-data" / PLUGIN_ID


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
            raise HerdError("This machine is not in a herd yet. Run `hermes sync pair`.")
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
         sync_secrets: bool = False, include_cron: bool = False) -> dict:
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


def join(home: Path, store_path: str, code: str, *, name: str | None = None,
         sync_secrets: bool = False) -> dict:
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
    policy.sync_secrets = bool(sync_secrets)
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
    ctx.state["first_pull"] = True
    write_json(ctx.data / "state.json", ctx.state)
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

        frozen = set(ctx.state.get("frozen") or [])
        for item_id, item in local.items():
            if item_id in frozen:
                continue                          # a disagreement the person must settle
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
            seen = (base.get("items") or {}).get(item_id) or {}
            my_items[item_id] = Entry(item_id=item_id, oid=oid, kind=item.kind, rev=rev,
                                      device_id=ctx.device["id"], mtime=item.mtime, size=item.size,
                                      parent_rev=int(seen.get("rev") or 0),
                                      parent_dev=str(seen.get("device") or ""))
            changed.append(item_id)

        here = items_mod.current_platform()
        platform_skipped = {
            f"skill:{name}" for name, path in items_mod.iter_skills(ctx.home).items()
            if (lambda pl: bool(pl) and here not in pl)(items_mod.skill_platforms(path))
        }
        for item_id in set((base.get("pushed") or {})) - left:
            if item_id in platform_skipped or not _deletable(item_id):
                # Absent from scan is not the same as deleted: this build may
                # simply not know the item, or may be the wrong OS for it.
                continue
            if not ((base.get("pushed") or {}).get(item_id) or {}).get("oid"):
                continue  # already tombstoned
            previous = my_items.get(item_id)
            rev = max(clock, int(((base.get("items") or {}).get(item_id) or {}).get("rev") or 0),
                      previous.rev if previous else 0, merged[item_id].rev if item_id in merged else 0) + 1
            clock = rev
            seen = (base.get("items") or {}).get(item_id) or {}
            my_items[item_id] = Entry(item_id=item_id, oid="", kind=(previous.kind if previous else "file"),
                                      rev=rev, device_id=ctx.device["id"], deleted=True,
                                      parent_rev=int(seen.get("rev") or 0),
                                      parent_dev=str(seen.get("device") or ""))
            removed.append(item_id)

        ctx.store.write_device({**ctx.device, "created_at": ctx.device.get("created_at", now())}, my_items, clock)
        published = ctx.store.publish(f"herd: {ctx.device.get('name', 'device')} push {len(changed)} item(s)")

        # The base is the last state both sides agreed on, not "what I just
        # wrote". Advancing it here is what turned a three-way merge into
        # last-writer-wins: the writer's next pull saw local == base and took
        # the peer's value as "only they changed it".
        doc = _load_base(ctx)
        pushed = dict(doc.get("pushed") or {})
        for item_id, entry in my_items.items():
            pushed[item_id] = _row(entry)
        doc["pushed"] = pushed
        base_items = dict(doc.get("items") or {})
        for item_id, entry in my_items.items():
            if item_id not in base_items and not entry.deleted:
                base_items[item_id] = _row(entry)
        doc["items"] = base_items
        # Seed the merge ancestor once, on the first push, so a later deletion
        # can be told from a value this machine never had. It is never rewritten
        # afterwards: the ancestor only moves when a pull agrees on a value.
        if not doc.get("config"):
            doc["config"] = items_mod.scrub(_local_dict(local, "config"), ctx.policy)
        if not doc.get("env"):
            doc["env"] = _local_dict(local, "env")
        doc["saved_at"] = now()
        write_json(ctx.data / "base.json", doc)

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
        deferred: list[str] = []
        resolved: set[str] = set()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        first = bool(ctx.state.pop("first_pull", False))
        frozen = set(ctx.state.get("frozen") or [])
        pushed_map = base.get("pushed") or {}

        def freeze(item_id: str) -> None:
            """Hold a published disagreement still; never hold an unpublished edit."""
            if (pushed_map.get(item_id) or {}).get("rev"):
                frozen.add(item_id)

        write_json(ctx.data / "state.json", ctx.state)

        local = items_mod.scan(ctx.home, ctx.policy, include_cron=bool(ctx.state.get("sync_cron")))
        by_item = ctx.store.entries_by_item()
        for item_id, entry in sorted(merged.items()):
            if entry.device_id == ctx.device["id"]:
                continue
            known = base_items.get(item_id) or {}
            if known.get("oid") == entry.oid and known.get("rev") == entry.rev:
                skipped.append(item_id)
                continue

            record_base = True
            local_item = local.get(item_id)
            local_oid = crypto.object_id(ctx.key, local_item.payload) if local_item else ""
            base_oid = str((base_items.get(item_id) or {}).get("oid") or "")

            if item_id in frozen and local_oid != entry.oid:
                conflicts.append({"item": item_id, "path": item_id, "kept": "local",
                                  "local": "kept this machine's version",
                                  "remote": "an unresolved disagreement on another machine"})
                continue

            # A value this device published may outrank a peer's edit, which hides
            # the disagreement behind the winner. Look at every device's entry: a
            # rival that is neither ours nor the agreed value is a conflict.
            if local_oid != base_oid:
                rivals = [e for e in by_item.get(item_id, [])
                          if e.device_id != ctx.device["id"]
                          and e.oid not in ("", local_oid, base_oid, entry.oid)]
                if rivals:
                    freeze(item_id)
                    conflicts.append({"item": item_id, "path": item_id, "kept": "local",
                                      "local": "kept this machine's version",
                                      "remote": f"another machine also changed it ({rivals[0].device_id[:6]})"})
                    continue
            if entry.deleted and local_oid and local_oid != base_oid:
                freeze(item_id)
                conflicts.append({"item": item_id, "path": item_id, "kept": "local",
                                  "local": "kept this machine's version", "remote": "another machine deleted it"})
                continue

            if entry.deleted:
                if _remove_item(ctx, item_id, stamp):
                    removed.append(item_id)
                base_items[item_id] = {"oid": "", "rev": entry.rev, "kind": entry.kind}
                continue

            try:
                payload = ctx.store.get(ctx.key, entry.oid)
                sealed_id, sealed_kind, body = items_mod.open_item(payload)
            except (StoreError, crypto.TamperedBlob, ValueError) as exc:
                skipped.append(f"{item_id}: {exc}")
                continue
            if sealed_id != item_id or sealed_kind != entry.kind:
                skipped.append(f"{item_id}: payload belongs to {sealed_id} ({sealed_kind})")
                continue

            if entry.kind == "config":
                item = local.get("config")
                local_oid = crypto.object_id(ctx.key, item.payload) if item else ""
                decision = _decision(local_oid, base_items.get(item_id), (base.get("pushed") or {}).get(item_id), entry)
                if first and decision == "conflict":
                    decision = "adopt"
                if decision in ("same", "local"):
                    if decision == "same":
                        frozen.discard(item_id)
                        resolved.add(item_id)
                    base_items[item_id] = _row(entry)
                    base["config"] = json.loads(body.decode()) if body else {}
                    continue
                if decision == "conflict":
                    record_base = False
                result = _apply_config(ctx, body, base, local, "remote" if decision == "adopt" else "local",
                                       stamp, report=(decision == "conflict"))
                conflicts.extend({**c, "item": item_id} for c in result["conflicts"])
                if result["changed"]:
                    applied.append(item_id)
                if decision == "adopt":
                    resolved.add(item_id)
                    base["config"] = result["remote"]
            elif entry.kind == "env":
                if not ctx.policy.sync_secrets:
                    # Nothing to decrypt and nothing to open: secrets are off on
                    # this machine. Left out of the base, so enabling them later
                    # picks the item up instead of treating it as current.
                    deferred.append(item_id)
                    continue
                item = local.get("env")
                local_oid = crypto.object_id(ctx.key, item.payload) if item else ""
                decision = _decision(local_oid, base_items.get(item_id), (base.get("pushed") or {}).get(item_id), entry)
                if first and decision == "conflict":
                    decision = "adopt"
                if decision in ("same", "local"):
                    if decision == "same":
                        frozen.discard(item_id)
                        resolved.add(item_id)
                    base_items[item_id] = _row(entry)
                    base["env"] = json.loads(body.decode()) if body else {}
                    continue
                if decision == "conflict":
                    record_base = False
                result = _apply_env(ctx, body, base, stamp,
                                    prefer="remote" if decision == "adopt" else "local",
                                    report=(decision == "conflict"))
                conflicts.extend({**c, "item": item_id} for c in result["conflicts"])
                if result["changed"]:
                    applied.append(item_id)
                if decision == "adopt":
                    resolved.add(item_id)
                    base["env"] = result["remote"]
            elif entry.kind == "skill":
                platforms = items_mod.skill_platforms_from_blob(body)
                if platforms and items_mod.current_platform() not in platforms:
                    # Not ours to run. Remember the entry so we do not retry it,
                    # but never install it and never tombstone it.
                    base_items[item_id] = _row(entry)
                    skipped.append(f"{item_id}: for {', '.join(platforms)}")
                    continue
                item = local.get(item_id)
                local_oid = crypto.object_id(ctx.key, item.payload) if item else ""
                decision = _decision(local_oid, base_items.get(item_id), (base.get("pushed") or {}).get(item_id), entry)
                if first and decision == "conflict":
                    decision = "adopt"
                if decision in ("same", "local"):
                    if decision == "same":
                        frozen.discard(item_id)
                        resolved.add(item_id)
                    base_items[item_id] = _row(entry)
                    continue
                if decision == "conflict":
                    # Both machines edited the same skill. Keep this one, but put
                    # the other side somewhere the user can reach — a skill is a
                    # directory, so "merge" would be a guess.
                    saved = ctx.data / "conflicts" / stamp / f"{item_id.split(':', 1)[1]}.tar.gz"
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes(body)
                    conflicts.append({
                        "item": item_id,
                        "path": "(entire skill)",
                        "local": "kept this machine's version",
                        "remote": f"other version saved to {saved}",
                        "kept": "local",
                    })
                else:
                    try:
                        _apply_skill(ctx, item_id, body, stamp)
                        applied.append(item_id)
                    except Exception as exc:  # noqa: BLE001 - a bad skill is one item
                        record_base = False          # retry next pull instead of claiming it landed
                        skipped.append(f"{item_id}: {type(exc).__name__}: {exc}")
            elif entry.kind == "memory":
                name = items_mod.MEMORY_FILES.get(item_id)
                dest = ctx.home / "memories" / name if name else None
                if dest is None or not _inside(ctx.home, dest):
                    skipped.append(f"{item_id}: not a memory file this build knows")
                    continue
                item = local.get(item_id)
                local_oid = crypto.object_id(ctx.key, item.payload) if item else ""
                decision = _decision(local_oid, base_items.get(item_id), (base.get("pushed") or {}).get(item_id), entry)
                if first and decision == "conflict":
                    decision = "adopt"          # a machine joining takes the herd's memory
                if decision in ("same", "local"):
                    if decision == "same":
                        frozen.discard(item_id)
                        resolved.add(item_id)
                    base_items[item_id] = _row(entry)
                    continue
                if decision == "conflict":
                    record_base = False
                    freeze(item_id)
                    conflicts.append({"item": item_id, "path": item_id,
                                      "local": "kept this machine's text",
                                      "remote": "store has another version", "kept": "local"})
                    base_items[item_id] = _row(entry)
                    continue
                try:
                    _backup_path(ctx, stamp, dest)
                    atomic_write(dest, body, mode=0o600)
                    applied.append(item_id)
                except Exception as exc:  # noqa: BLE001 - one item must not stop the pull
                    record_base = False
                    skipped.append(f"{item_id}: {type(exc).__name__}: {exc}")
            elif entry.kind == "file":
                name = FILE_TARGETS.get(item_id)
                dest = ctx.home / name if name else None
                if dest is None or not _inside(ctx.home, dest):
                    skipped.append(f"{item_id}: not a file item this build writes")
                    continue
                try:
                    _backup_path(ctx, stamp, dest)
                    atomic_write(dest, body, mode=dest.stat().st_mode & 0o777 if dest.exists() else 0o600)
                    applied.append(item_id)
                except Exception as exc:  # noqa: BLE001
                    record_base = False
                    skipped.append(f"{item_id}: {type(exc).__name__}: {exc}")

            if record_base:
                base_items[item_id] = _row(entry)

        base_doc = _load_base(ctx)
        base_doc["items"] = base_items
        base_doc["config"] = base.get("config") or base_doc.get("config") or {}
        base_doc["env"] = base.get("env") or base_doc.get("env") or {}
        base_doc["saved_at"] = now()
        write_json(ctx.data / "base.json", base_doc)

        _record_conflicts(ctx, conflicts, resolved)
        ctx.state["frozen"] = sorted(frozen)
        ctx.state["last_pull"] = now()
        ctx.state["last_sync"] = now()
        write_json(ctx.data / "state.json", ctx.state)
        return {
            "applied": applied,
            "removed": removed,
            "already_current": len(skipped),
            "deferred": deferred,
            "conflicts": conflicts,
            "backup": str(ctx.data / "backups" / stamp) if applied or removed else None,
        }


def _apply_config(ctx: Context, payload: bytes, base: dict, local: dict, prefer: str, stamp: str,
                  report: bool = True) -> dict:
    remote = json.loads(payload.decode())
    item = local.get("config")
    local_dict = (item.extra.get("live") if item else None) or {}
    local_text = (item.extra.get("text") if item else "") or ""
    base_conf = base.get("config") or {}

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


def _apply_env(ctx: Context, payload: bytes, base: dict, stamp: str, prefer: str = "",
               report: bool = True) -> dict:
    if not ctx.policy.sync_secrets:
        # Off means off. Nothing here opens `.env`, so a peer's env item has no
        # path into this machine while the person has not asked for it.
        return {"changed": False, "conflicts": [], "remote": base.get("env") or {}, "skipped": []}
    remote = json.loads(payload.decode())
    path = ctx.home / ".env"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    local = {k: v for k, v in items_mod.parse_env(text).items() if ctx.policy.secret_allowed(k)}
    base_env = base.get("env") or {}
    result = config_merge.merge(base_env, local, remote, lambda _p: False,
                                prefer=prefer or ("remote" if not base_env else "local"))
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
        if "\n" in str(value) or "\r" in str(value):
            # A value cannot carry a line break into `.env` without becoming a
            # second line, and Hermes's own writer strips them for this reason.
            skipped.append(f"{key} (contains a line break)")
            continue
        updates[str(key)] = str(value)
    removals = {k for k in local if k not in updates}
    found = [c.to_json() for c in result.conflicts if c.path in updates] if report else []
    if updates == local and not removals:
        return {"changed": False, "conflicts": found, "remote": remote, "skipped": skipped}
    rendered = items_mod.render_env(text, updates, removals)
    _backup_path(ctx, stamp, path)
    env_io.write(path, rendered)
    return {"changed": True, "conflicts": found, "remote": remote, "skipped": skipped}


def _apply_skill(ctx: Context, item_id: str, payload: bytes, stamp: str) -> None:
    name = item_id.split(":", 1)[1]
    if not _SKILL_NAME.match(name) or name in (".", ".."):
        raise ValueError(f"unsafe skill name {name!r}")
    if not _inside(items_mod.skill_root(ctx.home), items_mod.skill_root(ctx.home) / name):
        raise ValueError(f"skill {name!r} escapes the skills directory")
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
def gc(home: Path, keep_days: int = 30, dry_run: bool = False) -> dict:
    """Drop objects no device references, and old backups, from this machine's view.

    Only objects older than *keep_days* are candidates: a device that wrote a
    blob and crashed before writing its manifest leaves an unreferenced object
    that is still live, so age is the only safe signal. Referenced objects are
    never touched, and neither is the store's own metadata.
    """
    ctx = open_context(home)
    cutoff = now() - max(0, int(keep_days)) * 86400

    # References live in the device manifests. The base holds an ancestor oid
    # for change detection only; nothing fetches it, so it must not pin an
    # object forever.
    referenced: set[str] = set()
    for path in sorted((ctx.store.root / "devices").glob("*.json")):
        data = read_json(path, {}) or {}
        for row in (data.get("items") or {}).values():
            oid = (row or {}).get("oid") if isinstance(row, dict) else None
            if oid:
                referenced.add(str(oid))

    victims = [p for oid, p, mtime in ctx.store.objects()
               if oid not in referenced and mtime < cutoff]
    freed = sum(p.stat().st_size for p in victims if p.exists())
    if not dry_run:
        for path in victims:
            with contextlib.suppress(OSError):
                path.unlink()

    stale_dirs = []
    for folder in (ctx.data / "backups", ctx.data / "conflicts"):
        if not folder.exists():
            continue
        for child in folder.iterdir():
            if child.is_dir() and child.stat().st_mtime < cutoff:
                stale_dirs.append(child)
    if not dry_run:
        for child in stale_dirs:
            shutil.rmtree(child, ignore_errors=True)

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "keep_days": int(keep_days),
        "objects_removed": len(victims),
        "objects_kept": len(referenced),
        "bytes_freed": freed,
        "folders_removed": len(stale_dirs),
    }


def set_secrets(home: Path, on: bool) -> dict:
    """Turn credential sync on or off for this machine, and persist the answer."""
    data = data_dir(home)
    ctx = open_context(home)
    ctx.policy.sync_secrets = bool(on)
    ctx.policy.save(data / "policy.yaml")
    return {"ok": True, "secrets": bool(on), "policy": str(data / "policy.yaml")}


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
        # Count what still disagrees, not every row ever written: a pull that
        # settles an item leaves a row behind until it is forgotten.
        "conflicts": len(conflicts(home)),
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
        live = yamlutil.safe_load((Path(home) / "config.yaml").read_text(encoding="utf-8")) or {}
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


def _record_conflicts(ctx: Context, found: list[dict], resolved: set[str] | None = None) -> None:
    """Record the disagreements the last pull actually met.

    Not an append-only log: once the two sides agree again the entry has to go,
    otherwise `hermes sync conflicts` lists every disagreement the machine has
    ever had and the command becomes noise the user learns to ignore.
    """
    path = ctx.data / "conflicts.json"
    stamp = iso()
    resolved = resolved or set()
    # Only what this machine refused to take is a live disagreement. A key that
    # was adopted was never a choice, and recording it leaves a row that no
    # command can show and every count includes.
    found = [row for row in found if row.get("kept") == "local"]
    previous = [row for row in ((read_json(path, {}) or {}).get("entries") or [])
                if row.get("item") not in resolved]
    merged: dict[tuple, dict] = {}
    for row in previous:
        merged[(row.get("item"), row.get("path"))] = row
    for row in found:
        merged[(row.get("item"), row.get("path"))] = dict(row, at=stamp)
    write_json(path, {"entries": list(merged.values())[-200:]})


def sync(home: Path) -> dict:
    """Merge what the herd has, then publish what this machine has.

    Pull before push, always: pushing first is what hid a disagreement, because
    the writer overwrote the store before reading it.
    """
    ctx = open_context(home)
    first = pull(ctx)
    second = push(ctx)
    return {"ok": True, "order": "pull-then-push", "first": first, "second": second}


# ── pairing ──────────────────────────────────────────────────────────────────
def pair_start(home: Path, store_path: str | None = None, *, remote: str = "",
               name: str | None = None, ttl: int = pairing.DEFAULT_TTL) -> dict:
    """Make a short, single-use code another machine can finish pairing with.

    The store is created if this machine has none, so the first command a person
    runs does not ask them to choose a folder before they know what it is for.
    """
    home = Path(home)
    if load_state(data_dir(home)).get("store"):
        ctx = open_context(home)
    else:
        target = Path(store_path or DEFAULT_STORE).expanduser()
        if (target / "store.json").exists():
            raise HerdError(
                f"{target} already holds a herd. If it is this one, pair with the code "
                f"from the machine that made it; otherwise pick another folder:\n"
                f"  hermes sync pair {target}-2"
            )
        init(home, str(target), remote=remote, name=name)
        ctx = open_context(home)

    code = pairing.new_code()
    payload = {
        # The recovery code, not the derived key: the store's salt turns one into
        # the other, and another machine has to reproduce that derivation itself.
        "code": ctx.identity.get("code", ""),
        "store": str(ctx.store.root),
        "remote": ctx.state.get("remote") or "",
        "device": ctx.device.get("name") or "",
    }
    doc = pairing.seal(code, payload, ctx.store.store_id, ttl=ttl)
    atomic_write(ctx.store.root / "pairing.json", json.dumps(doc).encode(), mode=0o644)
    return {
        "code": code,
        "store": str(ctx.store.root),
        "remote": payload["remote"] or None,
        "device": ctx.device,
        "expires_in": ttl,
    }


def pair_finish(home: Path, code: str, store_path: str | None = None, *, name: str | None = None,
                sync_secrets: bool = False) -> dict:
    """Join with a pairing code instead of the long recovery code."""
    home = Path(home)
    path = Path(store_path or DEFAULT_STORE).expanduser()
    pfile = path / "pairing.json"
    if not pfile.exists():
        raise HerdError(
            f"No pairing code is waiting at {path}.\n"
            "Run `hermes sync pair` on the machine that already syncs, then pass the "
            "same store folder here — or use `hermes sync join <store> --code HERD-…` "
            "with the recovery code."
        )
    meta = read_json(path / "store.json", {}) or {}
    payload = pairing.open_payload(code, read_json(pfile, {}) or {}, str(meta.get("store_id") or ""))
    target = str(path) if path.exists() else (payload.get("remote") or str(path))
    joined = join(home, target, str(payload.get("code") or ""), name=name, sync_secrets=sync_secrets)
    with contextlib.suppress(OSError):
        pfile.unlink()
    return {**joined, "paired_with": payload.get("device") or "another machine"}


# ── resolving a disagreement ─────────────────────────────────────────────────
def _forget_conflict(ctx: Context, item_id: str) -> None:
    frozen = set(ctx.state.get("frozen") or [])
    if item_id in frozen:
        frozen.discard(item_id)
        ctx.state["frozen"] = sorted(frozen)
        write_json(ctx.data / "state.json", ctx.state)
    _record_conflicts(ctx, [], resolved={item_id})


def _write_config_value(ctx: Context, dotted: str, value) -> None:
    """Set one dotted key in config.yaml, preserving the rest of the file."""
    dest = ctx.home / "config.yaml"
    text = dest.read_text(encoding="utf-8") if dest.exists() else ""
    data = yamlutil.safe_load(text) or {}
    node = data
    parts = [p for p in dotted.split(".") if p]
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value
    rendered, _ = config_merge.render(text, data)
    mode = dest.stat().st_mode & 0o777 if dest.exists() else 0o600
    atomic_write(dest, rendered.encode(), mode=mode)


def _write_env_value(ctx: Context, name: str, value) -> None:
    path = ctx.home / ".env"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    if value is None:
        text = items_mod.render_env(text, {}, {name})
    else:
        text = items_mod.render_env(text, {name: str(value)}, set())
    env_io.write(path, text)


def _peer_entry(ctx: Context, item_id: str):
    """The other machines' newest entry for an item, ignoring our own."""
    best = None
    for doc in ctx.store.other_manifests(ctx.device["id"]):
        raw = (doc.get("items") or {}).get(item_id)
        if not raw or raw.get("deleted"):
            continue
        if best is None or int(raw.get("rev") or 0) > int(best[1].get("rev") or 0):
            best = (doc, raw)
    return best


def resolve(home: Path, item_id: str, choice: str) -> dict:
    """Settle one conflict: keep this machine's value, or take the other machine's.

    "Mine" republishes this machine's value; a machine that had not edited the
    item adopts it on its next pull, and one that had edited it is asked.
    "Theirs" writes the *peer's* value here — not the store's newest entry,
    which may be this machine's own from the sync that created the conflict.
    """
    if choice not in ("mine", "theirs"):
        raise HerdError("Choose `mine` or `theirs`.")
    home = Path(home)
    ctx = open_context(home)
    rows = (read_json(ctx.data / "conflicts.json", {}) or {}).get("entries") or []
    row = next((r for r in rows if r.get("item") == item_id), None)
    if row is None:
        raise HerdError(f"No conflict is recorded for {item_id}. `hermes sync conflicts` lists them.")

    if choice == "mine":
        _forget_conflict(ctx, item_id)
        report = push(ctx)
        return {"ok": True, "item": item_id, "choice": "mine", **report}

    applied = "value"
    if item_id == "config" and row.get("path"):
        _write_config_value(ctx, str(row["path"]), row.get("remote"))
    elif item_id == "env" and row.get("path"):
        _write_env_value(ctx, str(row["path"]), row.get("remote"))
    else:
        peer = _peer_entry(ctx, item_id)
        if peer is None:
            raise HerdError(
                f"{item_id} has no other machine's copy in the store — the disagreement is "
                "about a value this machine holds. Keep yours instead."
            )
        _doc, raw = peer
        body = ctx.store.get(ctx.key, str(raw["oid"]))
        kind = raw.get("kind") or item_id.split(":")[0]
        if kind == "skill":
            _apply_skill(ctx, item_id, body, time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
        elif kind == "memory":
            dest = ctx.home / "memories" / ("MEMORY.md" if item_id == "memory:agent" else "USER.md")
            atomic_write(dest, body, mode=0o600)
        elif kind == "file" and item_id in FILE_TARGETS:
            atomic_write(ctx.home / FILE_TARGETS[item_id], body, mode=0o600)
        else:
            raise HerdError(f"{item_id} is not a kind this machine can adopt.")
        applied = "file"

    # The local item now equals what the peer published, so the next push is a
    # no-op and the base can record agreement.
    base = _load_base(ctx)
    local = items_mod.scan(ctx.home, ctx.policy, include_cron=bool(ctx.state.get("sync_cron")))
    entry = local.get(item_id)
    items = dict(base.get("items") or {})
    if entry is not None:
        known = items.get(item_id) or {}
        items[item_id] = {"oid": crypto.object_id(ctx.key, entry.payload),
                          "rev": known.get("rev", 0), "kind": entry.kind}
    base["items"] = items
    if item_id == "config" and entry is not None:
        base["config"] = entry.extra.get("live") or {}
    if item_id == "env":
        env_path = ctx.home / ".env"
        text = env_path.read_text(encoding="utf-8", errors="ignore") if env_path.exists() else ""
        base["env"] = items_mod.parse_env(text)
    write_json(ctx.data / "base.json", base)

    _forget_conflict(ctx, item_id)
    pushed = push(ctx)
    return {"ok": True, "item": item_id, "choice": "theirs", "applied": applied, "pushed": pushed}


# ── one line about the herd ──────────────────────────────────────────────────
def summary(home: Path) -> str:
    """The sentence a person should be able to read at a glance."""
    try:
        state = status(home)
    except HerdError as exc:
        return str(exc)
    counts = state["counts"]
    parts: list[str] = []
    if state["conflicts"]:
        parts.append(f"{state['conflicts']} conflict(s) to review")
    waiting_out = counts["differs"] + counts["not_pushed"]
    if waiting_out:
        parts.append(f"{waiting_out} change(s) to push")
    if counts["not_local"]:
        parts.append(f"{counts['not_local']} change(s) to pull")
    parts = parts or ["In sync"]
    machines = len(state["devices"])
    return f"{' · '.join(parts)} · {machines} machine{'s' if machines != 1 else ''} · synced {state['last_sync_human']}"
