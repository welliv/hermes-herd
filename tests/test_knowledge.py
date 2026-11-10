"""Knowledge scope: share what you taught it, not how each box is set up.

For the person who runs three machines as three profiles and is tired of
explaining the same context three times: skills and memory travel, settings do
not, and nothing gets tombstoned because it was out of scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from herd import engine, yamlutil

CONFIG = """\
model:
  default: {model}
display:
  skin: default
terminal:
  backend: local
  cwd: /home/{name}/work
"""


def make_home(root: Path, name: str, model: str = "m") -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(CONFIG.format(name=name, model=model), encoding="utf-8")
    (home / "memories").mkdir(exist_ok=True)
    (home / "memories" / "MEMORY.md").write_text(f"memory from {name}\n", encoding="utf-8")
    skill = home / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nbody\n", encoding="utf-8")
    return home


def skin(home: Path) -> str:
    return (yamlutil.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {})["display"]["skin"]


def pair_knowledge(a: Path, b: Path, store: Path) -> None:
    started = engine.pair_start(a, str(store), name="desktop", scope="knowledge")
    engine.set_scope(b, "knowledge")
    engine.pair_finish(b, started["code"], str(store), name="laptop")


def test_skills_and_memory_travel_but_settings_do_not(tmp_path):
    a, b = make_home(tmp_path, "a"), make_home(tmp_path, "b")
    (b / "skills").mkdir(exist_ok=True)
    pair_knowledge(a, b, tmp_path / "store")

    # a skill added on the desktop arrives
    skill = a / "skills" / "research"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: research\n---\nnotes\n", encoding="utf-8")
    # and so does a memory edit
    (a / "memories" / "MEMORY.md").write_text("shared context\n", encoding="utf-8")
    engine.push(engine.open_context(a))
    engine.pull(engine.open_context(b))

    assert (b / "skills" / "research" / "SKILL.md").exists()
    assert "shared context" in (b / "memories" / "MEMORY.md").read_text(encoding="utf-8")

    # a display change on one machine stays there
    (a / "config.yaml").write_text(
        (a / "config.yaml").read_text(encoding="utf-8").replace("skin: default", "skin: dark"),
        encoding="utf-8",
    )
    engine.push(engine.open_context(a))
    pulled = engine.pull(engine.open_context(b))

    assert skin(b) == "default"
    assert "config" not in pulled["applied"]


def test_a_knowledge_machine_ignores_a_settings_item_from_a_profile_peer(tmp_path):
    a, b = make_home(tmp_path, "a"), make_home(tmp_path, "b")
    engine.init(a, str(tmp_path / "store"), name="desktop")           # profile scope
    (a / "config.yaml").write_text(
        (a / "config.yaml").read_text(encoding="utf-8").replace("skin: default", "skin: dark"),
        encoding="utf-8",
    )
    engine.push(engine.open_context(a))

    engine.set_scope(b, "knowledge")          # chosen before the first pull
    engine.join(b, str(tmp_path / "store"), engine.open_context(a).identity["code"], name="laptop")
    engine.pull(engine.open_context(b))

    assert skin(b) == "default"


def test_dropping_settings_from_scope_does_not_tombstone_them(tmp_path):
    """Switching to knowledge must not tell the herd the config was deleted."""
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    engine.set_scope(a, "knowledge")
    engine.push(engine.open_context(a))

    merged = engine.open_context(a).store.merged()
    entry = merged.get("config")
    assert entry is None or not entry.deleted


def test_scope_survives_a_reload_and_is_reported(tmp_path):
    a = make_home(tmp_path, "a")
    engine.pair_start(a, str(tmp_path / "store"), name="desktop", scope="knowledge")

    assert engine.open_context(a).policy.scope == "knowledge"
    assert engine.set_scope(a, "profile")["scope"] == "profile"
    with pytest.raises(engine.HerdError):
        engine.set_scope(a, "everything")


def test_status_and_summary_ignore_out_of_scope_items(tmp_path):
    a, b = make_home(tmp_path, "a"), make_home(tmp_path, "b")
    pair_knowledge(a, b, tmp_path / "store")
    (a / "config.yaml").write_text(
        (a / "config.yaml").read_text(encoding="utf-8").replace("skin: default", "skin: dark"),
        encoding="utf-8",
    )
    engine.push(engine.open_context(a))

    state = engine.status(b)
    assert "config" not in {row["item"] for row in state["items"]}
    assert "to pull" not in engine.summary(b)
