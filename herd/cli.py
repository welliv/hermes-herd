"""``hermes sync ...`` — the surface a person actually uses.

Every command prints something readable first and JSON only when asked, so a
terminal and an agent can share the same entry point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import engine
from .policy import DEFAULT_LOCAL_ONLY, DEFAULT_SECRET_SKIP, Policy
from .util import hermes_home, human_age


# ── output helpers ───────────────────────────────────────────────────────────
def _print(msg: str = "") -> None:
    print(msg)


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


def _json(args) -> bool:
    """The bare `hermes sync` path has no --json flag; treat absence as false."""
    return bool(getattr(args, "json", False))


def _fail(exc: Exception) -> int:
    print(f"Herd: {exc}", file=sys.stderr)
    return 1


def _code_block(code: str) -> None:
    _print()
    _print("  Your recovery code — copy it to every machine you want in the herd:")
    _print()
    _print(f"    {code}")
    _print()
    _print("  It decrypts the store. Anyone holding it can read your keys, and it")
    _print("  cannot be reset. Keep it in a password manager, not in this terminal's")
    _print("  scrollback alone.")


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_init(args) -> int:
    home = hermes_home()
    data = engine.data_dir(home)
    remote = (args.remote or "").strip()
    if args.store:
        store_path = str(Path(args.store).expanduser())
    elif remote:
        store_path = str(data / "store")
    else:
        store_path = str(Path.home() / ".hermes-sync-store")
    try:
        result = engine.init(
            home,
            store_path,
            remote=remote,
            name=args.name,
            sync_secrets=bool(getattr(args, "sync_secrets", False)),
            include_cron=bool(args.cron),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the person, not raised
        return _fail(exc)

    if _json(args):
        _dump(result)
        return 0
    _print(f"Herd is set up on {result['device']['name']}.")
    _print(f"  store   {result['store']}" + (f"  (git: {result['remote']})" if result["remote"] else ""))
    _print(f"  pushed  {len(result['pushed'])} item(s): {', '.join(result['pushed']) or '—'}")
    if not result.get("remote"):
        _print()
        _print("  This is a plain folder. Put it in Dropbox/iCloud/Syncthing, or")
        _print("  point a git remote at it later with `hermes sync remote <url>`.")
    _code_block(result["code"])
    return 0


def cmd_join(args) -> int:
    home = hermes_home()
    try:
        result = engine.join(home, args.store, args.code, name=args.name,
                             sync_secrets=bool(getattr(args, "sync_secrets", False)))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    pulled = result["pulled"]
    _print(f"Joined the herd as {result['device']['name']}.")
    _print(f"  pulled  {len(pulled['applied'])} item(s): {', '.join(pulled['applied']) or '—'}")
    kept = [c for c in pulled.get("conflicts") or [] if c.get("kept") == "local"]
    adopted = [c for c in pulled.get("conflicts") or [] if c.get("kept") == "remote"]
    if kept:
        _print(f"  kept    {len(kept)} local value(s): {', '.join(c['path'] for c in kept)}")
    if adopted:
        _print(f"  adopted {len(adopted)} value(s) from the store: {', '.join(c['path'] for c in adopted)}")
    _print(f"  store   {result['store']}")
    return 0


def cmd_gc(args) -> int:
    try:
        result = engine.gc(hermes_home(), keep_days=args.keep_days, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    verb = "Would remove" if result["dry_run"] else "Removed"
    _print(f"{verb} {result['objects_removed']} unused object(s), "
           f"{result['bytes_freed'] // 1024} KB freed; {result['objects_kept']} still referenced.")
    if result["folders_removed"]:
        _print(f"  {result['folders_removed']} backup or conflict folder(s) older than "
               f"{result['keep_days']} days")
    return 0


def cmd_secrets(args) -> int:
    home = hermes_home()
    on = args.state == "on"
    try:
        result = engine.set_secrets(home, on)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    if on:
        _print("API keys will be encrypted and synced from now on.")
        _print("`hermes sync push` sends this machine's keys; `pull` takes the other machines'.")
    else:
        _print("API keys stay on this machine. Nothing reads .env while this is off.")
    return 0


def cmd_status(args) -> int:
    home = hermes_home()
    try:
        state = engine.status(home)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(state)
        return 0

    device = state["device"]
    _print(f"Herd · {device.get('name')} ({device.get('platform')})")
    _print(f"store    {state['store']}")
    if state.get("remote"):
        _print(f"remote   {state['remote']}")
    _print(f"last     {state['last_sync_human']}")
    _print(f"secrets  {'encrypted and synced' if state['secrets'] else 'off (hermes sync secrets on)'}")
    if state.get("conflicts"):
        _print(f"kept     {state['conflicts']} value(s) where both sides differed — `hermes sync conflicts`")
    _print()
    if state["items"]:
        width = max(len(r["item"]) for r in state["items"])
        for row in state["items"]:
            _print(f"  {row['item']:<{width}}  {row['state']}")
    else:
        _print("  nothing to sync yet")
    if len(state["devices"]) > 1:
        _print()
        _print("devices")
        for d in state["devices"]:
            mark = "  ← this one" if d["this_device"] else ""
            _print(f"  {d['name']} ({d['platform']}) · {human_age(d.get('last_push') or 0)}{mark}")
    return 0


def cmd_diff(args) -> int:
    try:
        result = engine.diff(hermes_home())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    if not result["would_push"] and not result["would_pull"]:
        _print("Nothing to do — every item matches the store.")
        return 0
    for item in result["would_push"]:
        _print(f"  ↑ {item}")
    for item in result["would_pull"]:
        _print(f"  ↓ {item}")
    return 0


def cmd_push(args) -> int:
    try:
        ctx = engine.open_context(hermes_home())
        result = engine.push(ctx)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    if not result["pushed"] and not result["removed"]:
        _print("Already up to date — nothing to push.")
        return 0
    _print(f"Pushed {len(result['pushed'])} item(s)" + (f", removed {len(result['removed'])}" if result["removed"] else ""))
    for item in result["pushed"]:
        _print(f"  ↑ {item}")
    for item in result["removed"]:
        _print(f"  ✕ {item}")
    transport = result.get("transport") or {}
    if transport.get("detail"):
        _print(f"  {transport['detail']}")
    return 0


def cmd_pull(args) -> int:
    try:
        ctx = engine.open_context(hermes_home())
        result = engine.pull(ctx, prefer="local")
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    if not result["applied"] and not result["removed"]:
        _print("Already up to date — nothing to pull.")
        return 0
    _print(f"Pulled {len(result['applied'])} item(s)" + (f", removed {len(result['removed'])}" if result["removed"] else ""))
    for item in result["applied"]:
        _print(f"  ↓ {item}")
    if result["conflicts"]:
        kept = sum(1 for c in result["conflicts"] if c.get("kept") == "local")
        _print(f"  {kept} local value(s) kept over the store's; `hermes sync conflicts` to review")
    if result.get("backup"):
        _print(f"  backup {result['backup']}")
    return 0


def cmd_sync(args) -> int:
    try:
        result = engine.sync(hermes_home())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    first, second = result["first"], result["second"]
    changed = len(first.get("pushed", first.get("applied", []))) + len(
        second.get("applied", second.get("pushed", []))
    )
    _print(f"Synced ({result['order']}) — {changed} item change(s).")
    if second.get("conflicts"):
        _print(f"  {len(second['conflicts'])} conflict(s) kept locally; `hermes sync conflicts`")
    return 0


def cmd_conflicts(args) -> int:
    rows = engine.conflicts(hermes_home())
    if _json(args):
        _dump(rows)
        return 0
    if not rows:
        _print("No conflicts recorded.")
        return 0
    for row in rows:
        _print(f"{row.get('item','?')} · {row.get('path','?')}")
        if row.get("kept") == "remote":
            _print(f"  took    {json.dumps(row.get('remote'))[:160]}  (store)")
            _print(f"  over    {json.dumps(row.get('local'))[:160]}  (this machine)")
        else:
            _print(f"  kept    {json.dumps(row.get('local'))[:160]}  (this machine)")
            _print(f"  ignored {json.dumps(row.get('remote'))[:160]}  (store)")
    return 0


def cmd_undo(args) -> int:
    try:
        result = engine.undo(hermes_home())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    _print(f"Restored {len(result['files'])} file(s) from {result['restored_from']}")
    return 0


def cmd_code(args) -> int:
    try:
        ctx = engine.open_context(hermes_home())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump({"code": ctx.identity.get("code", ""), "device": ctx.device})
        return 0
    _print(f"Device: {ctx.device.get('name')}")
    _print(f"Store:  {ctx.store.root}")
    _code_block(ctx.identity.get("code", ""))
    return 0


def cmd_policy(args) -> int:
    home = hermes_home()
    policy = Policy.load(engine.data_dir(home) / "policy.yaml")
    if _json(args):
        _dump(policy.to_dict())
        return 0
    _print("Stays on this machine (config keys):")
    for pattern in DEFAULT_LOCAL_ONLY:
        _print(f"  {pattern}")
    if policy.shared:
        _print("\nFollows you anyway (shared):")
        for pattern in policy.shared:
            _print(f"  {pattern}")
    _print("\nStays on this machine (.env keys):")
    for pattern in DEFAULT_SECRET_SKIP:
        _print(f"  {pattern}")
    _print(f"\nsecrets synced: {'yes' if policy.sync_secrets else 'no'}")
    _print(f"auto pull: {policy.auto_pull} · auto push: {policy.auto_push}")
    return 0


def cmd_leave(args) -> int:
    try:
        result = engine.leave(hermes_home())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)
    if _json(args):
        _dump(result)
        return 0
    _print(f"Stopped syncing. Local files are untouched; the store at {result['store']} is unchanged.")
    return 0


# ── parser ───────────────────────────────────────────────────────────────────
def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="sync_command")

    p = subs.add_parser("init", help="Start a herd: create a store and publish this machine")
    p.add_argument("--store", help="Folder to use as the store (default: ~/.hermes-sync-store)")
    p.add_argument("--remote", help="Git remote to push the store to (creates the local clone)")
    p.add_argument("--name", help="Name for this device (default: hostname)")
    p.add_argument("--sync-secrets", action="store_true",
                   help="Include API keys (off by default; `hermes sync secrets on` later)")
    p.add_argument("--no-secrets", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--cron", action="store_true", help="Also sync cron jobs (off by default)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_init)

    p = subs.add_parser("join", help="Join an existing herd on this machine")
    p.add_argument("store", help="Folder, or a git URL to clone")
    p.add_argument("--code", required=True, help="Recovery code from `hermes sync code`")
    p.add_argument("--sync-secrets", action="store_true",
                   help="Also take API keys (off by default; `hermes sync secrets on` later)")
    p.add_argument("--name", help="Name for this device (default: hostname)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_join)

    for name, func, help_text in (
        ("status", cmd_status, "Show what is synced, and what differs"),
        ("diff", cmd_diff, "Show what a sync would do"),
        ("push", cmd_push, "Send this machine's changes to the store"),
        ("pull", cmd_pull, "Take the store's changes onto this machine"),
        ("sync", cmd_sync, "Pull and push in the right order"),
    ):
        p = subs.add_parser(name, help=help_text)
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=func)

    p = subs.add_parser("gc", help="Drop store objects no device references any more")
    p.add_argument("--keep-days", type=int, default=30,
                   help="Leave anything younger than this alone (default: 30)")
    p.add_argument("--dry-run", action="store_true", help="Report without deleting")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gc)

    p = subs.add_parser("secrets", help="Include or exclude API keys from syncing")
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_secrets)

    p = subs.add_parser("conflicts", help="Show values kept over the store's")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_conflicts)

    p = subs.add_parser("undo", help="Restore files from the last pull's backup")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_undo)

    p = subs.add_parser("code", help="Print this herd's recovery code")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_code)

    p = subs.add_parser("policy", help="Print exactly what does and does not sync")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_policy)

    p = subs.add_parser("leave", help="Stop syncing on this machine")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_leave)

    subparser.set_defaults(sync_command=None)


_HANDLERS = {
    "init": cmd_init,
    "join": cmd_join,
    "status": cmd_status,
    "diff": cmd_diff,
    "push": cmd_push,
    "pull": cmd_pull,
    "sync": cmd_sync,
    "conflicts": cmd_conflicts,
    "undo": cmd_undo,
    "code": cmd_code,
    "policy": cmd_policy,
    "leave": cmd_leave,
}


def sync_command(args) -> int:
    # Dispatch on the subcommand name, not on args.func: the host wires the
    # top-level handler itself, so args.func is this function.
    name = str(getattr(args, "sync_command", "") or "")
    # Bare `hermes sync` is the verb, not a status read: that is what the name
    # promises and what someone types when they want their machines to agree.
    return _HANDLERS.get(name, cmd_sync)(args)
