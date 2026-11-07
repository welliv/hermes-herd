"""Unit tests: keys, merge rules, policy, env rendering."""

from __future__ import annotations

import json

import pytest

from herd import config_merge, crypto, items, policy, yamlutil


# ── crypto ───────────────────────────────────────────────────────────────────
def test_code_round_trip_opens_the_same_key():
    key = crypto.new_key()
    code = crypto.format_code(key)
    salt = b"0123456789abcdef"
    derived = crypto.derive_key(code, salt)
    assert crypto.derive_key(key, salt) == derived
    assert crypto.verify_code(derived, crypto.store_check(derived))


def test_code_is_tolerable_to_copy_by_hand():
    code = crypto.format_code(crypto.new_key())
    assert code.startswith("HERD-")
    sloppy = code.lower().replace("-", " ")
    assert crypto.parse_code(sloppy) == crypto.parse_code(code)


def test_wrong_code_is_rejected_with_a_sentence():
    key = crypto.new_key()
    with pytest.raises(crypto.BadCode):
        crypto.parse_code("HERD-AA")
    other = crypto.derive_key(crypto.format_code(crypto.new_key()), b"salt")
    assert not crypto.verify_code(other, crypto.store_check(key))


def test_sealed_blob_does_not_open_in_another_store():
    key = crypto.new_key()
    blob = crypto.seal(key, b"secret config", "store_one")
    assert crypto.open_sealed(key, blob, "store_one") == b"secret config"
    with pytest.raises(crypto.TamperedBlob):
        crypto.open_sealed(key, blob, "store_two")


def test_tampered_ciphertext_is_detected():
    key = crypto.new_key()
    blob = bytearray(crypto.seal(key, b"payload", "s"))
    blob[-1] ^= 0x01
    with pytest.raises(crypto.TamperedBlob):
        crypto.open_sealed(key, bytes(blob), "s")


def test_object_names_are_keyed_not_plain_hashes():
    import hashlib

    key = crypto.new_key()
    data = b"model.default: gpt-5"
    oid = crypto.object_id(key, data)
    assert oid != hashlib.sha256(data).hexdigest()
    assert oid == crypto.object_id(key, data)
    assert oid != crypto.object_id(crypto.new_key(), data)


# ── config merge ─────────────────────────────────────────────────────────────
def test_remote_change_applies_when_local_did_not_touch_it():
    base = {"model": {"default": "a"}}
    local = {"model": {"default": "a"}}
    remote = {"model": {"default": "b"}}
    out = config_merge.merge(base, local, remote)
    assert out.merged["model"]["default"] == "b"
    assert not out.conflicts


def test_local_change_survives_a_remote_merge():
    base = {"terminal": {"cwd": "/a"}}
    local = {"terminal": {"cwd": "/b"}}
    remote = {"terminal": {"cwd": "/a"}}
    out = config_merge.merge(base, local, remote)
    assert out.merged["terminal"]["cwd"] == "/b"


def test_both_sides_changed_records_a_conflict_and_keeps_local():
    base = {"display": {"skin": "default"}}
    local = {"display": {"skin": "neon"}}
    remote = {"display": {"skin": "mono"}}
    out = config_merge.merge(base, local, remote)
    assert out.merged["display"]["skin"] == "neon"
    assert [c.path for c in out.conflicts] == ["display.skin"]
    assert out.conflicts[0].resolution == "local"
    assert out.conflicts[0].to_json()["remote"] == "mono"


def test_prefer_remote_wins_the_same_conflict():
    out = config_merge.merge(
        {"display": {"skin": "default"}},
        {"display": {"skin": "neon"}},
        {"display": {"skin": "mono"}},
        prefer="remote",
    )
    assert out.merged["display"]["skin"] == "mono"
    assert out.conflicts[0].resolution == "remote"


def test_local_only_keys_never_adopt_the_remote_value():
    out = config_merge.merge(
        {"webapp": {"port": 9120}},
        {"webapp": {"port": 9120}},
        {"webapp": {"port": 8000}},
        is_local_only=lambda p: p == "webapp.port",
    )
    assert out.merged["webapp"]["port"] == 9120
    assert "webapp.port" in out.local_only_kept


def test_local_only_key_missing_remotely_is_not_deleted():
    out = config_merge.merge(
        {},
        {"platforms": {"telegram": {"token": "x"}}},
        {"model": {"default": "gpt"}},
        is_local_only=lambda p: p.startswith("platforms."),
    )
    assert out.merged["platforms"]["telegram"]["token"] == "x"
    assert out.merged["model"]["default"] == "gpt"


def test_key_deleted_remotely_disappears_locally():
    base = {"agent": {"verbose": False, "max_turns": 150}}
    local = {"agent": {"verbose": False, "max_turns": 150}}
    remote = {"agent": {"max_turns": 150}}
    out = config_merge.merge(base, local, remote)
    assert "verbose" not in out.merged["agent"]


def test_config_version_takes_the_highest_number():
    out = config_merge.merge({"_config_version": 52}, {"_config_version": 52}, {"_config_version": 53})
    assert out.merged["_config_version"] == 53


def test_render_keeps_comments_and_other_keys():
    local = "# my notes\nmodel:\n  default: old  # inline\nterminal:\n  backend: docker\n"
    merged = {"model": {"default": "new"}, "terminal": {"backend": "docker"}}
    text, preserved = config_merge.render(local, merged)
    assert preserved is True
    assert "# my notes" in text and "# inline" in text
    assert yamlutil.safe_load(text)["model"]["default"] == "new"


def test_merge_is_idempotent():
    base = {"a": 1}
    local = {"a": 1, "b": 2}
    remote = {"a": 1, "c": 3}
    once = config_merge.merge(base, local, remote).merged
    twice = config_merge.merge(base, once, remote).merged
    assert once == twice


# ── policy ───────────────────────────────────────────────────────────────────
def test_machine_bound_keys_are_local_by_default():
    p = policy.Policy()
    for path in ("terminal.backend", "terminal.cwd", "webapp.port", "platforms.telegram.enabled",
                 "database.path", "auth.adopt_external_logins", "plugins.entries.foo"):
        assert p.is_local_only(path), path
    for path in ("model.default", "display.skin", "agent.max_turns", "skills.creation_nudge_interval"):
        assert not p.is_local_only(path), path


def test_shared_overrides_the_default_local_rule():
    p = policy.Policy({"shared": ["platforms.telegram"]})
    assert not p.is_local_only("platforms.telegram.enabled")
    assert p.is_local_only("platforms.discord.enabled")


def test_machine_env_vars_stay_put():
    p = policy.Policy()
    assert not p.secret_allowed("PATH")
    assert not p.secret_allowed("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")
    assert p.secret_allowed("OPENAI_API_KEY")


def test_policy_file_round_trips(tmp_path):
    path = tmp_path / "policy.yaml"
    p = policy.Policy({"shared": ["cron"], "sync_secrets": False, "secret_skip": ["MY_LOCAL_*"]})
    p.save(path)
    again = policy.Policy.load(path)
    assert again.shared == ["cron"]
    assert again.sync_secrets is False
    assert not again.secret_allowed("MY_LOCAL_THING")
    assert "per machine and never synced" in path.read_text()


# ── env ──────────────────────────────────────────────────────────────────────
def test_env_render_only_touches_changed_lines():
    text = "# header\nFOO=1\nBAR=two words\nBAZ=3\n"
    out = items.render_env(text, {"FOO": "9", "NEW": "x"}, {"BAZ"})
    assert "# header" in out
    assert "FOO=9" in out
    assert 'BAR=two words' in out
    assert "BAZ" not in out
    assert "NEW=x" in out
    assert items.parse_env(out)["BAR"] == "two words"


def test_env_parse_ignores_comments_and_quotes():
    got = items.parse_env('# c\nA=1\nB="two"\nC=\'three\'\nnot a pair\n')
    assert got == {"A": "1", "B": "two", "C": "three"}


# ── items ────────────────────────────────────────────────────────────────────
def test_scrub_drops_only_local_paths():
    conf = {"model": {"default": "x"}, "webapp": {"port": 9120, "enabled": True}}
    out = items.scrub(conf, policy.Policy())
    assert out["model"]["default"] == "x"
    assert "webapp" not in out


def test_skill_platforms_are_read_from_frontmatter(tmp_path):
    d = tmp_path / "apple-notes"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: apple-notes\nplatforms: [macos]\n---\nbody\n")
    assert items.skill_platforms(d) == ["macos"]
    (d / "SKILL.md").write_text("no frontmatter")
    assert items.skill_platforms(d) == []


def test_dir_packing_is_deterministic(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text("hello")
    (d / "refs").mkdir()
    (d / "refs" / "a.md").write_text("ref")
    first = items.pack_dir(d)
    second = items.pack_dir(d)
    assert first == second
