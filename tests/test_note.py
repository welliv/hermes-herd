"""Per-machine memory: shared context, plus a paragraph that never leaves.

The case that asked for this: three machines, one of them a VPS that is the
"risky one" and needs to know it. Memory has to be shared, but not identical.
"""

from __future__ import annotations

from pathlib import Path

from herd import engine, items


def make_home(root: Path, name: str) -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(f"model:\n  default: m\ndisplay:\n  skin: default\nterminal:\n  cwd: /{name}\n",
                                      encoding="utf-8")
    (home / "memories").mkdir(exist_ok=True)
    (home / "memories" / "MEMORY.md").write_text(f"memory from {name}\n", encoding="utf-8")
    skill = home / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nbody\n", encoding="utf-8")
    return home


def pair(a: Path, b: Path, store: Path) -> None:
    started = engine.pair_start(a, str(store), name="desktop")
    engine.pair_finish(b, started["code"], str(store), name="laptop")


def memory(home: Path) -> str:
    return (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")


def test_the_note_never_reaches_the_other_machine(tmp_path):
    a, b = make_home(tmp_path, "a"), make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")

    engine.set_note(a, "this box is the VPS, and the risky one")
    engine.push(engine.open_context(a))
    engine.pull(engine.open_context(b))

    assert "risky one" in memory(a)
    assert "risky one" not in memory(b)


def test_editing_only_the_note_is_not_a_change_to_push(tmp_path):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    engine.set_note(a, "v1")
    engine.push(engine.open_context(a))

    engine.set_note(a, "v2 — a different note")
    state = engine.status(a)

    assert {row["item"] for row in state["items"] if row["state"] != "in-sync"} == set()


def test_a_herd_update_keeps_the_local_note(tmp_path):
    a, b = make_home(tmp_path, "a"), make_home(tmp_path, "b")
    pair(a, b, tmp_path / "store")
    engine.set_note(b, "laptop: travels, no docker")

    (a / "memories" / "MEMORY.md").write_text("shared memory, rewritten\n", encoding="utf-8")
    engine.push(engine.open_context(a))
    engine.pull(engine.open_context(b))

    text = memory(b)
    assert "shared memory, rewritten" in text
    assert "laptop: travels, no docker" in text


def test_clearing_the_note_leaves_the_shared_text(tmp_path):
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "store"), name="desktop")
    engine.set_note(a, "temporary")
    assert engine.get_note(a) == "temporary"

    engine.set_note(a, None)
    assert engine.get_note(a) == ""
    assert items.LOCAL_BEGIN not in memory(a)
    assert "memory from a" in memory(a)
