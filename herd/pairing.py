"""Pairing: hand a second machine the herd without transcribing a 52-char key.

The recovery code is the root of trust and stays long; it is not the thing a
person should be typing on a phone-sized keyboard. Pairing puts a short-lived,
single-use code in front of it:

* `pair` writes ``pairing.json`` into the store — a payload sealed with a
  20-character code that expires in 15 minutes.
* The second machine reads that file, unseals the real key, joins, and the file
  is deleted. One code, one machine, one window.

The payload travels through the store folder, so both machines must be able to
reach that folder (a shared folder or a synced folder). It is not pushed to a
git remote: the sealed payload holds the recovery code, and a commit would
leave that ciphertext in git history after the file is deleted. For a git-only
second machine, use the recovery code (`hermes sync join <git-url> --code HERD-…`).
Nothing is sent anywhere else.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
GROUPS, GROUP_LEN = 4, 5
CODE_LEN = GROUPS * GROUP_LEN
DEFAULT_TTL = 15 * 60
_SCRYPT_N = 2 ** 14


class PairingError(ValueError):
    """The code is wrong, expired, or already used."""


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    return "-".join(raw[i : i + GROUP_LEN] for i in range(0, CODE_LEN, GROUP_LEN))


def normalize(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch in ALPHABET)


def _key(code: str, salt: bytes) -> bytes:
    cleaned = normalize(code)
    if len(cleaned) != CODE_LEN:
        raise PairingError(
            f"That pairing code is {len(cleaned)} characters; it should be {CODE_LEN}. "
            "Copy the whole line from the other machine."
        )
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=8, p=1).derive(cleaned.encode())


def seal(code: str, payload: dict, store_id: str, ttl: int = DEFAULT_TTL) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    expires_at = int(time.time()) + int(ttl)
    # The expiry is repeated inside the ciphertext: the copy outside is metadata
    # for the reader, and an attacker who edits it must not revive an old blob.
    body = json.dumps({**payload, "exp": expires_at}, separators=(",", ":")).encode()
    ct = AESGCM(_key(code, salt)).encrypt(nonce, body, store_id.encode())
    return {
        "version": 1,
        "store_id": store_id,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
        "expires_at": expires_at,
    }


def open_payload(code: str, doc: dict, store_id: str) -> dict:
    if int(doc.get("expires_at") or 0) < int(time.time()):
        raise PairingError(
            "That pairing code has expired. Run `hermes sync pair` on the other "
            "machine to make a new one."
        )
    if doc.get("store_id") != store_id:
        raise PairingError("That pairing code belongs to a different herd.")
    try:
        salt = base64.b64decode(doc["salt"])
        nonce = base64.b64decode(doc["nonce"])
        ct = base64.b64decode(doc["ct"])
        raw = AESGCM(_key(code, salt)).decrypt(nonce, ct, store_id.encode())
    except InvalidTag as exc:
        raise PairingError(
            "That pairing code does not open this herd. Check it for typos — the "
            "code expires after 15 minutes and works once."
        ) from exc
    payload = json.loads(raw.decode())
    if int(payload.get("exp") or 0) < int(time.time()):
        raise PairingError("That pairing code has expired. Run `hermes sync pair` again.")
    return payload
