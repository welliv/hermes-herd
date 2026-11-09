"""End-to-end: two and three real Hermes homes sharing one store."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from herd import crypto, engine, items, store as store_mod, yamlutil
from herd.util import file_lock

CONFIG_A = """\
# machine A
model:
  default: deepseek-v4-flash
  provider: deepseek
terminal:
  backend: local
  cwd: /home/a/work
webapp:
  port: 9120
display:
  skin: default
platforms:
  telegram:
    enabled: true
    home_channel:
      chat_id: 12345
"""

ENV_A = """\
# keys
DEEPSEEK_API_KEY=sk-aaa
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=hunter2
PATH=/usr/local/bin:/usr/bin
"""


def make_home(root: Path, name: str, config: str = CONFIG_A, env: str = ENV_A) -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(config)
    (home / ".env").write_text(env)
    (home / "memories").mkdir(exist_ok=True)
    (home / "memories" / "MEMORY.md").write_text(f"memory from {name}\n")
    skill = home / "skills" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
    return home


@pytest.fixture()
def herd(tmp_path):
    a = make_home(tmp_path, "a")
    store = tmp_path / "store"
    result = engine.init(a, str(store), name="desktop", sync_secrets=True)
    return {"root": tmp_path, "a": a, "store": store, "code": result["code"], "init": result}


def test_store_never_contains_plaintext(herd):
    blobs = b"".join(p.read_bytes() for p in herd["store"].rglob("*") if p.is_file())
    for secret in (b"sk-aaa", b"9120", b"deepseek-v4-flash", b"memory from"):
        assert secret not in blobs, secret


def test_scrubbed_config_keeps_machine_keys_out_of_the_store(herd):
    st = store_mod.open_store(herd["store"])
    key = st.unlock(herd["code"])
    merged = st.merged()
    payload = st.get(key, merged["config"].oid)
    conf = json.loads(payload)
    assert conf["model"]["default"] == "deepseek-v4-flash"
    assert "webapp" not in conf
    assert "platforms" not in conf
    assert "terminal" not in conf


def test_secrets_are_synced_but_machine_vars_are_not(herd):
    st = store_mod.open_store(herd["store"])
    key = st.unlock(herd["code"])
    env = json.loads(st.get(key, st.merged()["env"].oid))
    assert env["DEEPSEEK_API_KEY"] == "sk-aaa"
    assert "PATH" not in env
    assert "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD" not in env


def test_join_merges_without_breaking_the_new_machine(herd):
    b = make_home(
        herd["root"], "b",
        config="""\
model:
  default: gpt-5
terminal:
  backend: docker
  cwd: /srv/b
webapp:
  port: 9999
""",
        env="OPENAI_API_KEY=sk-bbb\nPATH=/usr/bin\n",
    )
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    conf = (b / "config.yaml").read_text()
    assert "deepseek-v4-flash" in conf          # shared: store wins
    assert "backend: docker" in conf            # local-only: untouched
    assert "cwd: /srv/b" in conf
    assert "port: 9999" in conf                 # local-only: untouched
    env = (b / ".env").read_text()
    assert "DEEPSEEK_API_KEY=sk-aaa" in env
    assert "OPENAI_API_KEY=sk-bbb" in env
    assert "PATH=/usr/bin" in env
    assert (b / "skills" / "demo" / "SKILL.md").exists()
    assert "memory from a" in (b / "memories" / "MEMORY.md").read_text()


def test_round_trip_new_key_travels_back(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    # B adds a portable setting; A must receive it.
    text = (b / "config.yaml").read_text()
    (b / "config.yaml").write_text(text.replace("display:\n  skin: default", "display:\n  skin: default\nagent:\n  max_turns: 42"))
    engine.push(engine.open_context(b))
    engine.pull(engine.open_context(herd["a"]))
    assert "max_turns: 42" in (herd["a"] / "config.yaml").read_text()


def test_same_key_edited_on_both_sides_keeps_local_and_records_it(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    # Both change display.skin after the join.
    for home, skin in ((herd["a"], "neon"), (b, "mono")):
        text = (home / "config.yaml").read_text().replace("skin: default", f"skin: {skin}")
        (home / "config.yaml").write_text(text)
    # B publishes first; A has edited but not yet synced, so the pull is where
    # the two edits meet. A keeps its own value and records B's.
    engine.push(engine.open_context(b))
    engine.pull(engine.open_context(herd["a"]))
    assert "skin: neon" in (herd["a"] / "config.yaml").read_text()
    rows = engine.conflicts(herd["a"])
    assert any(r["path"] == "display.skin" and r["kept"] == "local" and r["remote"] == "mono" for r in rows)


def test_remote_config_never_deletes_local_only_sections(herd):
    """A scrubbed payload has no terminal/webapp keys; a pull must not read that
    as a deletion and wipe the machine it is running on."""
    b = make_home(
        herd["root"], "b",
        config="model:\n  default: gpt-5\nterminal:\n  backend: docker\n  cwd: /srv/b\nwebapp:\n  port: 9999\n",
    )
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    (herd["a"] / "config.yaml").write_text(
        (herd["a"] / "config.yaml").read_text().replace("skin: default", "skin: agate")
    )
    engine.push(engine.open_context(herd["a"]))
    engine.pull(engine.open_context(b))
    conf = yamlutil.safe_load((b / "config.yaml").read_text())
    assert conf["terminal"]["backend"] == "docker"
    assert conf["terminal"]["cwd"] == "/srv/b"
    assert conf["webapp"]["port"] == 9999
    assert conf["display"]["skin"] == "agate"


def test_two_edits_to_one_skill_keep_both(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    for home, line in ((herd["a"], "from desktop"), (b, "from laptop")):
        (home / "skills" / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: d\n---\n" + line + "\n"
        )
    engine.push(engine.open_context(b))
    result = engine.pull(engine.open_context(herd["a"]))
    assert any(c["item"] == "skill:demo" for c in result["conflicts"])
    assert "from desktop" in (herd["a"] / "skills" / "demo" / "SKILL.md").read_text()
    saved = [p for c in result["conflicts"] for p in [c.get("remote", "")] if "conflicts/" in p]
    assert saved and Path(saved[0].split("saved to ")[-1]).exists()


def test_deleting_a_skill_propagates(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    assert (b / "skills" / "demo").exists()
    import shutil

    shutil.rmtree(herd["a"] / "skills" / "demo")
    engine.push(engine.open_context(herd["a"]))
    engine.pull(engine.open_context(b))
    assert not (b / "skills" / "demo").exists()


def test_pull_leaves_a_backup_that_undo_restores(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    original = (b / "config.yaml").read_text()
    (herd["a"] / "config.yaml").write_text((herd["a"] / "config.yaml").read_text().replace("skin: default", "skin: agate"))
    engine.push(engine.open_context(herd["a"]))
    result = engine.pull(engine.open_context(b))
    assert result["backup"]
    assert "agate" in (b / "config.yaml").read_text()
    engine.undo(b)
    assert (b / "config.yaml").read_text() == original


def test_platform_specific_skill_is_not_installed_elsewhere(tmp_path, monkeypatch):
    a = make_home(tmp_path, "a")
    mac = a / "skills" / "apple-notes"
    mac.mkdir(parents=True)
    (mac / "SKILL.md").write_text("---\nname: apple-notes\nplatforms: [macos]\n---\nbody\n")
    monkeypatch.setattr(items, "current_platform", lambda: "linux")
    result = engine.init(a, str(tmp_path / "store"), name="linux-box")
    assert "skill:apple-notes" not in result["pushed"]


def test_dry_run_status_does_not_write_objects(herd):
    st = store_mod.open_store(herd["store"])
    before = len(list((herd["store"] / "objects").rglob("*")))
    engine.status(herd["a"])
    after = len(list((herd["store"] / "objects").rglob("*")))
    assert before == after


def test_status_counts_after_join(herd):
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    state = engine.status(b)
    assert state["counts"]["differs"] == 0, [r for r in state["items"] if r["state"] != "in-sync"]
    assert state["counts"]["not_local"] == 0
    assert len(state["devices"]) == 2
    assert any(d["this_device"] for d in state["devices"])


def test_git_transport_clones_to_a_second_machine(herd, tmp_path):
    repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(repo)], check=True)
    a = make_home(tmp_path, "git-a")
    result = engine.init(a, str(tmp_path / "work"), remote=str(repo), name="desktop")
    b = make_home(tmp_path, "git-b", config="model:\n  default: other\n")
    joined = engine.join(b, str(repo), result["code"], name="laptop")
    assert "git" in joined["store"] or joined["store"]
    assert "deepseek-v4-flash" in (b / "config.yaml").read_text()


def test_no_secrets_mode_creates_no_env_item(tmp_path):
    a = make_home(tmp_path, "a")
    result = engine.init(a, str(tmp_path / "store"), name="desk", sync_secrets=False)
    assert "env" not in result["pushed"]
    assert "env" not in {row["item"] for row in engine.status(a)["items"]}


def test_lock_prevents_two_writers(tmp_path):
    from herd.store import StoreError

    lock = tmp_path / "x.lock"
    with file_lock(lock, timeout=0.2):
        with pytest.raises(Exception):
            with file_lock(lock, timeout=0.2):
                pass

def test_conflicts_disappear_once_the_sides_agree(herd):
    """The conflict list is the state of the last pull, not a history log."""
    b = make_home(herd["root"], "b")
    engine.join(b, str(herd["store"]), herd["code"], name="laptop", sync_secrets=True)
    for home, skin in ((herd["a"], "neon"), (b, "mono")):
        text = (home / "config.yaml").read_text().replace("skin: default", f"skin: {skin}")
        (home / "config.yaml").write_text(text)
    engine.push(engine.open_context(b))
    engine.pull(engine.open_context(herd["a"]))
    assert [r["path"] for r in engine.conflicts(herd["a"])] == ["display.skin"]

    # A accepts the store's value; the next pull meets no disagreement.
    (herd["a"] / "config.yaml").write_text(
        (herd["a"] / "config.yaml").read_text().replace("skin: neon", "skin: mono")
    )
    # Resolving by hand is enough: the list reflects the live config, not the log.
    assert engine.conflicts(herd["a"]) == []
    engine.pull(engine.open_context(herd["a"]))
    assert engine.conflicts(herd["a"]) == []


# --- what a store may and may not write into this machine's .env ------------


def test_a_store_key_cannot_smuggle_a_line_into_env(herd):
    ctx = engine.open_context(herd["a"])
    payload = json.dumps({
        "OPENAI_API_KEY": "from-peer",
        "SLACK_CHANNEL\nANTHROPIC_BASE_URL=https://evil.example #": "x",
    }).encode()
    engine._apply_env(ctx, payload, {}, "smuggle")
    text = (herd["a"] / ".env").read_text()
    env = items.parse_env(text)
    assert env["OPENAI_API_KEY"] == "from-peer"
    assert "ANTHROPIC_BASE_URL" not in env
    assert "evil.example" not in text


def test_this_machines_skip_rules_bind_on_the_way_in(herd):
    ctx = engine.open_context(herd["a"])
    payload = json.dumps({
        "HERMES_HOME": "/tmp/elsewhere",
        "PATH": "/evil",
        "DEEPSEEK_API_KEY": "from-peer",
    }).encode()
    result = engine._apply_env(ctx, payload, {}, "inbound")
    env = items.parse_env((herd["a"] / ".env").read_text())
    assert "HERMES_HOME" not in env
    assert env["PATH"] == "/usr/local/bin:/usr/bin"  # untouched, not the peer's value
    assert env["DEEPSEEK_API_KEY"] == "from-peer"
    assert sorted(result["skipped"]) == ["HERMES_HOME", "PATH"]


def test_a_managed_key_is_left_to_the_administrator(herd, monkeypatch):
    monkeypatch.setattr(
        engine.env_io, "refusal",
        lambda k: "managed by your administrator" if k == "STRIPE_KEY" else None,
    )
    ctx = engine.open_context(herd["a"])
    engine._apply_env(
        ctx, json.dumps({"STRIPE_KEY": "sk_live", "OTHER_KEY": "v"}).encode(), {}, "managed")
    env = items.parse_env((herd["a"] / ".env").read_text())
    assert "STRIPE_KEY" not in env
    assert env["OTHER_KEY"] == "v"


def test_env_write_is_announced_to_the_cache(herd, monkeypatch):
    seen = []
    monkeypatch.setattr(engine.env_io, "invalidate", lambda p: seen.append(Path(p)))
    ctx = engine.open_context(herd["a"])
    engine._apply_env(ctx, json.dumps({"NEW_KEY": "v"}).encode(), {}, "cache")
    assert seen == [herd["a"] / ".env"]


# --- credentials are opt-in, and "off" means the file is never opened --------


def test_secrets_are_off_until_asked(tmp_path):
    home = make_home(tmp_path, "quiet")
    result = engine.init(home, str(tmp_path / "store-off"), name="desk")
    assert result["device"]
    state = engine.status(home)
    assert state["secrets"] is False
    assert "env" not in items.scan(home, engine.open_context(home).policy)


def test_off_never_opens_env(herd, monkeypatch):
    ctx = engine.open_context(herd["a"])
    ctx.policy.sync_secrets = False
    real_read = Path.read_text

    def guarded(self, *a, **kw):
        if str(self).endswith(".env"):
            raise AssertionError("opened .env while secrets were off")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = engine._apply_env(ctx, json.dumps({"OPENAI_API_KEY": "from-peer"}).encode(), {}, "off")
    assert result["changed"] is False


def test_secrets_command_turns_it_on(tmp_path):
    home = make_home(tmp_path, "later")
    engine.init(home, str(tmp_path / "store-later"), name="desk")
    engine.set_secrets(home, True)
    ctx = engine.open_context(home)
    assert ctx.policy.sync_secrets is True
    engine.push(ctx)
    st = store_mod.open_store(tmp_path / "store-later")
    key = st.unlock(engine.open_context(home).identity["code"])
    merged = st.merged()
    assert "env" in merged
    assert json.loads(st.get(key, merged["env"].oid))["DEEPSEEK_API_KEY"] == "sk-aaa"


# --- the .env codec has to survive a round trip ------------------------------


def test_env_values_round_trip_unchanged():
    from herd import items

    for value in ("sk-abc", "pa#ss", "a b", 'say "hi"', "C:\\Users\\x", "$HOME/x", "it's"):
        text = items.render_env("", {"K": value}, set())
        assert items.parse_env(text)["K"] == value, (value, text)


def test_a_repeated_sync_does_not_escape_a_value_further():
    from herd import items

    value = 'say "hi"'
    for _ in range(3):
        text = items.render_env("", {"OPENAI_API_KEY": value}, set())
        value = items.parse_env(text)["OPENAI_API_KEY"]
    assert value == "say \"hi\""


def test_a_value_cannot_carry_a_line_into_env(herd):
    ctx = engine.open_context(herd["a"])
    before = (herd["a"] / ".env").read_text()
    result = engine._apply_env(
        ctx,
        json.dumps({"OPENAI_API_KEY": "sk-real\nANTHROPIC_BASE_URL=https://evil.example #"}).encode(),
        {}, "value-line")
    after = (herd["a"] / ".env").read_text()
    assert before == after
    assert result["changed"] is False
    assert "line break" in result["skipped"][0]


# --- housekeeping: the store must not grow forever ---------------------------


def test_gc_drops_unreferenced_objects_only(herd):
    ctx = engine.open_context(herd["a"])
    (herd["a"] / "config.yaml").write_text(
        (herd["a"] / "config.yaml").read_text().replace("skin: default", "skin: midnight"))
    engine.push(ctx)
    ctx = engine.open_context(herd["a"])
    before = len(ctx.store.objects())
    assert before >= 2
    result = engine.gc(herd["a"], keep_days=0)
    assert result["objects_removed"] >= 1
    after = engine.open_context(herd["a"]).store.objects()
    assert len(after) < before
    # every object a manifest still names is still there
    engine.pull(engine.open_context(herd["a"]))
    engine.push(engine.open_context(herd["a"]))


def test_gc_dry_run_keeps_everything(herd):
    engine.gc(herd["a"], keep_days=0, dry_run=True)
    ctx = engine.open_context(herd["a"])
    assert ctx.store.objects()
    engine.pull(ctx)


def test_gc_leaves_young_objects_alone(herd):
    result = engine.gc(herd["a"], keep_days=7)
    assert result["objects_removed"] == 0


# --- the profile Hermes routed us to is the one we sync ---------------------


def test_hermes_resolver_wins_over_the_env_var(monkeypatch, tmp_path):
    from herd import util

    routed = tmp_path / "routed"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "launch"))
    monkeypatch.setattr(util, "get_hermes_home", lambda: routed)
    assert util.hermes_home() == routed.resolve()


# --- the codec, over an alphabet full of trouble ----------------------------


def test_env_codec_round_trips_a_hostile_alphabet():
    import random
    from herd import items

    alphabet = 'ab #"\'\\\t$=/é漢'
    rng = random.Random(20261109)
    for _ in range(400):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        text = items.render_env("", {"K": value}, set())
        assert items.parse_env(text)["K"] == value, (value, text)
