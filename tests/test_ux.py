"""The front door: pairing, one-line status, and settling a disagreement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from herd import engine, pairing, yamlutil

CONFIG = """\
model:
  default: m
  provider: p
display:
  skin: default
terminal:
  backend: local
  cwd: /home/{name}/work
"""


def make_home(root: Path, name: str) -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(CONFIG.format(name=name))
    (home / "memories").mkdir(exist_ok=True)
    (home / "memories" / "MEMORY.md").write_text(f"memory from {name}\n")
    skill = home / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nbody\n")
    return home


def skin(home: Path) -> str:
    return (yamlutil.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {})["display"]["skin"]


def pair(a: Path, b: Path, store: Path) -> dict:
    started = engine.pair_start(a, str(store), name="desktop")
    return engine.pair_finish(b, started["code"], str(store), name="laptop")


# ── pairing ──────────────────────────────────────────────────────────────────
def test_a_short_code_replaces_the_long_recovery_code(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    result = pair(a, b, tmp_path / "store")

    assert len(result["paired_with"]) > 0
    assert (b / "skills" / "demo" / "SKILL.md").exists()
    assert (b / "memories" / "MEMORY.md").exists()
    # same machine keeps its own path
    assert "home/b/work" in (b / "config.yaml").read_text(encoding="utf-8")


def test_the_code_is_twenty_characters_and_typed_once(tmp_path):
    a = make_home(tmp_path, "a")
    started = engine.pair_start(a, str(tmp_path / "store"), name="desktop")

    assert len(pairing.normalize(started["code"])) == 20
    assert started["code"].count("-") == 3
    assert (tmp_path / "store" / "pairing.json").exists()

    b = make_home(tmp_path, "b")
    engine.pair_finish(b, started["code"], str(tmp_path / "store"))
    assert not (tmp_path / "store" / "pairing.json").exists()


def test_a_used_code_does_not_pair_a_third_machine(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    c = make_home(tmp_path, "c")
    started = engine.pair_start(a, str(tmp_path / "store"), name="desktop")
    engine.pair_finish(b, started["code"], str(tmp_path / "store"))

    with pytest.raises(engine.HerdError):
        engine.pair_finish(c, started["code"], str(tmp_path / "store"))


def test_a_wrong_code_says_so_and_changes_nothing(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    engine.pair_start(a, str(tmp_path / "store"), name="desktop")

    with pytest.raises(pairing.PairingError) as err:
        engine.pair_finish(b, "AAAAA-BBBBB-CCCCC-DDDDD", str(tmp_path / "store"))
    assert "does not open" in str(err.value)
    assert not (b / "plugin-data" / "herd" / "state.json").exists()


def test_an_expired_code_is_refused(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    started = engine.pair_start(a, str(tmp_path / "store"), name="desktop", ttl=-1)

    with pytest.raises(pairing.PairingError) as err:
        engine.pair_finish(b, started["code"], str(tmp_path / "store"))
    assert "expired" in str(err.value)


def test_editing_the_expiry_in_the_store_does_not_revive_a_code(tmp_path):
    import time

    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    started = engine.pair_start(a, str(tmp_path / "store"), name="desktop", ttl=-1)
    doc = json.loads((tmp_path / "store" / "pairing.json").read_text(encoding="utf-8"))
    doc["expires_at"] = int(time.time()) + 3600          # what an attacker would try
    (tmp_path / "store" / "pairing.json").write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(pairing.PairingError):
        engine.pair_finish(b, started["code"], str(tmp_path / "store"))


def test_pairing_again_on_the_same_machine_reissues_a_code(tmp_path):
    a = make_home(tmp_path, "a")
    first = engine.pair_start(a, str(tmp_path / "store"), name="desktop")
    second = engine.pair_start(a, str(tmp_path / "store"), name="desktop")
    assert second["code"] != first["code"]
    assert second["store"] == first["store"]


def test_joining_with_a_local_setting_takes_the_herd_value_quietly(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: desk"))
    (b / "config.yaml").write_text((b / "config.yaml").read_text().replace("skin: default", "skin: laptop"))

    started = engine.pair_start(a, str(tmp_path / "store"), name="desktop")
    engine.pair_finish(b, started["code"], str(tmp_path / "store"), name="laptop")

    assert skin(b) == "desk"
    assert engine.conflicts(b) == []
    assert "conflict" not in engine.summary(b)
    rows = json.loads((b / "plugin-data" / "herd" / "conflicts.json").read_text())["entries"] \
        if (b / "plugin-data" / "herd" / "conflicts.json").exists() else []
    assert rows == []


# ── settling a disagreement ──────────────────────────────────────────────────
def test_taking_the_store_value_settles_the_item(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")

    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: dark"))
    engine.push(engine.open_context(a))
    (b / "config.yaml").write_text((b / "config.yaml").read_text().replace("skin: default", "skin: light"))

    pulled = engine.pull(engine.open_context(b))
    assert pulled["conflicts"]
    assert engine.conflicts(b)

    engine.resolve(b, "config", "theirs")
    assert skin(b) == "dark"
    assert engine.conflicts(b) == []


def test_keeping_mine_publishes_it_and_the_other_machine_adopts(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")

    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: dark"))
    engine.push(engine.open_context(a))
    (b / "config.yaml").write_text((b / "config.yaml").read_text().replace("skin: default", "skin: light"))
    engine.pull(engine.open_context(b))

    engine.resolve(b, "config", "mine")

    # b published its value; a had also edited, so a is asked rather than
    # silently overruled. One more decision on a settles the herd.
    engine.pull(engine.open_context(a))
    assert engine.conflicts(a)
    engine.resolve(a, "config", "theirs")

    assert skin(a) == "light"
    assert skin(b) == "light"
    assert engine.conflicts(a) == [] and engine.conflicts(b) == []


def test_taking_theirs_after_this_machine_published_its_own_value(tmp_path):
    """The CLI's `sync` is pull-then-push, so after a conflict this machine's
    entry is the newest in the store. "Take theirs" must still mean the peer's
    value, not the winner this machine just wrote."""
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")

    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: desk"))
    engine.push(engine.open_context(a))
    (b / "config.yaml").write_text((b / "config.yaml").read_text().replace("skin: default", "skin: laptop"))
    engine.sync(b)                      # pull records the conflict, push republishes ours
    assert engine.conflicts(b)

    engine.resolve(b, "config", "theirs")
    assert skin(b) == "desk"


def test_resolving_something_that_is_not_a_conflict_is_refused(tmp_path):
    a = make_home(tmp_path, "a")
    engine.pair_start(a, str(tmp_path / "store"), name="desktop")
    with pytest.raises(engine.HerdError):
        engine.resolve(a, "config", "theirs")
    with pytest.raises(engine.HerdError):
        engine.resolve(a, "config", "both")


# ── the one line ─────────────────────────────────────────────────────────────
def test_summary_is_a_sentence_about_the_herd(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")

    line = engine.summary(b)
    assert "machine" in line and "synced" in line
    assert "conflict" not in line


def test_summary_names_a_pending_conflict(tmp_path):
    a = make_home(tmp_path, "a")
    b = make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")
    (a / "config.yaml").write_text((a / "config.yaml").read_text().replace("skin: default", "skin: dark"))
    engine.push(engine.open_context(a))
    (b / "config.yaml").write_text((b / "config.yaml").read_text().replace("skin: default", "skin: light"))
    engine.pull(engine.open_context(b))

    assert "conflict" in engine.summary(b)


def test_summary_before_setup_offers_the_first_command(tmp_path):
    home = make_home(tmp_path, "fresh")
    assert "pair" in engine.summary(home)
