"""Approval and unattended-session gates for writes.

``sync_status`` and ``sync_diff`` only read. ``sync_now``, and the session
hooks that pull or push, are the writes. Those ask Hermes for a human approval
when a person can answer, and they skip without touching the profile when the
session is cron or otherwise non-interactive. Skipping is the closed failure:
cron can be configured to auto-approve, and a prompt there has nobody to answer.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}
_UNATTENDED_PLATFORMS = {"cron", "scheduler"}
_UNATTENDED_SOURCES = {"cron", "scheduler", "single_query", "noninteractive", "unattended"}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def cron_execution_active(ctx=None) -> bool:
    """True when Hermes says this turn is a cron run.

    The env var is set for external cron workers. The context var covers an
    in-process scheduler. Either one is enough. A missing Hermes install is
    not a cron run.
    """
    if _flag("HERMES_CRON_SESSION"):
        return True
    if ctx is not None:
        ask = getattr(ctx, "current_cron_execution", None)
        if callable(ask):
            try:
                if ask() is not None:
                    return True
            except Exception:
                return True
    try:
        from cron.execution_identity import current_cron_execution
    except Exception:
        return False
    try:
        return current_cron_execution() is not None
    except Exception:
        return True


def unattended(kwargs: dict | None = None, ctx=None) -> bool:
    """True when no person is there to approve a pull or a push.

    Interactive CLI, TUI, Desktop and messaging sessions are not unattended:
    Hermes's own approval gate can reach a person, and it fails closed when it
    cannot. Cron, ``hermes -q``, and an explicit ``HERD_UNATTENDED`` are.
    """
    kwargs = kwargs or {}
    if _flag("HERMES_CRON_SESSION") or _flag("HERMES_SINGLE_QUERY_SESSION") or _flag("HERD_UNATTENDED"):
        return True
    platform = str(kwargs.get("platform") or "").strip().lower()
    if platform in _UNATTENDED_PLATFORMS:
        return True
    source = str(kwargs.get("source") or kwargs.get("session_source") or "").strip().lower()
    if source in _UNATTENDED_SOURCES:
        return True
    if kwargs.get("interactive") is False:
        return True
    return cron_execution_active(ctx)


def pre_tool_call(tool_name=None, args=None, ctx=None, **kwargs):
    """Hermes ``pre_tool_call`` directive for Herd's own tools.

    Read tools are untouched. ``sync_now`` escalates to the human gate, or
    blocks immediately when the session cannot answer.
    """
    if tool_name != "sync_now":
        return None
    if unattended(kwargs, ctx=ctx):
        return {
            "action": "block",
            "message": (
                "sync_now was not run. This session is cron or otherwise non-interactive, "
                "so Herd will not pull or overwrite config, skills, memory or SOUL.md."
            ),
        }
    direction = "auto"
    if isinstance(args, dict) and args.get("direction"):
        direction = str(args.get("direction"))
    if direction not in {"auto", "pull", "push"}:
        direction = "auto"
    return {
        "action": "approve",
        "message": (
            "Herd will sync this machine with the others in the herd "
            f"({direction}). That can overwrite config, skills, memory and SOUL.md "
            "with copies from a paired device. Those files are instructions the agent "
            "loads. Approve only if you trust that device."
        ),
        "rule_key": f"herd:sync_now:{direction}",
    }
