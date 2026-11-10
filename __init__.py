"""herd — keep one Hermes across every machine.

Settings, skills, memory and API keys follow you between devices. The merge is
per key, so a laptop keeps its Docker path while the desktop keeps its port; the
store only ever holds ciphertext; and every sync leaves a restorable backup.
"""

from __future__ import annotations

import logging
import threading
import time

try:  # loaded by Hermes as a package
    from .herd import engine, tools
    from .herd.cli import register_cli, sync_command
    from .herd.policy import Policy
    from .herd.util import hermes_home, now
except ImportError:  # imported as a top-level module (pytest collection, ad-hoc)
    from herd import engine, tools
    from herd.cli import register_cli, sync_command
    from herd.policy import Policy
    from herd.util import hermes_home, now

logger = logging.getLogger(__name__)

# A session start/end hook must never block the turn it runs in, and must never
# raise into the gateway. Both hooks therefore hand the work to a daemon thread.
_AUTO_MIN_GAP_SECONDS = 120


def _auto(kind: str) -> None:
    try:
        home = hermes_home()
        data = engine.data_dir(home)
        policy = Policy.load(data / "policy.yaml")
        if kind == "pull" and not policy.auto_pull:
            return
        if kind == "push" and not policy.auto_push:
            return
        state = engine.load_state(data)
        last = state.get(f"last_{kind}") or 0
        if now() - last < _AUTO_MIN_GAP_SECONDS:
            return
    except Exception:
        return

    def run() -> None:
        try:
            ctx = engine.open_context(home)
            if kind == "pull":
                engine.pull(ctx)
            else:
                engine.push(ctx)
        except Exception as exc:  # noqa: BLE001 - background, nothing to report to
            logger.debug("herd auto-%s skipped: %s", kind, exc)

    threading.Thread(target=run, name=f"herd-auto-{kind}", daemon=True).start()


def _on_session_start(**_kwargs) -> None:
    _auto("pull")


def _on_session_end(**_kwargs) -> None:
    _auto("push")


def register(ctx) -> None:
    """Register tools, hooks and the `hermes sync` command."""
    for name, (schema, handler, emoji) in tools.TOOLS.items():
        ctx.register_tool(
            name=name,
            toolset="herd",
            schema=schema,
            handler=lambda args, _h=handler, **kw: _h(args, **kw),
            emoji=emoji,
        )
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_cli_command(
        name="sync",
        help="Keep one Hermes across machines (settings, skills, memory, keys)",
        setup_fn=register_cli,
        handler_fn=sync_command,
        description=(
            "Sync this Hermes with your other machines: per-key config merge, encrypted "
            "secrets, restorable backups. Start with `hermes sync pair`."
        ),
    )
    logger.info("herd plugin loaded")
