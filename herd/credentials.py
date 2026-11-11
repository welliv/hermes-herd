"""Credentials inside config.yaml stay on the machine that has them.

Hermes keeps provider keys in ``.env``, but a config file can still carry one:
``model.api_key``, a ``custom_providers`` entry's ``api_key``, an MCP server's
``env`` or ``headers``. The policy's prefix rules cannot see those, because they
sit under keys that should otherwise follow you. So this is a rule about key
*names*, applied at any depth, lists included, in both directions:

* outgoing, the key is dropped before the config is packed;
* incoming, a peer's value for it is ignored, so a peer can neither inject,
  overwrite, nor delete one;
* on merge, this machine's own value is put back where it was.

A key is a credential when its name, with ``-`` read as ``_`` and camelCase
read as snake_case, is one of ``CREDENTIAL_NAMES`` or ends with one of
``CREDENTIAL_SUFFIXES``. So ``api_key``, ``API_KEY``, ``apiKey``,
``OPENAI_API_KEY``, ``X-Api-Key``, ``accessToken``, ``client_secret``,
``db_password`` and ``Authorization`` all match, while ``api_key_env`` (the
*name* of an env var), ``max_tokens``, ``password_store`` and ``redact_secrets``
do not. ``mcp_servers.<name>.env`` and ``mcp_servers.<name>.headers`` stay
local whole, including when the section name is ``MCP-Servers`` or the leaf is
``Headers``.

These rules are not part of the user-editable policy: ``shared:`` cannot lift
them.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any

CREDENTIAL_NAMES: frozenset[str] = frozenset({
    "api_key", "apikey", "token", "secret", "password", "passwd", "authorization",
    "password_hash", "private_key", "secret_key", "cookie",
})
CREDENTIAL_SUFFIXES: tuple[str, ...] = (
    "_api_key", "_apikey", "_token", "_secret", "_password", "_passwd",
    "_private_key", "_secret_key", "_authorization",
)
# Whole subtrees: every value in them is a credential or a header that carries one.
# Matching is case-insensitive and treats "-" as "_". A server name that itself
# contains a dot still counts: any `env` or `headers` component under mcp_servers.
CREDENTIAL_PATHS: tuple[str, ...] = (
    "mcp_servers.*.env",
    "mcp_servers.*.headers",
)

_MCP_ROOT = "mcp_servers"
_MCP_LEAVES = frozenset({"env", "headers"})


def _norm_key(key: Any) -> str:
    """Fold case, hyphens and camelCase so ``apiKey`` and ``X-Api-Key`` match."""
    text = str(key).strip().replace("-", "_")
    if not text:
        return ""
    if text.lower() == text or text.upper() == text:
        return text.lower()
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    snake = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", snake)
    return snake.lower()


def is_credential_key(key: Any) -> bool:
    name = _norm_key(key)
    return name in CREDENTIAL_NAMES or name.endswith(CREDENTIAL_SUFFIXES)


def is_credential_path(path: str) -> bool:
    """True for a dotted config path that must never leave or enter this machine."""
    if not path:
        return False
    raw = [p for p in str(path).split(".") if p]
    if any(is_credential_key(p) for p in raw):
        return True
    parts = [_norm_key(p) for p in raw]
    if parts and parts[0] == _MCP_ROOT and _MCP_LEAVES.intersection(parts[1:]):
        return True
    for pattern in CREDENTIAL_PATHS:
        depth = pattern.count(".") + 1
        if len(parts) >= depth and fnmatchcase(".".join(parts[:depth]), pattern):
            return True
    return False


def _child(path: str, key: Any) -> str:
    part = str(key)
    return f"{path}.{part}" if path else part


def strip(value: Any, path: str = "") -> Any:
    """Copy of *value* with every credential removed, at any depth.

    Credential-named keys are removed everywhere. ``mcp_servers.*.env`` and
    ``mcp_servers.*.headers`` are removed whole. Lists keep their shape so a
    provider entry can still be matched by name.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            child = _child(path, key)
            if is_credential_key(key) or is_credential_path(child):
                continue
            out[key] = strip(item, child)
        return out
    if isinstance(value, list):
        return [strip(item, path) for item in value]
    return value


def contains(value: Any, path: str = "") -> bool:
    """True when *value* holds a credential this machine must not lose."""
    if path and is_credential_path(path):
        return True
    if isinstance(value, dict):
        for key, item in value.items():
            child = _child(path, key)
            if is_credential_key(key) or is_credential_path(child) or contains(item, child):
                return True
        return False
    if isinstance(value, list):
        return any(contains(item, path) for item in value)
    return False


def _match_key(item: dict) -> tuple[str, Any] | None:
    for field in ("name", "id", "key", "base_url", "url"):
        if field in item and not isinstance(item[field], (dict, list)):
            return field, item[field]
    return None


def _find_old(item: Any, old: list, matched: set[int], index: int) -> int | None:
    if isinstance(item, dict):
        ident = _match_key(item)
        if ident is not None:
            for i, candidate in enumerate(old):
                if i in matched or not isinstance(candidate, dict):
                    continue
                if candidate.get(ident[0]) == ident[1]:
                    return i
            return None
    if index < len(old) and index not in matched:
        return index
    return None


def restore(new: Any, old: Any, path: str = "") -> Any:
    """Put this machine's credentials (from *old*) back into *new*.

    Dicts are matched by key. List entries are matched by their ``name`` (or
    ``id``, ``key``, ``base_url``, ``url``) when both sides have one, otherwise
    by position. A peer value for a credential is never kept. An entry the peer
    dropped is kept when it still holds a credential, so a poisoned empty list
    cannot delete one. Nothing else is invented.
    """
    if isinstance(new, dict) and isinstance(old, dict):
        out = strip(new, path)
        for key, value in old.items():
            child = _child(path, key)
            if is_credential_key(key) or is_credential_path(child):
                out[key] = value
            elif key in out:
                out[key] = restore(out[key], value, child)
        return out
    if isinstance(new, list) and isinstance(old, list):
        out = []
        matched: set[int] = set()
        for index, item in enumerate(new):
            found = _find_old(item, old, matched, index)
            if found is None:
                out.append(strip(item, path))
                continue
            matched.add(found)
            out.append(restore(item, old[found], path))
        for index, item in enumerate(old):
            if index not in matched and contains(item, path):
                out.append(item)
        return out
    return strip(new, path) if isinstance(new, (dict, list)) else new


def preserve(new: Any, old: Any, path: str = "") -> Any:
    """*new* with this machine's credentials intact.

    ``None`` (a peer set the value to null) does not delete a credential.
    Replacing a mapping or list with a different shape does not either: the
    local container is kept so the secret still has somewhere to live.
    """
    if old is None:
        return None if new is None else strip(new, path)
    if new is None:
        return old if contains(old, path) else None
    if isinstance(old, (dict, list)) and not isinstance(new, type(old)) and contains(old, path):
        return old
    return restore(new, old, path)
