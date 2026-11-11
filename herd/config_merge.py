"""Three-way merge for `config.yaml`, then re-application that keeps comments.

A two-way diff would have to guess whether a difference is an edit or a
deletion. Storing the last common snapshot gives a real base, so every key is
decided by one of four unambiguous cases:

    local == remote            keep it
    local == base              take remote          (only they changed it)
    remote == base             keep local           (only you changed it)
    all three differ           conflict, recorded, local wins by default

Keys covered by the policy's local-only rules never even enter the remote side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import credentials, yamlutil

MISSING = object()

# Schema bookkeeping, not preference: always keep the newest number so a pull
# never looks like a downgrade to Hermes' migration code.
_VERSION_KEY = "_config_version"


@dataclass
class Conflict:
    path: str
    base: Any
    local: Any
    remote: Any
    resolution: str  # "local" | "remote"
    reason: str = "both-edited"

    def to_json(self) -> dict:
        def plain(v):
            return None if v is MISSING else v

        return {
            "path": self.path,
            # Conflicts are printed and saved on disk. Credential values are
            # already in config.yaml; they do not need a second copy here.
            "base": plain(credentials.strip(self.base, self.path)),
            "local": plain(credentials.strip(self.local, self.path)),
            "remote": plain(credentials.strip(self.remote, self.path)),
            "kept": self.resolution,
            "reason": self.reason,
        }


@dataclass
class MergeResult:
    merged: dict
    conflicts: list[Conflict] = field(default_factory=list)
    remote_applied: list[str] = field(default_factory=list)
    local_kept: list[str] = field(default_factory=list)
    local_only_kept: list[str] = field(default_factory=list)
    changed: bool = False


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else str(key)


def _blocked(path: str, is_local_only: Callable[[str], bool]) -> bool:
    """Local-only policy, plus credentials, which `shared` cannot lift."""
    return bool(path) and (is_local_only(path) or credentials.is_credential_path(path))


def _stripped(value: Any, path: str) -> Any:
    if value is MISSING:
        return MISSING
    return credentials.strip(value, path)


def _adopt(remote: Any, local: Any, path: str) -> Any:
    """Take *remote*, then put this machine's credentials back.

    A missing or null remote does not delete a value that holds a credential.
    """
    if local is MISSING:
        return MISSING if remote is MISSING else credentials.strip(remote, path)
    if remote is MISSING:
        return local if credentials.contains(local, path) else MISSING
    return credentials.preserve(remote, local, path)


def merge(
    base: dict | None,
    local: dict | None,
    remote: dict | None,
    is_local_only: Callable[[str], bool] = lambda _p: False,
    prefer: str = "local",
) -> MergeResult:
    result = MergeResult(merged={})
    base = base or {}
    local = local or {}
    remote = remote or {}

    def walk(b, l, r, path: str):
        if _blocked(path, is_local_only):
            # Device-local: the remote value is never adopted, even when it is
            # the only side that changed. A missing local value is not filled
            # in from the peer, so a credential cannot be injected either.
            if l is not MISSING:
                result.local_only_kept.append(path)
            return l
        # Recurse whenever both sides are mappings, even if one side equals the
        # base: a parent that matches at the object level can still contain a
        # device-local child that must not be overwritten.
        if isinstance(l, dict) and isinstance(r, dict):
            bd = b if isinstance(b, dict) else {}
            out = {}
            for key in sorted(set(bd) | set(l) | set(r)):
                value = walk(bd.get(key, MISSING), l.get(key, MISSING), r.get(key, MISSING), _join(path, key))
                if value is not MISSING:
                    out[key] = value
            return out
        # Lists can hold credentials (a custom provider's api_key) that never
        # travel. Compare without them, and keep this machine's when the
        # remote list is taken. A null or a shape change cannot drop them.
        lv, rv, bv = _stripped(l, path), _stripped(r, path), _stripped(b, path)
        if l is r or lv == rv:
            return l
        if lv == bv:
            if path:
                result.remote_applied.append(path)
            adopted = _adopt(r, l, path)
            if adopted is not MISSING and path and credentials.contains(l, path) and adopted == l:
                result.local_only_kept.append(path)
            return adopted
        if rv == bv:
            if path and l is not MISSING:
                result.local_kept.append(path)
            return l
        # Both sides changed this key to different values.
        resolution = prefer if prefer in {"local", "remote"} else "local"
        if _blocked(path, is_local_only):
            resolution = "local"
        result.conflicts.append(
            Conflict(
                path=path,
                base=b,
                local=l,
                remote=r,
                resolution=resolution,
                reason="local-only" if _blocked(path, is_local_only) else "both-edited",
            )
        )
        if resolution == "local":
            return l
        return _adopt(r, l, path)

    for key in sorted(set(base) | set(local) | set(remote)):
        if key == _VERSION_KEY:
            merged_version = max(
                [v for v in (base.get(key), local.get(key), remote.get(key)) if isinstance(v, int)],
                default=local.get(key, base.get(key, remote.get(key))),
            )
            if merged_version is not None:
                result.merged[key] = merged_version
            continue
        if _blocked(key, is_local_only):
            if key in local:
                result.merged[key] = local[key]
                result.local_only_kept.append(key)
            continue
        value = walk(base.get(key, MISSING), local.get(key, MISSING), remote.get(key, MISSING), key)
        if value is not MISSING:
            result.merged[key] = value

    # A local-only subtree must survive verbatim, including keys the remote invented.
    for key in local:
        if _blocked(key, is_local_only) and key not in result.merged and key != _VERSION_KEY:
            result.merged[key] = local[key]
            result.local_only_kept.append(key)

    result.changed = result.merged != local
    return result


def _sync_doc(target, source: dict) -> None:
    for key in list(target.keys()):
        if key not in source:
            del target[key]
    for key, value in source.items():
        existing = target.get(key, MISSING)
        if isinstance(value, dict) and isinstance(existing, dict):
            _sync_doc(existing, value)
        elif isinstance(value, dict):
            target[key] = dict(value)
        else:
            target[key] = value


def render(local_text: str, merged: dict) -> tuple[str, bool]:
    """Apply *merged* onto the local file so comments and ordering survive.

    Returns (text, comments_preserved). Falls back to a clean dump when the
    round-trip result does not parse back to exactly the merged mapping — a
    comment is never worth a wrong value.
    """
    if local_text.strip():
        try:
            yaml, doc = yamlutil.roundtrip(local_text)
            if isinstance(doc, dict):
                _sync_doc(doc, merged)
                out = yamlutil.dump_roundtrip(yaml, doc)
                if yamlutil.safe_load(out) == merged:
                    return out, True
        except Exception:
            pass
    return yamlutil.safe_dump(merged), False
