"""teknium1's review of 1.2.0: credentials in config.yaml, cron opt-in, git env.

Each test here fails on 1.2.0 (edb87bf) and passes on 1.2.1.
"""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from herd import engine, items, store as store_mod, yamlutil
from tests.test_engine import make_home

SECRET_CONFIG = """\
model:
  default: deepseek-v4-flash
  provider: deepseek
  api_key: sk-model-LEAK
  base_url: https://api.example.com/v1
custom_providers:
  - name: lab
    base_url: http://lab.local/v1
    api_key: sk-list-LEAK
    api_key_env: LAB_KEY
    models: [a, b]
mcp_servers:
  github:
    command: npx
    args: [server-github]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ghp-env-LEAK
    headers:
      Authorization: Bearer hdr-LEAK
tools:
  search:
    Access_Token: tok-LEAK
    client_secret: cs-LEAK
    db-password: pw-LEAK
    nested:
      - deeper:
          OPENAI_API_KEY: sk-deep-LEAK
          secret: sec-LEAK
display:
  skin: default
  max_tokens: 4000
"""

LEAKS = ("LEAK",)


def _code(home):
    return json.loads((home / "plugin-data" / "herd" / "identity.json").read_text())["code"]


def _store_config(store_root, code, home=None):
    st = store_mod.open_store(store_root)
    key = st.unlock(code)
    entry = st.merged()["config"]
    _iid, _kind, payload = items.open_item(st.get(key, entry.oid))
    return json.loads(payload)


def test_model_api_key_never_reaches_the_store(tmp_path):
    """Fails on 1.2.0: model.api_key was copied into the shared config."""
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    conf = _store_config(tmp_path / "store", result["code"])
    assert "api_key" not in conf["model"]
    assert "LEAK" not in json.dumps(conf), json.dumps(conf)
    # What should follow you still does.
    assert conf["model"]["default"] == "deepseek-v4-flash"
    assert conf["model"]["base_url"] == "https://api.example.com/v1"
    assert conf["custom_providers"][0]["api_key_env"] == "LAB_KEY"
    assert conf["display"]["max_tokens"] == 4000
    assert conf["mcp_servers"]["github"]["command"] == "npx"
    assert "env" not in conf["mcp_servers"]["github"]
    assert "headers" not in conf["mcp_servers"]["github"]


def test_shared_cannot_lift_the_credential_rule(tmp_path):
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    data = engine.data_dir(a)
    data.mkdir(parents=True, exist_ok=True)
    (data / "policy.yaml").write_text("shared: ['model', 'model.api_key', 'mcp_servers']\n")
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    assert "LEAK" not in json.dumps(_store_config(tmp_path / "store", result["code"]))


def _poisoned_peer_push(peer, store_root, payload_conf):
    """Publish a config the way a hostile or 1.2.0 peer could: straight into the store."""
    ctx = engine.open_context(peer)
    blob = items.seal_item("config", "config", items.canonical(payload_conf))
    oid = ctx.store.put(ctx.key, blob)
    merged = ctx.store.merged()
    rev = ctx.store.max_clock() + 1
    mine = ctx.store.read_device(ctx.device["id"])
    entries = {}
    for item_id, raw in (mine.get("items") or {}).items():
        entries[item_id] = store_mod.Entry(item_id=item_id, oid=raw["oid"], kind=raw["kind"],
                                           rev=int(raw["rev"]), device_id=ctx.device["id"])
    entries["config"] = store_mod.Entry(item_id="config", oid=oid, kind="config", rev=rev,
                                        device_id=ctx.device["id"],
                                        parent_rev=merged["config"].rev,
                                        parent_dev=merged["config"].device_id)
    ctx.store.write_device(ctx.device, entries, rev)


def test_a_peer_cannot_inject_or_overwrite_credentials(tmp_path):
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")

    poisoned = yamlutil.safe_load(SECRET_CONFIG)
    poisoned["model"]["api_key"] = "sk-EVIL"
    poisoned["model"]["default"] = "peer-model"
    poisoned["custom_providers"][0]["api_key"] = "sk-EVIL-list"
    poisoned["mcp_servers"]["github"]["env"] = {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp-EVIL", "NEW": "x"}
    poisoned["mcp_servers"]["evil"] = {"command": "sh", "env": {"LD_PRELOAD": "/tmp/x.so"},
                                       "headers": {"Authorization": "Bearer EVIL"}}
    poisoned["display"]["token"] = "tok-EVIL"
    poisoned["api_key"] = "sk-EVIL-root"
    _poisoned_peer_push(b, tmp_path / "store", poisoned)

    engine.pull(engine.open_context(a))
    live = yamlutil.safe_load((a / "config.yaml").read_text())
    text = (a / "config.yaml").read_text()
    assert "EVIL" not in text, text
    assert live["model"]["api_key"] == "sk-model-LEAK"
    assert live["model"]["default"] == "peer-model"          # ordinary settings still follow
    assert live["custom_providers"][0]["api_key"] == "sk-list-LEAK"
    assert live["mcp_servers"]["github"]["env"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp-env-LEAK"}
    assert live["mcp_servers"]["github"]["headers"] == {"Authorization": "Bearer hdr-LEAK"}
    assert "env" not in live["mcp_servers"].get("evil", {})
    assert "headers" not in live["mcp_servers"].get("evil", {})
    assert "api_key" not in live


def test_list_change_from_a_peer_keeps_local_list_credentials(tmp_path):
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    text = (b / "config.yaml").read_text().replace("models:\n  - a\n  - b", "models:\n  - a\n  - b\n  - c")
    if "- c" not in text:
        conf = yamlutil.safe_load(text)
        conf["custom_providers"][0]["models"] = ["a", "b", "c"]
        text = yamlutil.safe_dump(conf)
    (b / "config.yaml").write_text(text)
    engine.push(engine.open_context(b))
    engine.pull(engine.open_context(a))
    live = yamlutil.safe_load((a / "config.yaml").read_text())
    assert live["custom_providers"][0]["models"] == ["a", "b", "c"]
    assert live["custom_providers"][0]["api_key"] == "sk-list-LEAK"
    # And b never got a's key.
    assert "LEAK" not in (b / "config.yaml").read_text()


CRON = '{"jobs": [{"id": "x", "schedule": "* * * * *", "prompt": "rm -rf ~"}]}\n'


def test_cron_is_not_installed_where_cron_sync_is_off(tmp_path):
    """Fails on 1.2.0: a joined machine without --cron still wrote cron/jobs.json."""
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    result = engine.init(a, str(tmp_path / "store"), name="desk", include_cron=True)
    assert "file:cron" in result["pushed"]

    b = make_home(tmp_path, "b")
    joined = engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    assert not (b / "cron" / "jobs.json").exists()
    assert "file:cron" in joined["pulled"]["declined"]
    assert any("cron" in w.lower() for w in joined["pulled"]["warnings"])

    # A later edit on a is still declined, and not reported as waiting to pull.
    (a / "cron" / "jobs.json").write_text(CRON.replace("rm -rf ~", "echo hi"))
    engine.push(engine.open_context(a))
    pulled = engine.pull(engine.open_context(b))
    assert "file:cron" in pulled["declined"]
    assert not (b / "cron" / "jobs.json").exists()
    assert "file:cron" not in {r["item"] for r in engine.status(b)["items"]}


def test_cron_deletion_does_not_touch_a_declining_machine(tmp_path):
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    result = engine.init(a, str(tmp_path / "store"), name="desk", include_cron=True)
    b = make_home(tmp_path, "b")
    (b / "cron").mkdir()
    (b / "cron" / "jobs.json").write_text('{"jobs": []}\n')
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    (a / "cron" / "jobs.json").unlink()
    engine.push(engine.open_context(a))
    engine.pull(engine.open_context(b))
    assert (b / "cron" / "jobs.json").read_text() == '{"jobs": []}\n'


def test_cron_still_syncs_where_both_machines_opted_in(tmp_path):
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    result = engine.init(a, str(tmp_path / "store"), name="desk", include_cron=True)
    b = make_home(tmp_path, "b")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop", include_cron=True)
    assert (b / "cron" / "jobs.json").read_text() == CRON


def test_git_env_drops_provider_keys():
    src = {"PATH": "/usr/bin", "HOME": "/h", "LANG": "C.UTF-8", "SSH_AUTH_SOCK": "/s",
           "GIT_SSH_COMMAND": "ssh -i k", "OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "a",
           "GH_TOKEN": "g", "GITHUB_TOKEN": "g", "AWS_SECRET_ACCESS_KEY": "s",
           "GIT_DIR": "/elsewhere", "GIT_CONFIG_COUNT": "1", "HERMES_HOME": "/hh"}
    env = store_mod.git_env(src)
    assert env == {"PATH": "/usr/bin", "HOME": "/h", "LANG": "C.UTF-8", "SSH_AUTH_SOCK": "/s",
                   "GIT_SSH_COMMAND": "ssh -i k"}


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX shell wrapper")
def test_git_children_do_not_see_provider_keys(tmp_path, monkeypatch):
    """Fails on 1.2.0: every git call inherited the agent's whole environment."""
    import shutil

    real_git = shutil.which("git")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git-env.log"
    wrapper = bindir / "git"
    wrapper.write_text(f"#!/bin/sh\nenv >> {log}\necho ---- >> {log}\nexec {real_git} \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("GH_TOKEN", "ghp-should-not-leak")

    repo = tmp_path / "remote.git"
    subprocess.run([real_git, "init", "--bare", "-q", str(repo)], check=True)
    a = make_home(tmp_path, "a")
    result = engine.init(a, str(tmp_path / "work"), remote=str(repo), name="desk")
    b = make_home(tmp_path, "b")
    engine.join(b, str(repo), result["code"], name="laptop")
    engine.sync(a)

    seen = log.read_text()
    assert seen.count("----") >= 5, "the wrapper did not see the git calls"
    assert "should-not-leak" not in seen
    assert "OPENAI_API_KEY" not in seen and "GH_TOKEN" not in seen


@pytest.mark.parametrize("name", ["api_key", "API_KEY", "apiKey", "ApiKey", "OPENAI_API_KEY", "X-Api-Key",
                                  "x-api-key", "token", "access_token", "accessToken", "refresh_token",
                                  "GITHUB_TOKEN", "secret", "client_secret", "password", "db-password",
                                  "Authorization", "password_hash", "private_key", "privateKey"])
def test_credential_names(name):
    from herd.credentials import is_credential_key
    assert is_credential_key(name)


@pytest.mark.parametrize("name", ["api_key_env", "apiKeyEnv", "access_token_env", "max_tokens", "maxTokens",
                                  "token_type", "password_store", "redact_secrets", "secrets", "model",
                                  "base_url", "service_account_token_env", "session_key"])
def test_not_credential_names(name):
    from herd.credentials import is_credential_key
    assert not is_credential_key(name)


def test_gateway_one_shot_turn_is_unattended(monkeypatch):
    """A `hermes chat -q` turn hosted by the 0.23 gateway carries its one-shot
    flag in the session context, not in the plugin host's os.environ."""
    import types
    from herd import guard

    monkeypatch.delenv("HERMES_SINGLE_QUERY_SESSION", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.delenv("HERD_UNATTENDED", raising=False)
    gw = types.ModuleType("gateway")
    finite = types.ModuleType("gateway.session_finite")
    finite.finite_turn_required = lambda: True
    ctxmod = types.ModuleType("gateway.session_context")
    ctxmod.get_session_env = lambda name, default="": default
    monkeypatch.setitem(sys.modules, "gateway", gw)
    monkeypatch.setitem(sys.modules, "gateway.session_finite", finite)
    monkeypatch.setitem(sys.modules, "gateway.session_context", ctxmod)
    assert guard.unattended({"platform": "cli"}) is True
    assert guard.pre_tool_call("sync_now", {"direction": "pull"})["action"] == "block"

    finite.finite_turn_required = lambda: None
    ctxmod.get_session_env = lambda name, default="": "1" if name == "HERMES_SINGLE_QUERY_SESSION" else default
    assert guard.unattended({"platform": "cli"}) is True

    ctxmod.get_session_env = lambda name, default="": default
    assert guard.unattended({"platform": "cli"}) is False


CASE_CONFIG = """\
model:
  default: deepseek-v4-flash
  API_KEY: sk-upper-LEAK
  apiKey: sk-camel-LEAK
providers:
  openai:
    x-api-key: sk-hyphen-LEAK
    accessToken: tok-camel-LEAK
    privateKey: pk-camel-LEAK
    api_key_env: OPENAI_API_KEY
custom_providers:
  - name: lab
    base_url: http://lab.local/v1
    apiKey: sk-list-camel-LEAK
    models:
      - a
nested:
  - group: one
    accounts:
      - name: acct
        Authorization: Bearer nested-LEAK
        token: tok-nested-LEAK
MCP_Servers:
  GitHub:
    command: npx
    Headers:
      Authorization: Bearer hdr-LEAK
      X-Custom-Auth: custom-LEAK
    Env:
      FOO: env-LEAK
      DISPLAY: ":1"
auxiliary:
  env:
    OPENAI_API_KEY: sk-other-env-LEAK
    DISPLAY: ":1"
  headers:
    Authorization: Bearer other-hdr-LEAK
    X-Trace: keep-me
"""


def test_case_variants_nested_lists_and_other_env_sections_stay_local(tmp_path):
    """API_KEY, apiKey, x-api-key, Authorization, nested lists, provider dicts.

    mcp env/headers are local even under MCP_Servers / Headers / Env.
    A non-mcp env map drops credential-named keys and still syncs the rest.
    """
    a = make_home(tmp_path, "a", config=CASE_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    conf = _store_config(tmp_path / "store", result["code"])
    packed = json.dumps(conf)
    assert "LEAK" not in packed, packed
    assert conf["model"]["default"] == "deepseek-v4-flash"
    assert conf["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert conf["custom_providers"][0]["models"] == ["a"]
    assert "apiKey" not in conf["custom_providers"][0]
    assert conf["MCP_Servers"]["GitHub"]["command"] == "npx"
    assert "Headers" not in conf["MCP_Servers"]["GitHub"]
    assert "Env" not in conf["MCP_Servers"]["GitHub"]
    assert conf["auxiliary"]["env"] == {"DISPLAY": ":1"}
    assert conf["auxiliary"]["headers"] == {"X-Trace": "keep-me"}
    assert conf["nested"][0]["accounts"][0]["name"] == "acct"
    assert "token" not in conf["nested"][0]["accounts"][0]
    assert "Authorization" not in conf["nested"][0]["accounts"][0]


def test_incoming_poison_cannot_overwrite_or_delete_local_secrets(tmp_path):
    attacks = [
        ("omit", lambda c: c["model"].pop("api_key", None)),
        ("null", lambda c: c["model"].__setitem__("api_key", None)),
        ("empty", lambda c: c["model"].__setitem__("api_key", "")),
        ("parent-null", lambda c: c.__setitem__("model", None)),
        ("parent-scalar", lambda c: c.__setitem__("model", "clobber")),
        ("providers-empty", lambda c: c.__setitem__("custom_providers", [])),
        ("mcp-env-gone", lambda c: c["mcp_servers"]["github"].pop("env", None)),
        ("mcp-headers-null", lambda c: c["mcp_servers"]["github"].__setitem__("headers", None)),
    ]
    # Each attack is its own herd. A raw store inject does not carry a normal
    # parent revision, so chaining them makes the next pull look like a conflict
    # and stops exercising the merge.
    for name, mutate in attacks:
        a = make_home(tmp_path, f"a-{name}", config=SECRET_CONFIG)
        result = engine.init(a, str(tmp_path / f"store-{name}"), name="desk")
        b = make_home(tmp_path, f"b-{name}", config="model:\n  default: x\n")
        engine.join(b, str(tmp_path / f"store-{name}"), result["code"], name="laptop")
        poisoned = yamlutil.safe_load(SECRET_CONFIG)
        poisoned["model"]["default"] = f"from-{name}"
        mutate(poisoned)
        _poisoned_peer_push(b, tmp_path / f"store-{name}", poisoned)
        engine.pull(engine.open_context(a))
        live = yamlutil.safe_load((a / "config.yaml").read_text())
        text = (a / "config.yaml").read_text()
        assert "EVIL" not in text
        assert live["model"]["api_key"] == "sk-model-LEAK", name
        assert live["custom_providers"][0]["api_key"] == "sk-list-LEAK", name
        assert live["mcp_servers"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp-env-LEAK", name
        assert live["mcp_servers"]["github"]["headers"]["Authorization"] == "Bearer hdr-LEAK", name
        # Replacing the parent with null or a scalar cannot smuggle a new model name through.
        if name in {"parent-null", "parent-scalar"}:
            assert live["model"]["default"] == "deepseek-v4-flash", name
        else:
            assert live["model"]["default"] == f"from-{name}", name


def test_a_real_push_cannot_null_out_a_local_secret(tmp_path):
    """The public push path, not only a hand-built store blob."""
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config=SECRET_CONFIG)
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    conf = yamlutil.safe_load((b / "config.yaml").read_text())
    conf["model"] = None
    conf["custom_providers"] = []
    conf["display"]["skin"] = "from-real-push"
    (b / "config.yaml").write_text(yamlutil.safe_dump(conf))
    engine.push(engine.open_context(b))
    engine.pull(engine.open_context(a))
    live = yamlutil.safe_load((a / "config.yaml").read_text())
    assert live["model"]["api_key"] == "sk-model-LEAK"
    assert live["model"]["default"] == "deepseek-v4-flash"
    assert live["custom_providers"][0]["api_key"] == "sk-list-LEAK"
    assert live["display"]["skin"] == "from-real-push"
    assert live["mcp_servers"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp-env-LEAK"


def test_fresh_join_does_not_receive_a_poisoned_api_key(tmp_path):
    a = make_home(tmp_path, "a", config="model:\n  default: desk\n")
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    poisoned = {"model": {"default": "peer", "api_key": "sk-JOIN-LEAK", "apiKey": "sk-JOIN-CAMEL"},
                "mcp_servers": {"x": {"command": "npx", "env": {"FOO": "env-JOIN-LEAK"},
                                      "headers": {"Authorization": "Bearer JOIN"}}}}
    _poisoned_peer_push(a, tmp_path / "store", poisoned)
    b = make_home(tmp_path, "b", config="model:\n  default: laptop\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    text = (b / "config.yaml").read_text()
    assert "LEAK" not in text and "Bearer JOIN" not in text
    live = yamlutil.safe_load(text)
    assert live["model"]["default"] == "peer"
    assert "api_key" not in live["model"] and "apiKey" not in live["model"]
    assert "env" not in live["mcp_servers"]["x"]
    assert "headers" not in live["mcp_servers"]["x"]
    assert live["mcp_servers"]["x"]["command"] == "npx"


def test_take_theirs_does_not_import_or_drop_credentials(tmp_path):
    a = make_home(tmp_path, "a", config=SECRET_CONFIG)
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config=SECRET_CONFIG.replace("sk-list-LEAK", "sk-b-LEAK"))
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    # Both sides edit the provider list so the pull records a conflict.
    for home, models in ((a, ["a", "b", "from-a"]), (b, ["a", "b", "from-b"])):
        conf = yamlutil.safe_load((home / "config.yaml").read_text())
        conf["custom_providers"][0]["models"] = models
        conf["custom_providers"][0]["api_key"] = "sk-EVIL" if home == b else conf["custom_providers"][0]["api_key"]
        (home / "config.yaml").write_text(yamlutil.safe_dump(conf))
    engine.push(engine.open_context(b))
    pulled = engine.pull(engine.open_context(a))
    assert any(c.get("path") == "custom_providers" for c in pulled["conflicts"])
    saved = json.dumps(json.loads((a / "plugin-data" / "herd" / "conflicts.json").read_text()))
    assert "LEAK" not in saved and "EVIL" not in saved
    engine.resolve(a, "config", "theirs")
    live = yamlutil.safe_load((a / "config.yaml").read_text())
    assert live["custom_providers"][0]["models"] == ["a", "b", "from-b"]
    assert live["custom_providers"][0]["api_key"] == "sk-list-LEAK"
    assert "EVIL" not in (a / "config.yaml").read_text()


def test_cron_skip_is_recorded_and_not_reapplied_until_opt_in(tmp_path):
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    result = engine.init(a, str(tmp_path / "store"), name="desk", include_cron=True)
    b = make_home(tmp_path, "b")
    (b / "cron").mkdir()
    local_jobs = '{"jobs": [{"id": "local"}]}\n'
    (b / "cron" / "jobs.json").write_text(local_jobs)
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    state = json.loads((b / "plugin-data" / "herd" / "state.json").read_text())
    assert state.get("sync_cron") is False
    assert state.get("declined_seen", {}).get("file:cron")
    base = json.loads((b / "plugin-data" / "herd" / "base.json").read_text())
    assert "file:cron" not in (base.get("items") or {})

    first = engine.pull(engine.open_context(b))
    second = engine.pull(engine.open_context(b))
    assert "file:cron" in first["declined"] and "file:cron" in second["declined"]
    # The skip is recorded once per revision; a later pull does not nag again
    # and does not install or delete the local file.
    assert not any("cron" in w.lower() for w in second["warnings"])
    assert (b / "cron" / "jobs.json").read_text() == local_jobs
    ctx = engine.open_context(b)
    ctx.state["sync_cron"] = "false"
    engine.pull(ctx)
    assert (b / "cron" / "jobs.json").read_text() == local_jobs

    # A machine with no local cron file still has the jobs waiting. Opting in
    # later installs them, because the decline was not recorded as agreement.
    d = make_home(tmp_path, "d")
    engine.join(d, str(tmp_path / "store"), result["code"], name="phone")
    assert not (d / "cron" / "jobs.json").exists()
    ctx = engine.open_context(d)
    ctx.state["sync_cron"] = True
    (ctx.data / "state.json").write_text(json.dumps(ctx.state))
    opted = engine.pull(engine.open_context(d))
    assert "file:cron" not in opted.get("declined", [])
    assert (d / "cron" / "jobs.json").read_text() == CRON


def test_pair_without_cron_does_not_install_jobs(tmp_path):
    a = make_home(tmp_path, "a")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    engine.init(a, str(tmp_path / "store"), name="desk", include_cron=True)
    started = engine.pair_start(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b")
    finished = engine.pair_finish(b, started["code"], str(tmp_path / "store"), name="laptop")
    assert not (b / "cron" / "jobs.json").exists()
    assert "file:cron" in finished["pulled"]["declined"]
    c = make_home(tmp_path, "c")
    started = engine.pair_start(a, str(tmp_path / "store"), name="desk")
    engine.pair_finish(c, started["code"], str(tmp_path / "store"), name="phone", include_cron=True)
    assert (c / "cron" / "jobs.json").read_text() == CRON


def test_git_env_keeps_platform_runtime_and_drops_everything_else():
    src = {
        "Path": r"C:\Git\cmd",
        "SystemRoot": r"C:\Windows",
        "TMPDIR": "/var/folders/xx/T",
        "TEMP": r"C:\Users\u\AppData\Local\Temp",
        "HOME": "/h",
        "http_proxy": "http://proxy:8080",
        "GIT_EXEC_PATH": "/usr/lib/git-core",
        "CURL_CA_BUNDLE": "/etc/ssl/cert.pem",
        "OPENAI_API_KEY": "sk-x",
        "GH_TOKEN": "ghp",
        "GITHUB_TOKEN": "ghp",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "GIT_DIR": "/elsewhere",
        "GIT_WORK_TREE": "/elsewhere",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.sshCommand",
        "GIT_CONFIG_VALUE_0": "steal",
        "GIT_CONFIG_PARAMETERS": "'core.sshCommand=steal'",
        "AUTHORIZATION": "Bearer nope",
    }
    env = store_mod.git_env(src)
    assert env["Path"] == r"C:\Git\cmd"
    assert env["SystemRoot"] == r"C:\Windows"
    assert env["TMPDIR"] == "/var/folders/xx/T"
    assert env["TEMP"] == src["TEMP"]
    assert env["http_proxy"] == "http://proxy:8080"
    assert env["GIT_EXEC_PATH"] == "/usr/lib/git-core"
    assert env["CURL_CA_BUNDLE"] == "/etc/ssl/cert.pem"
    for banned in ("OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY",
                   "GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0",
                   "GIT_CONFIG_VALUE_0", "GIT_CONFIG_PARAMETERS", "AUTHORIZATION"):
        assert banned not in env


def test_every_package_subprocess_passes_the_git_environment():
    """ssh and credential helpers are not separate call sites: git starts them."""
    root = Path(__file__).resolve().parents[1] / "herd"
    spawners = {"run", "Popen", "call", "check_call", "check_output", "popen", "system"}
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in spawners:
                continue
            base = node.func.value
            owner = base.id if isinstance(base, ast.Name) else ""
            if owner not in {"subprocess", "os"}:
                continue
            if not any(kw.arg == "env" for kw in node.keywords):
                offenders.append(f"{path.name}:{node.lineno} {owner}.{node.func.attr}")
    assert offenders == []
    # And there is exactly one subprocess.run, so a new call site cannot hide.
    runs = [
        node for node in ast.walk(ast.parse((root / "store.py").read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
    ]
    assert len(runs) == 1


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX shell wrapper")
def test_ssh_and_credential_helper_see_only_the_git_environment(tmp_path, monkeypatch):
    log = tmp_path / "child-env.log"
    helper = tmp_path / "helper.sh"
    helper.write_text(f"#!/bin/sh\nenv >> {log}\necho ---- >> {log}\nexit 0\n")
    helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("GH_TOKEN", "ghp-should-not-leak")
    monkeypatch.setenv("GIT_SSH_COMMAND", str(helper))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    store_mod._git(["init", "--quiet"], repo)
    # core.sshCommand is how git starts ssh. A local remote never would.
    store_mod._git(
        ["-c", f"core.sshCommand={helper}", "ls-remote", "ssh://invalid.example/nope.git"],
        repo, check=False,
    )
    seen = log.read_text()
    assert "----" in seen
    assert "should-not-leak" not in seen
    assert "OPENAI_API_KEY" not in seen and "GH_TOKEN" not in seen
    assert "TMPDIR=" in seen and "PATH=" in seen and "HOME=" in seen


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX shell wrapper")
def test_three_homes_through_a_bare_repo_leak_no_secret(tmp_path, monkeypatch):
    """Memory and skills still sync; planted config secrets never reach git."""
    import shutil

    real_git = shutil.which("git")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git-env.log"
    wrapper = bindir / "git"
    wrapper.write_text(f"#!/bin/sh\nenv >> {log}\necho ---- >> {log}\nexec {real_git} \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-planted-OPENAI")
    monkeypatch.setenv("GH_TOKEN", "ghp-planted-GH")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-planted-SECRET")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    bare = tmp_path / "remote.git"
    subprocess.run([real_git, "init", "--bare", "-q", str(bare)], check=True)

    def plant(name, skin):
        text = SECRET_CONFIG.replace("LEAK", f"LEAK-{name}").replace("skin: default", f"skin: {skin}")
        return make_home(tmp_path, name, config=text)

    a = plant("a", "desk")
    (a / "memories" / "USER.md").write_text("user from desk\n")
    (a / "SOUL.md").write_text("soul from desk\n")
    (a / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nfrom desk\n")
    (a / "cron").mkdir()
    (a / "cron" / "jobs.json").write_text(CRON)
    result = engine.init(a, str(tmp_path / "work-a"), remote=str(bare), name="desk", include_cron=True)
    b = plant("b", "laptop")
    joined_b = engine.join(b, str(bare), result["code"], name="laptop")
    c = plant("c", "phone")
    engine.join(c, str(bare), result["code"], name="phone", include_cron=True)

    assert (b / "memories" / "USER.md").read_text() == "user from desk\n"
    assert (b / "SOUL.md").read_text() == "soul from desk\n"
    assert "from desk" in (b / "skills" / "demo" / "SKILL.md").read_text()
    assert not (b / "cron" / "jobs.json").exists()
    assert "file:cron" in joined_b["pulled"]["declined"]
    assert (c / "cron" / "jobs.json").read_text() == CRON

    # A non-secret edit still travels, and nobody adopts another machine's key.
    live_a = yamlutil.safe_load((a / "config.yaml").read_text())
    live_a["display"]["skin"] = "agate"
    (a / "config.yaml").write_text(yamlutil.safe_dump(live_a))
    (a / "memories" / "MEMORY.md").write_text("memory revised on desk\n")
    engine.sync(a)
    engine.pull(engine.open_context(b))
    engine.pull(engine.open_context(c))
    assert yamlutil.safe_load((b / "config.yaml").read_text())["display"]["skin"] == "agate"
    assert "memory revised on desk" in (c / "memories" / "MEMORY.md").read_text()
    assert yamlutil.safe_load((b / "config.yaml").read_text())["model"]["api_key"] == "sk-model-LEAK-b"
    assert yamlutil.safe_load((c / "config.yaml").read_text())["model"]["api_key"] == "sk-model-LEAK-c"
    assert "LEAK-a" not in (b / "config.yaml").read_text()

    planted = ("LEAK-a", "LEAK-b", "LEAK-c", "sk-planted-OPENAI", "ghp-planted-GH", "aws-planted-SECRET")
    # Uncompressed git objects, not just the working tree: a secret packed into
    # a blob would show up here even when the file is encrypted on disk.
    listed = subprocess.run(
        [real_git, "--git-dir", str(bare), "rev-list", "--all", "--objects"],
        check=True, capture_output=True, text=True,
    )
    oids = [line.split()[0] for line in listed.stdout.splitlines() if line.strip()]
    shown = subprocess.run(
        [real_git, "--git-dir", str(bare), "cat-file", "--batch"],
        input="".join(oid + "\n" for oid in oids).encode(),
        check=True, capture_output=True,
    )
    for secret in planted:
        assert secret.encode() not in shown.stdout, secret
    for folder in (tmp_path / "work-a", b / "plugin-data" / "herd" / "store", c / "plugin-data" / "herd" / "store"):
        if not folder.exists():
            continue
        raw = b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file() and ".git" not in p.parts)
        for secret in planted:
            assert secret.encode() not in raw, secret

    # Decrypt the packed config as well: ciphertext grep can miss a lucky encoding.
    for home in (a, b, c):
        ctx = engine.open_context(home)
        entry = ctx.store.merged()["config"]
        _iid, _kind, payload = items.open_item(ctx.store.get(ctx.key, entry.oid))
        assert "LEAK" not in payload.decode()

    seen = log.read_text()
    assert seen.count("----") >= 5
    for secret in ("sk-planted-OPENAI", "ghp-planted-GH", "aws-planted-SECRET"):
        assert secret not in seen
    assert "OPENAI_API_KEY" not in seen and "GH_TOKEN" not in seen and "AWS_SECRET_ACCESS_KEY" not in seen
    assert "TMPDIR=" in seen


def test_versions_say_1_2_1():
    from herd import __version__

    root = Path(__file__).resolve().parents[1]
    assert __version__ == "1.2.1"
    plugin = (root / "plugin.yaml").read_text(encoding="utf-8")
    assert "version: 1.2.1" in plugin
    assert "API keys are not synced" in plugin
    assert 'version = "1.2.1"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "API keys are not synced" in readme
    assert "config.yaml" in readme.split("API keys are not synced", 1)[1][:400]
