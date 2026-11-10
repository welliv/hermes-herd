"""Pull must not eat a newer local edit, and undo must really undo."""

from __future__ import annotations

import json

from herd import engine
from tests.test_engine import make_home


def _code(home):
    return json.loads((home / "plugin-data" / "herd" / "identity.json").read_text())["code"]


def test_sync_keeps_a_newer_local_soul(tmp_path):
    server = make_home(tmp_path, "server")
    (server / "SOUL.md").write_text("original soul\n")
    engine.init(server, str(tmp_path / "store"), name="server")
    laptop = make_home(tmp_path, "laptop")
    engine.join(laptop, str(tmp_path / "store"), _code(server), name="laptop")

    (server / "SOUL.md").write_text("server edited soul\n")
    engine.sync(server)

    assert (server / "SOUL.md").read_text() == "server edited soul\n"


def test_undo_removes_a_skill_the_pull_created(tmp_path):
    server = make_home(tmp_path, "server")
    engine.init(server, str(tmp_path / "store"), name="server")
    laptop = make_home(tmp_path, "laptop")
    engine.join(laptop, str(tmp_path / "store"), _code(server), name="laptop")

    fresh = server / "skills" / "fresh"
    fresh.mkdir()
    (fresh / "SKILL.md").write_text("---\nname: fresh\n---\nnew\n")
    engine.push(engine.open_context(server))
    engine.pull(engine.open_context(laptop))
    assert (laptop / "skills" / "fresh" / "SKILL.md").exists()
    assert (laptop / "skills" / "demo").exists()

    result = engine.undo(laptop)
    assert "skills/fresh" in result["removed"]
    assert not (laptop / "skills" / "fresh").exists()
    assert (laptop / "skills" / "demo" / "SKILL.md").exists()


def test_two_pulls_in_one_second_do_not_share_a_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.time, "time", lambda: 1_700_000_000.5)
    server = make_home(tmp_path, "server")
    engine.init(server, str(tmp_path / "store"), name="server")
    laptop = make_home(tmp_path, "laptop")
    engine.join(laptop, str(tmp_path / "store"), _code(server), name="laptop")

    def edit(skin: str) -> None:
        text = (server / "config.yaml").read_text().replace("skin: default", f"skin: {skin}")
        if f"skin: {skin}" not in text:
            text = (server / "config.yaml").read_text().replace("skin: agate", f"skin: {skin}")
        (server / "config.yaml").write_text(text)
        engine.push(engine.open_context(server))
        engine.pull(engine.open_context(laptop))

    edit("agate")
    edit("mono")
    names = sorted(p.name for p in (laptop / "plugin-data" / "herd" / "backups").iterdir() if p.is_dir())
    assert len(names) >= 2
    assert len(names) == len(set(names))
    assert names[-1] != names[-2]


def test_join_saves_the_memory_it_replaces_and_says_so(tmp_path):
    server = make_home(tmp_path, "server")
    engine.init(server, str(tmp_path / "store"), name="server")
    laptop = make_home(tmp_path, "laptop")
    result = engine.join(laptop, str(tmp_path / "store"), _code(server), name="laptop")

    text = (laptop / "memories" / "MEMORY.md").read_text()
    saved = laptop / "plugin-data" / "herd" / "pre-join-MEMORY.md"
    assert "memory from server" in text
    assert "memory from laptop" not in text
    assert saved.read_text().strip() == "memory from laptop"
    assert any("MEMORY.md" in w and "pre-join-MEMORY.md" in w for w in result["pulled"]["warnings"])


def test_memory_and_soul_edits_propagate_after_pairing(tmp_path):
    """A remote-only edit after join is a pull, not a conflict.

    Joining used to republish the same MEMORY.md and SOUL.md under a new
    revision. The other machine's later edit then parented on that revision,
    and the joiner — whose ancestor was still the older rev of the same bytes —
    treated it as both sides having changed.
    """
    root = tmp_path / "pair"
    def mk(name: str):
        home = root / name
        skill = home / "skills" / "research"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: research\n---\nb\n")
        (home / "memories").mkdir()
        (home / "SOUL.md").write_text("soul v1\n")
        (home / "config.yaml").write_text(f"model:\n  default: m\nterminal:\n  cwd: /{name}\n")
        return home

    server, laptop = mk("server"), mk("laptop")
    (server / "memories" / "MEMORY.md").write_text("mem v1\n")
    started = engine.pair_start(server, str(root / "store"), name="server")
    engine.pair_finish(laptop, started["code"], str(root / "store"), name="laptop")
    engine.sync(server)

    (server / "memories" / "MEMORY.md").write_text("mem v2\n")
    (server / "SOUL.md").write_text("soul v2\n")
    pushed = engine.sync(server)["second"]["pushed"]
    assert "memory:agent" in pushed and "file:soul" in pushed

    # The note is this machine's. It must survive the pull of the shared text.
    engine.set_note(laptop, "laptop only")
    result = engine.sync(laptop)
    assert result["first"]["conflicts"] == []
    assert "memory:agent" in result["first"]["applied"]
    assert "file:soul" in result["first"]["applied"]
    assert (laptop / "memories" / "MEMORY.md").read_text().startswith("mem v2\n")
    assert "laptop only" in (laptop / "memories" / "MEMORY.md").read_text()
    assert (laptop / "SOUL.md").read_text() == "soul v2\n"

    undone = engine.undo(laptop)
    assert "SOUL.md" in undone["files"]
    assert "memories/MEMORY.md" in undone["files"]
    assert (laptop / "SOUL.md").read_text() == "soul v1\n"
    assert "mem v1" in (laptop / "memories" / "MEMORY.md").read_text()
    assert "mem v2" not in (laptop / "memories" / "MEMORY.md").read_text()


def test_a_remote_change_is_a_pull_not_a_push(tmp_path):
    server = make_home(tmp_path, "server")
    engine.init(server, str(tmp_path / "store"), name="server")
    laptop = make_home(tmp_path, "laptop")
    engine.join(laptop, str(tmp_path / "store"), _code(server), name="laptop")
    (laptop / "memories" / "MEMORY.md").write_text("from the laptop\n")
    engine.push(engine.open_context(laptop))

    report = engine.diff(server)
    assert "memory:agent" in report["would_pull"]
    assert "memory:agent" not in report["would_push"]
    assert "memory:agent" in report["review_before_pull"]

    (server / "config.yaml").write_text(
        (server / "config.yaml").read_text().replace("skin: default", "skin: agate"))
    report = engine.diff(server)
    assert "config" in report["would_push"]
    assert "config" not in report["would_pull"]
