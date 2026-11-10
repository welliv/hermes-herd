"""Agent-facing tools. Three verbs, because an agent needs to look, move, and compare."""

from __future__ import annotations

import json

from . import engine, guard
from .util import hermes_home

STATUS_SCHEMA = {
    "name": "sync_status",
    "description": (
        "Show whether this Hermes is in sync across machines: which items differ, "
        "when it last synced, and which devices are in the herd. Read-only. "
        "A git store is fetched and not rebased or pushed."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

DIFF_SCHEMA = {
    "name": "sync_diff",
    "description": (
        "List what sync_now would push or pull, without changing anything. "
        "A change that exists only on another machine is a pull, not a push. "
        "Skills, memory and SOUL.md that would be pulled are listed in "
        "review_before_pull: they become instructions this agent follows. "
        "Read-only: a git store is fetched and not rebased or pushed."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

SYNC_SCHEMA = {
    "name": "sync_now",
    "description": (
        "Sync this Hermes with the other machines in the herd. Asks for approval "
        "before pulling or pushing, because that can overwrite config, skills, "
        "memory and SOUL.md from a paired machine. Refuses in cron and other "
        "non-interactive sessions. Does not read or write API keys."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["auto", "pull", "push"],
                "description": "auto (default) picks the safe order; pull or push forces one way.",
            }
        },
        "required": [],
    },
}


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _err(code: str, message: str, **extra) -> str:
    return json.dumps({"ok": False, "code": code, "message": message, **extra}, ensure_ascii=False)


def handle_status(args: dict, **_kw) -> str:
    try:
        state = engine.status(hermes_home())
    except engine.HerdError as exc:
        return _err("not_configured", str(exc))
    except Exception as exc:  # noqa: BLE001 - a tool must return, never raise
        return _err("status_failed", str(exc))
    return _ok(
        {
            "device": state["device"],
            "store": state["store"],
            "remote": state.get("remote"),
            "last_sync": state.get("last_sync"),
            "last_sync_human": state.get("last_sync_human"),
            "secrets_synced": state["secrets"],
            "counts": state["counts"],
            "differs": [
                r["item"] for r in state["items"]
                if r["state"] in ("local-ahead", "remote-ahead", "diverged", "not-pushed")
            ],
            "incoming_instructions": state.get("incoming_instructions") or [],
            "not_local": [r["item"] for r in state["items"] if r["state"] == "not-local"],
            "devices": [
                {"name": d["name"], "platform": d["platform"], "this_device": d["this_device"]}
                for d in state["devices"]
            ],
        }
    )


def handle_diff(args: dict, **_kw) -> str:
    try:
        return _ok(engine.diff(hermes_home()))
    except engine.HerdError as exc:
        return _err("not_configured", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _err("diff_failed", str(exc))


def handle_sync(args: dict, **kw) -> str:
    if guard.unattended(kw):
        return _err(
            "unattended",
            "sync_now was not run. Cron and other non-interactive sessions do not "
            "pull or overwrite config, skills, memory or SOUL.md.",
        )
    direction = (args or {}).get("direction") or "auto"
    try:
        if direction == "pull":
            ctx = engine.open_context(hermes_home())
            result = engine.pull(ctx)
            return _ok({"direction": "pull", **result})
        if direction == "push":
            ctx = engine.open_context(hermes_home())
            result = engine.push(ctx)
            return _ok({"direction": "push", **result})
        return _ok(engine.sync(hermes_home()))
    except engine.HerdError as exc:
        return _err("not_configured", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _err("sync_failed", str(exc))


TOOLS = {
    "sync_status": (STATUS_SCHEMA, handle_status, "🔄"),
    "sync_diff": (DIFF_SCHEMA, handle_diff, "🔍"),
    "sync_now": (SYNC_SCHEMA, handle_sync, "🔁"),
}
