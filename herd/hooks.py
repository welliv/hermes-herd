"""Session hooks. A short background thread, and nothing when nobody is there.

The thread exists so a session start or end is not blocked on the store. It is
not a daemon: it does one pull or one push and exits, and it will not start
more often than once every two minutes. Cron and other non-interactive sessions
do not start it.
"""

from __future__ import annotations

import logging
import threading

from . import engine, guard
from .policy import Policy
from .util import hermes_home, now

logger = logging.getLogger(__name__)

_AUTO_MIN_GAP_SECONDS = 120


def _auto(kind: str, **kwargs) -> None:
    if guard.unattended(kwargs):
        logger.debug("herd auto-%s skipped: unattended session", kind)
        return
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
            # The env flags are process-global. The cron context var is not,
            # which is why the check above happens on the hook's own thread.
            if guard.unattended(kwargs):
                return
            ctx = engine.open_context(home)
            if kind == "pull":
                engine.pull(ctx)
            else:
                engine.push(ctx)
        except Exception as exc:  # noqa: BLE001 - background, nothing to report to
            logger.debug("herd auto-%s skipped: %s", kind, exc)

    threading.Thread(target=run, name=f"herd-auto-{kind}", daemon=True).start()


def on_session_start(**kwargs) -> None:
    _auto("pull", **kwargs)


def on_session_end(**kwargs) -> None:
    _auto("push", **kwargs)


def pre_tool_call(tool_name=None, args=None, **kwargs):
    return guard.pre_tool_call(tool_name=tool_name, args=args, **kwargs)
