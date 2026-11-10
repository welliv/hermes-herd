"""Catalog rules: no .env access, approval on writes, read tools do not push."""

from __future__ import annotations

import json
from pathlib import Path

from herd import engine, guard, hooks, store as store_mod, tools
from tests.test_engine import make_home


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_sync_never_opens_dotenv(tmp_path, monkeypatch):
    home = make_home(tmp_path, "desk")
    real = Path.read_text

    def guarded(self, *args, **kwargs):
        if self.name == ".env":
            raise AssertionError("opened .env")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    engine.init(home, str(tmp_path / "store"), name="desk", sync_secrets=True)
    engine.set_secrets(home, True)
    ctx = engine.open_context(home)
    engine.push(ctx)
    engine.pull(ctx)
    engine.status(home)
    engine.diff(home)


def test_sync_now_asks_for_approval_and_reads_do_not():
    approved = guard.pre_tool_call("sync_now", {"direction": "pull"})
    assert approved["action"] == "approve"
    assert approved["rule_key"] == "herd:sync_now:pull"
    assert "SOUL.md" in approved["message"]
    assert guard.pre_tool_call("sync_status", {}) is None
    assert guard.pre_tool_call("sync_diff", {}) is None


def test_cron_blocks_sync_now_and_skips_the_session_hook(tmp_path, monkeypatch):
    home = make_home(tmp_path, "desk")
    engine.init(home, str(tmp_path / "store"), name="desk")
    (home / "config.yaml").write_text(home.joinpath("config.yaml").read_text().replace("skin: default", "skin: agate"))
    before = (home / "config.yaml").read_text()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")

    blocked = guard.pre_tool_call("sync_now", {"direction": "push"})
    assert blocked["action"] == "block"
    out = _payload(tools.handle_sync({"direction": "push"}))
    assert out["ok"] is False and out["code"] == "unattended"
    assert (home / "config.yaml").read_text() == before

    monkeypatch.setattr(engine, "open_context", lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
    hooks.on_session_start(platform="cron")
    hooks.on_session_end()


def test_single_query_is_unattended(monkeypatch):
    monkeypatch.setenv("HERMES_SINGLE_QUERY_SESSION", "1")
    assert guard.unattended() is True
    assert guard.pre_tool_call("sync_now", {})["action"] == "block"


def test_status_and_diff_fetch_without_rebase_or_push(tmp_path, monkeypatch):
    home = make_home(tmp_path, "desk")
    engine.init(home, str(tmp_path / "store"), name="desk")
    flags = []

    def spy(self, fetch_only=False):
        flags.append(fetch_only)

    monkeypatch.setattr(store_mod.Store, "refresh", spy)
    engine.status(home)
    engine.diff(home)
    assert flags == [True, True]
    engine.pull(engine.open_context(home))
    assert flags[-1] is False


def test_clone_separates_the_remote_from_options(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return store_mod.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(store_mod.subprocess, "run", fake_run)
    try:
        store_mod.clone("--upload-pack=touch", tmp_path / "dest")
    except Exception:
        pass
    clone = next(c for c in calls if c[:2] == ["git", "clone"])
    assert clone[:4] == ["git", "clone", "--quiet", "--"]
    assert clone[4] == "--upload-pack=touch"
