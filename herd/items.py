"""What a device actually holds, and how each piece is packed for the store.

An item is the smallest thing that can move on its own: the config, the env
subset, one skill, one memory file. Item ids are stable across devices because
they are derived from the thing itself, never from a path on disk.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import platform as _platform
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlutil
from .policy import Policy
from .util import atomic_write


@dataclass
class LocalItem:
    item_id: str
    kind: str  # config, env, skill, memory, file, cron
    payload: bytes
    mtime: float = 0.0
    extra: dict = field(default_factory=dict)  # live dict for config, platform list for skills

    @property
    def size(self) -> int:
        return len(self.payload)


def current_platform() -> str:
    name = _platform.system().lower()
    return {"darwin": "macos", "windows": "windows"}.get(name, "linux")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ── config ───────────────────────────────────────────────────────────────────
def scrub(conf: Any, policy: Policy, prefix: str = "") -> Any:
    """Drop device-local keys before the config ever leaves this machine.

    Keeping the shape matters: an empty mapping still tells the remote that the
    section exists, while dropping a local-only scalar leaves no trace of it.
    """
    if isinstance(conf, dict):
        out = {}
        for key, value in conf.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if policy.is_local_only(path):
                continue
            if isinstance(value, dict):
                child = scrub(value, policy, path)
                if child:
                    out[key] = child
            else:
                out[key] = value
        return out
    return conf


def _read_config(home: Path) -> tuple[str, dict]:
    path = home / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", {}
    try:
        data = yamlutil.safe_load(text) or {}
    except Exception:
        # A corrupt config is not something to sync over someone else's good copy.
        raise ValueError(f"{path} does not parse; fix it before syncing.")
    return text, data if isinstance(data, dict) else {}


# ── env ──────────────────────────────────────────────────────────────────────
def parse_env(text: str) -> dict[str, str]:
    """Parse simple KEY=VALUE lines; ignore comments and anything unusual.

    We deliberately do not use a dotenv library: the file we write back must
    keep every line we did not touch byte-for-byte.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() and not key.isidentifier():
            continue
        out[key] = _unquote_env(value.strip())
    return out


def _unquote_env(value: str) -> str:
    """Undo exactly what Hermes's writer quotes: double quotes escape \\" and \\\\."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        quoted, out, i = value[1:-1], [], 0
        while i < len(quoted):
            escaped = quoted[i] == "\\" and quoted[i + 1:i + 2] in ('"', "\\")
            out.append(quoted[i + 1] if escaped else quoted[i])
            i += 2 if escaped else 1
        return "".join(out)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def render_env(text: str, updates: dict[str, str], removals: set[str]) -> str:
    """Rewrite only the lines that change; append new keys at the end."""
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in removals:
                continue
            if key in updates:
                out.append(f"{key}={_quote_env(updates[key])}")
                seen.add(key)
                continue
        out.append(raw)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={_quote_env(value)}")
    return "\n".join(out) + ("\n" if out else "")


def _quote_env(value: str) -> str:
    """Quote the way Hermes does, so a value written here parses back unchanged.

    Same rule as ``hermes_cli.config._quote_env_value``: any whitespace, ``#`` or
    a quote character forces double quotes; backslashes and double quotes are
    escaped inside them.
    """
    if value == "":
        return value
    if not ("#" in value or '"' in value or "'" in value or any(c.isspace() for c in value)):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' 


# ── skills ───────────────────────────────────────────────────────────────────
def skill_platforms(skill_dir: Path) -> list[str]:
    """Read the `platforms:` list from SKILL.md frontmatter, if it has one."""
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    try:
        meta = yamlutil.safe_load(text[3:end]) or {}
    except Exception:
        return []
    raw = meta.get("platforms") if isinstance(meta, dict) else None
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return [str(p).strip().lower() for p in raw if str(p).strip()]


def skill_root(home: Path) -> Path:
    return home / "skills"


def iter_skills(home: Path) -> dict[str, Path]:
    """Map skill name -> directory, for every SKILL.md under skills/."""
    root = skill_root(home)
    found: dict[str, Path] = {}
    if not root.exists():
        return found
    for skill_md in root.rglob("SKILL.md"):
        d = skill_md.parent
        if any(part.startswith(".") for part in d.relative_to(root).parts):
            continue
        found[d.name] = d
    return found


_SEAL = b"HERD1\n"


def seal_item(item_id: str, kind: str, body: bytes) -> bytes:
    """Name the item inside its own payload.

    A sealed blob can then only be applied as the item it was written for: a
    manifest that points the config item at the env blob fails here instead of
    writing one kind of file as another.
    """
    meta = json.dumps({"id": item_id, "kind": kind}, sort_keys=True, separators=(",", ":")).encode()
    return _SEAL + meta + b"\n" + body


def open_item(blob: bytes) -> tuple[str, str, bytes]:
    if not blob.startswith(_SEAL):
        raise ValueError("payload is not sealed by this plugin")
    meta, _, body = blob[len(_SEAL):].partition(b"\n")
    info = json.loads(meta.decode())
    return str(info["id"]), str(info["kind"]), body


def skill_platforms_from_blob(blob: bytes) -> list[str]:
    """Read SKILL.md's platforms: out of the archive without unpacking it."""
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.name == "SKILL.md"), None)
            if member is None:
                return []
            text = tar.extractfile(member).read().decode("utf-8", "ignore")
    except Exception:
        return []
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    try:
        meta = yamlutil.safe_load(text[3:end]) or {}
    except Exception:
        return []
    raw = meta.get("platforms") if isinstance(meta, dict) else None
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return [str(p).strip().lower() for p in raw if str(p).strip()]


def pack_dir(path: Path) -> bytes:
    """Deterministic tar.gz: same content in, same bytes out, on any machine."""
    buf = io.BytesIO()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    # gzip stamps the current time into its header by default, which would make
    # the same skill hash differently on two machines. Pin it to zero.
    gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
    with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in files:
            rel = f.relative_to(path).as_posix()
            info = tarfile.TarInfo(name=rel)
            data = f.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if os.access(f, os.X_OK) else 0o644
            tar.addfile(info, io.BytesIO(data))
    gz.close()
    return buf.getvalue()


def unpack_dir(blob: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError("skill archive contains an unsafe path")
            if not (member.isfile() or member.isdir()):
                continue
            target = dest / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member)
            if data is not None:
                atomic_write(target, data.read(), mode=0o644)


# ── scan ─────────────────────────────────────────────────────────────────────
MEMORY_FILES = {"memory:agent": "MEMORY.md", "memory:user": "USER.md"}


def scan(home: Path, policy: Policy, include_cron: bool = False) -> dict[str, LocalItem]:
    """Read every syncable item off this device, applying the policy as we go."""
    items: dict[str, LocalItem] = {}

    text, conf = _read_config(home)
    items["config"] = LocalItem(
        item_id="config",
        kind="config",
        payload=canonical(scrub(conf, policy)),
        mtime=(home / "config.yaml").stat().st_mtime if (home / "config.yaml").exists() else 0.0,
        extra={"live": conf, "text": text},
    )

    env_path = home / ".env"
    if policy.sync_secrets and env_path.exists():
        env = {k: v for k, v in parse_env(env_path.read_text(encoding="utf-8", errors="ignore")).items()
               if policy.secret_allowed(k)}
        if env:
            items["env"] = LocalItem(
                item_id="env",
                kind="env",
                payload=canonical(env),
                mtime=env_path.stat().st_mtime,
                extra={"live": env},
            )

    for item_id, filename in MEMORY_FILES.items():
        path = home / "memories" / filename
        if path.exists():
            items[item_id] = LocalItem(
                item_id=item_id, kind="memory", payload=path.read_bytes(), mtime=path.stat().st_mtime
            )

    soul = home / "SOUL.md"
    if soul.exists():
        items["file:soul"] = LocalItem(
            item_id="file:soul", kind="file", payload=soul.read_bytes(), mtime=soul.stat().st_mtime
        )

    here = current_platform()
    for name, path in iter_skills(home).items():
        if not policy.skill_allowed(name):
            continue
        platforms = skill_platforms(path)
        if platforms and here not in platforms:
            # The other machine would install a skill it cannot run.
            continue
        items[f"skill:{name}"] = LocalItem(
            item_id=f"skill:{name}",
            kind="skill",
            payload=pack_dir(path),
            mtime=max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0.0),
            extra={"platforms": platforms, "name": name},
        )

    if include_cron:
        jobs = home / "cron" / "jobs.json"
        if jobs.exists():
            items["file:cron"] = LocalItem(
                item_id="file:cron", kind="file", payload=jobs.read_bytes(), mtime=jobs.stat().st_mtime
            )

    for item in items.values():
        item.payload = seal_item(item.item_id, item.kind, item.payload)
    return items


def item_digest(item: LocalItem) -> str:
    return hashlib.sha256(item.payload).hexdigest()[:12]
