"""herd — keep one Hermes across every machine.

Settings, skills and memory follow you between devices. API keys do not. The
merge is per key, so a laptop keeps its Docker path while the desktop keeps its
port; the store only ever holds ciphertext; and every sync leaves a restorable
backup.
"""

from __future__ import annotations

import logging

try:  # loaded by Hermes as a package
    from .herd import tools
    from .herd.cli import register_cli, sync_command
    from .herd.hooks import on_session_end, on_session_start, pre_tool_call
except ImportError:  # imported as a top-level module (pytest collection, ad-hoc)
    from herd import tools
    from herd.cli import register_cli, sync_command
    from herd.hooks import on_session_end, on_session_start, pre_tool_call

logger = logging.getLogger(__name__)

# The session hooks used to live in this module. The names stay so a caller
# that already has them (the cost check, an older install) still finds them.
_on_session_start = on_session_start
_on_session_end = on_session_end


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
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_cli_command(
        name="sync",
        help="Keep one Hermes across machines (settings, skills, memory)",
        setup_fn=register_cli,
        handler_fn=sync_command,
        description=(
            "Sync this Hermes with your other machines. Three commands are the product: "
            "`pair`, `sync`, `conflicts`. The rest are repair tools."
        ),
    )
    logger.info("herd plugin loaded")
