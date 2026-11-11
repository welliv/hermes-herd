"""1.2.1: a peer cannot point this machine's credentials somewhere else.

Credentials stay local, but the URL, provider or command they are used with
syncs like any other setting. Without a pin, a peer could change
``model.base_url`` and the next request would carry this machine's
``model.api_key`` to the peer's endpoint. Each test that names a redirect
fails on 3bdbe13.
"""

from __future__ import annotations

from herd import engine, yamlutil
from tests.test_engine import make_home
from tests.test_review_1_2_1 import CRON, SECRET_CONFIG, _poisoned_peer_push

SECRETS = ("sk-model-LEAK", "sk-list-LEAK", "ghp-env-LEAK", "hdr-LEAK", "tok-LEAK", "sk-deep-LEAK")


def _cfg(home):
    return yamlutil.safe_load((home / "config.yaml").read_text())


def _edit(home, fn):
    conf = _cfg(home)
    fn(conf)
    (home / "config.yaml").write_text(yamlutil.safe_dump(conf))


def _setup(tmp_path):
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    return a, b


def _reasons(home):
    return {(c["path"], c.get("reason")) for c in engine.conflicts(home)}


def test_shape_changes_do_not_drop_local_credentials(tmp_path):
    a, b = _setup(tmp_path)
    p = yamlutil.safe_load(SECRET_CONFIG)
    p["model"] = "just-a-string"
    p["custom_providers"] = {"x": 1}
    p["mcp_servers"] = None
    p["tools"] = []
    _poisoned_peer_push(b, tmp_path / "store", p)
    engine.pull(engine.open_context(a))
    text = (a / "config.yaml").read_text()
    for value in SECRETS:
        assert value in text


def test_prefer_remote_pull_does_not_import_a_peer_key(tmp_path):
    a, b = _setup(tmp_path)
    p = yamlutil.safe_load(SECRET_CONFIG)
    p["model"]["api_key"] = "EVIL"
    p["model"]["default"] = "z"
    (a / "config.yaml").write_text(SECRET_CONFIG.replace("deepseek-v4-flash", "local-edit"))
    _poisoned_peer_push(b, tmp_path / "store", p)
    engine.pull(engine.open_context(a), prefer="remote")
    text = (a / "config.yaml").read_text()
    assert "EVIL" not in text and "sk-model-LEAK" in text


def test_local_state_and_store_hold_no_secret(tmp_path):
    a, b = _setup(tmp_path)
    engine.sync(a)
    engine.sync(b)
    for f in engine.data_dir(a).rglob("*.json"):
        assert "LEAK" not in f.read_text(errors="ignore"), f
    for f in (tmp_path / "store").rglob("*"):
        if f.is_file():
            assert b"LEAK" not in f.read_bytes(), f


def test_peer_cannot_redirect_local_key_via_base_url(tmp_path):
    """Fails on 3bdbe13: the peer's base_url was merged beside the local key."""
    a, b = _setup(tmp_path)
    p = yamlutil.safe_load(SECRET_CONFIG)
    p["model"]["base_url"] = "https://attacker.example/v1"
    p["custom_providers"][0]["base_url"] = "https://attacker.example/lab"
    _poisoned_peer_push(b, tmp_path / "store", p)
    engine.pull(engine.open_context(a))
    live = _cfg(a)
    assert live["model"]["base_url"] == "https://api.example.com/v1"
    assert live["model"]["api_key"] == "sk-model-LEAK"
    assert live["custom_providers"][0]["base_url"] == "http://lab.local/v1"
    assert "attacker" not in (a / "config.yaml").read_text()
    assert ("model.base_url", "credential-endpoint") in _reasons(a)


def test_peer_cannot_hand_local_mcp_env_to_a_new_command(tmp_path):
    """Fails on 3bdbe13: the local env went to the peer's command."""
    a, b = _setup(tmp_path)
    p = yamlutil.safe_load(SECRET_CONFIG)
    p["mcp_servers"]["github"]["command"] = "sh"
    p["mcp_servers"]["github"]["args"] = ["-c", "curl evil"]
    _poisoned_peer_push(b, tmp_path / "store", p)
    engine.pull(engine.open_context(a))
    server = _cfg(a)["mcp_servers"]["github"]
    assert server["command"] == "npx" and server["args"] == ["server-github"]


def test_peer_cannot_add_an_endpoint_or_switch_provider_beside_a_key(tmp_path):
    a = make_home(tmp_path, "a", config="model:\n  provider: deepseek\n  api_key: sk-model-LEAK\n")
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    _edit(b, lambda c: c["model"].update(base_url="https://attacker.example/v1", provider="custom"))
    engine.sync(b)
    engine.sync(a)
    model = _cfg(a)["model"]
    assert model["provider"] == "deepseek" and model["api_key"] == "sk-model-LEAK"
    assert "base_url" not in model


def test_a_header_credential_pins_its_endpoint(tmp_path):
    conf = ("auxiliary:\n  vision:\n    base_url: https://vision.example/v1\n"
            "    extra_headers:\n      Authorization: Bearer hdr-LEAK\n      X-Trace: on\n")
    a = make_home(tmp_path, "a", config=conf)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    _edit(b, lambda c: c["auxiliary"]["vision"].__setitem__("base_url", "https://attacker.example/v1"))
    engine.sync(b)
    engine.sync(a)
    vision = _cfg(a)["auxiliary"]["vision"]
    assert vision["base_url"] == "https://vision.example/v1"
    assert vision["extra_headers"]["Authorization"] == "Bearer hdr-LEAK"
    assert "Authorization" not in (_cfg(b)["auxiliary"]["vision"].get("extra_headers") or {})


def test_endpoint_without_local_credential_still_syncs(tmp_path):
    a, b = _setup(tmp_path)
    p = yamlutil.safe_load(SECRET_CONFIG)
    p["display"]["url"] = "https://new"
    _poisoned_peer_push(b, tmp_path / "store", p)
    engine.pull(engine.open_context(a))
    assert _cfg(a)["display"]["url"] == "https://new"


def test_endpoints_follow_onto_a_machine_without_the_key(tmp_path):
    a, b = _setup(tmp_path)
    _edit(a, lambda c: c["model"].__setitem__("base_url", "https://moved.example/v1"))
    engine.sync(a)
    engine.sync(b)
    assert _cfg(b)["model"]["base_url"] == "https://moved.example/v1"
    assert "api_key" not in _cfg(b)["model"]
    assert not engine.conflicts(b)


def test_normal_edits_beside_a_key_raise_no_conflict(tmp_path):
    a, b = _setup(tmp_path)
    _edit(b, lambda c: c["model"].__setitem__("default", "other-model"))
    _edit(b, lambda c: c["custom_providers"][0].__setitem__("models", ["a", "b", "c"]))
    _edit(b, lambda c: c["display"].__setitem__("skin", "mono"))
    for _ in range(2):
        engine.sync(b)
        engine.sync(a)
    live = _cfg(a)
    assert live["model"]["default"] == "other-model"
    assert live["custom_providers"][0]["models"] == ["a", "b", "c"]
    assert live["display"]["skin"] == "mono"
    assert not engine.conflicts(a) and not engine.conflicts(b)


def test_held_endpoint_is_shown_does_not_ping_pong_and_take_theirs_applies_it(tmp_path):
    a, b = _setup(tmp_path)
    _edit(b, lambda c: c["model"].__setitem__("base_url", "https://other.example/v1"))
    _edit(b, lambda c: c["display"].__setitem__("skin", "mono"))
    for _ in range(4):
        engine.sync(b)
        engine.sync(a)
    assert _cfg(a)["model"]["base_url"] == "https://api.example.com/v1"
    assert _cfg(a)["display"]["skin"] == "mono"            # the rest still follows
    assert _cfg(b)["model"]["base_url"] == "https://other.example/v1"   # b's edit is not reverted
    assert ("model.base_url", "credential-endpoint") in _reasons(a)
    engine.resolve(a, "config", "theirs")
    for _ in range(2):
        engine.sync(a)
        engine.sync(b)
    assert _cfg(a)["model"]["base_url"] == "https://other.example/v1"
    assert _cfg(a)["model"]["api_key"] == "sk-model-LEAK"
    assert not engine.conflicts(a)


def test_held_list_endpoint_is_shown_and_take_theirs_applies_it(tmp_path):
    a, b = _setup(tmp_path)
    _edit(b, lambda c: c["custom_providers"][0].__setitem__("base_url", "https://other.example/lab"))
    for _ in range(3):
        engine.sync(b)
        engine.sync(a)
    assert _cfg(a)["custom_providers"][0]["base_url"] == "http://lab.local/v1"
    assert ("custom_providers", "credential-endpoint") in _reasons(a)
    engine.resolve(a, "config", "theirs")
    entry = _cfg(a)["custom_providers"][0]
    assert entry["base_url"] == "https://other.example/lab" and entry["api_key"] == "sk-list-LEAK"


def test_pair_cron_on_the_first_machine_opts_it_in(tmp_path):
    """Fails on 3bdbe13: `pair --cron` without --code was accepted and ignored."""
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    started = engine.pair_start(a, str(tmp_path / "store"), name="desk", include_cron=True)
    assert engine.load_state(engine.data_dir(a))["sync_cron"] is True
    b = make_home(tmp_path, "b")
    engine.pair_finish(b, started["code"], str(tmp_path / "store"), name="laptop", include_cron=True)
    assert (b / "cron" / "jobs.json").read_text() == CRON


def test_pair_cron_on_a_machine_that_already_syncs_turns_it_on(tmp_path):
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    engine.init(a, str(tmp_path / "store"), name="desk")
    assert engine.load_state(engine.data_dir(a)).get("sync_cron") is False
    started = engine.pair_start(a, str(tmp_path / "store"), name="desk", include_cron=True)
    assert engine.load_state(engine.data_dir(a))["sync_cron"] is True
    b = make_home(tmp_path, "b")
    engine.pair_finish(b, started["code"], str(tmp_path / "store"), name="laptop", include_cron=True)
    assert (b / "cron" / "jobs.json").read_text() == CRON
    # And plain `pair` never turns it off.
    engine.pair_start(a, str(tmp_path / "store"), name="desk")
    assert engine.load_state(engine.data_dir(a))["sync_cron"] is True


def test_cli_pair_passes_cron_to_the_first_machine(tmp_path, monkeypatch):
    import argparse
    from herd import cli
    seen = {}
    monkeypatch.setattr(engine, "pair_start", lambda *a, **k: seen.update(k) or {"code": "x"})
    monkeypatch.setattr(cli, "hermes_home", lambda: tmp_path)
    args = argparse.Namespace(code="", cron=True, store=None, remote="", name=None, knowledge=False,
                              sync_secrets=False, json=True)
    cli.cmd_pair(args)
    assert seen.get("include_cron") is True
