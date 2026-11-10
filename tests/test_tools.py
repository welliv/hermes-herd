"""The agent-facing surface: three tools, their envelope, and their failure modes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from herd import engine, tools
from tests.test_engine import make_home


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_status_before_setup_explains_itself(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    out = _payload(tools.handle_status({}))
    assert out["ok"] is False
    assert out["code"] == "not_configured"
    assert "hermes sync pair" in out["message"]


def test_status_reports_the_herd(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    b = make_home(tmp_path, "b")
    engine.join(b, str(tmp_path / "store"), json.loads(
        (Path(a) / "plugin-data" / "herd" / "identity.json").read_text())["code"], name="laptop")
    monkeypatch.setenv("HERMES_HOME", str(b))
    out = _payload(tools.handle_status({}))
    assert out["ok"] is True
    assert out["device"]["name"] == "laptop"
    assert out["counts"]["differs"] == 0
    assert {d["name"] for d in out["devices"]} == {"desktop", "laptop"}


def test_diff_lists_what_a_sync_would_do(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: agate"))
    monkeypatch.setenv("HERMES_HOME", str(a))
    out = _payload(tools.handle_diff({}))
    assert out["ok"] is True
    assert "config" in out["would_push"]


def test_sync_now_runs_and_reports(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    b = make_home(tmp_path, "b")
    engine.join(b, str(tmp_path / "store"), json.loads(
        (Path(a) / "plugin-data" / "herd" / "identity.json").read_text())["code"], name="laptop")
    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: agate"))
    monkeypatch.setenv("HERMES_HOME", str(a))
    assert _payload(tools.handle_sync({}))["ok"] is True
    monkeypatch.setenv("HERMES_HOME", str(b))
    out = _payload(tools.handle_sync({"direction": "pull"}))
    assert out["ok"] is True and out["direction"] == "pull"
    assert "agate" in (b / "config.yaml").read_text()


def test_sync_now_push_only(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: mono"))
    monkeypatch.setenv("HERMES_HOME", str(a))
    out = _payload(tools.handle_sync({"direction": "push"}))
    assert out["ok"] is True and out["direction"] == "push"


def test_tools_return_json_instead_of_raising_when_the_store_vanishes(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    shutil.rmtree(tmp_path / "store")
    monkeypatch.setenv("HERMES_HOME", str(a))
    for handler in (tools.handle_status, tools.handle_diff, tools.handle_sync):
        out = _payload(handler({}))
        assert out["ok"] is False
        assert out["code"] in {"status_failed", "diff_failed", "sync_failed", "not_configured"}
        assert out["message"]
