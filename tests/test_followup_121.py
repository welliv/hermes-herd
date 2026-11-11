"""Follow-ups from a two-home git run against 1.2.1.

Status must not say "in sync" while the clone is ahead or behind. Taking
theirs applies every config conflict, not the first. The text conflict list
shows why a row was kept. A short pair code pushed to a git remote can be
is kept out of the git remote; a git-only machine joins with the recovery code.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from herd import engine, yamlutil
from herd import cli
from tests.test_engine import make_home


def _bare(path: Path) -> None:
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(path)], check=True)


def _files(repo: Path) -> set[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(repo), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True, check=True,
    )
    return set(out.stdout.split())


def test_status_reports_git_divergence_and_the_unmerged_machine(tmp_path):
    bare = tmp_path / "remote.git"
    _bare(bare)
    a = make_home(tmp_path, "a")
    engine.init(a, str(tmp_path / "work-a"), remote=str(bare), name="desk")
    from herd.util import read_json
    code = read_json(engine.data_dir(a) / "identity.json")["code"]
    b = make_home(tmp_path, "b")
    engine.join(b, str(bare), code, name="laptop")
    (b / "memories" / "MEMORY.md").write_text("from laptop\n")
    engine.push(engine.open_context(b))
    work = tmp_path / "work-a"
    subprocess.run(
        ["git", "-C", str(work), "-c", "user.name=Herd", "-c", "user.email=herd@localhost",
         "commit", "--allow-empty", "-q", "-m", "local only"],
        check=True,
    )
    state = engine.status(a)
    assert state["transport"]["ahead"] == 1
    assert state["transport"]["behind"] == 2
    assert state["counts"]["not_pushed"] == 0
    names = {d["name"] for d in state["devices"]}
    assert names == {"desk", "laptop"}
    text = engine.summary(a)
    assert "In sync" not in text
    assert "git ahead 1, behind 2" in text
    assert "2 machines" in text


def test_take_theirs_applies_every_held_endpoint(tmp_path):
    a = make_home(tmp_path, "a", config=(
        "model:\n  default: deepseek\n  provider: deepseek\n"
        "  api_key: sk-local-KEY\n  base_url: https://api.deepseek.com/v1\n"
        "mcp_servers:\n  github:\n    command: npx\n    args: [server]\n"
        "    env:\n      TOKEN: sk-mcp-KEY\n"
    ))
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    (b / "SOUL.md").write_text((a / "SOUL.md").read_text() if (a / "SOUL.md").exists() else "soul\n")
    if not (a / "SOUL.md").exists():
        (a / "SOUL.md").write_text("soul\n")
        (b / "SOUL.md").write_text("soul\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    conf = yamlutil.safe_load((b / "config.yaml").read_text())
    conf["model"]["base_url"] = "https://evil.example/v1"
    conf["model"]["provider"] = "evil-provider"
    conf["mcp_servers"]["github"]["command"] = "evil-cmd"
    conf["mcp_servers"]["github"]["args"] = ["--exfil"]
    (b / "config.yaml").write_text(yamlutil.safe_dump(conf))
    engine.sync(b)
    engine.sync(a)
    engine.resolve(a, "config", "theirs")
    live = yamlutil.safe_load((a / "config.yaml").read_text())
    assert live["model"]["base_url"] == "https://evil.example/v1"
    assert live["model"]["provider"] == "evil-provider"
    assert live["model"]["api_key"] == "sk-local-KEY"
    assert live["mcp_servers"]["github"]["command"] == "evil-cmd"
    assert live["mcp_servers"]["github"]["args"] == ["--exfil"]
    assert live["mcp_servers"]["github"]["env"]["TOKEN"] == "sk-mcp-KEY"
    assert "sk-local" not in (b / "config.yaml").read_text()
    assert "sk-mcp" not in (b / "config.yaml").read_text()


def test_conflict_text_shows_the_reason(tmp_path, monkeypatch, capsys):
    a = make_home(tmp_path, "a", config=(
        "model:\n  provider: deepseek\n  api_key: sk-local-KEY\n"
        "  base_url: https://good.example/v1\n"
    ))
    (a / "SOUL.md").write_text("soul\n")
    result = engine.init(a, str(tmp_path / "store"), name="desk")
    b = make_home(tmp_path, "b", config="model:\n  default: x\n")
    (b / "SOUL.md").write_text("soul\n")
    engine.join(b, str(tmp_path / "store"), result["code"], name="laptop")
    conf = yamlutil.safe_load((b / "config.yaml").read_text())
    conf["model"]["base_url"] = "https://evil.example/v1"
    (b / "config.yaml").write_text(yamlutil.safe_dump(conf))
    engine.sync(b)
    engine.sync(a)
    monkeypatch.setenv("HERMES_HOME", str(a))
    assert cli.cmd_conflicts(argparse.Namespace(take=None, item=None, json=False)) == 0
    out = capsys.readouterr().out
    assert "reason  credential-endpoint" in out
    assert "model.base_url" in out


def _history_names(repo: Path) -> str:
    out = subprocess.run(
        ["git", "--git-dir", str(repo), "log", "--all", "--name-only", "--pretty=format:"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def test_pairing_json_is_kept_out_of_a_git_remote(tmp_path):
    """pairing.json seals the recovery code. It must not enter git history."""
    bare = tmp_path / "remote.git"
    _bare(bare)
    a = make_home(tmp_path, "a")
    started = engine.pair_start(a, str(tmp_path / "work-a"), remote=str(bare), name="desk")
    local = tmp_path / "work-a" / "pairing.json"
    assert local.is_file()
    ignore = (tmp_path / "work-a" / ".gitignore").read_text(encoding="utf-8")
    assert any(line.strip() == "pairing.json" for line in ignore.splitlines())
    assert "pairing.json" not in _files(bare)
    engine.sync(a)
    assert "pairing.json" not in _files(bare)
    assert "pairing.json" not in _history_names(bare)
    probe = make_home(tmp_path, "probe")
    try:
        engine.pair_finish(probe, started["code"], str(bare), name="phone")
    except engine.HerdError as exc:
        msg = str(exc)
        assert "No pairing code" in msg
        assert "hermes sync join" in msg
    else:
        raise AssertionError("a short code over a git remote unwrapped the recovery code")
    from herd.util import read_json
    recovery = read_json(engine.data_dir(a) / "identity.json")["code"]
    b = make_home(tmp_path, "b")
    joined = engine.join(b, str(bare), recovery, name="laptop")
    assert joined["device"]["name"] == "laptop"
    assert "pairing.json" not in _files(bare)
    assert "pairing.json" not in _history_names(bare)
