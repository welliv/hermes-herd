"""Adversarial store fuzz: corrupt the store between syncs and check that the
plugin fails safely — no crash outside its own error types, no file outside the
home, config still valid YAML.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from herd import engine, store as store_mod, crypto, yamlutil  # noqa: E402

SAFE = (store_mod.StoreError, crypto.TamperedBlob, ValueError, KeyError, json.JSONDecodeError)


def home(root: Path, name: str) -> Path:
    h = root / name
    (h / "skills").mkdir(parents=True, exist_ok=True)
    (h / "memories").mkdir(exist_ok=True)
    (h / "memories" / "MEMORY.md").write_text("start\n")
    (h / "config.yaml").write_text("model:\n  default: v0\ndisplay:\n  skin: v0\n")
    return h


def objects(store: Path) -> list[Path]:
    return [p for p in (store / "objects").rglob("*") if p.is_file()]


def corrupt(rng: random.Random, root: Path) -> str:
    store = root / "store"
    what = rng.choice(["delete", "truncate", "flip", "forge", "manifest_id", "rev"])
    objs = objects(store)
    if what == "delete" and objs:
        rng.choice(objs).unlink()
        return "deleted an object"
    if what == "truncate" and objs:
        p = rng.choice(objs)
        p.write_bytes(p.read_bytes()[: rng.randint(1, 20)])
        return "truncated an object"
    if what == "flip" and objs:
        p = rng.choice(objs)
        raw = bytearray(p.read_bytes())
        raw[rng.randrange(len(raw))] ^= 0xFF
        p.write_bytes(bytes(raw))
        return "flipped a byte"
    if what in ("forge", "manifest_id") and objs:
        oid = rng.choice(objs).name
        item_id = rng.choice([
            "file:../../escape.txt", "skill:../../escape", "config", "env",
            "file:soul", "skill:s1", "future:item", "memory:agent",
        ])
        kind = rng.choice(["file", "skill", "config", "env", "memory", "future"])
        doc = {
            "version": 1,
            "device": {"id": "atk", "name": "atk", "platform": "linux", "created_at": 1},
            "clock": rng.randint(1, 10_000), "updated_at": 1,
            "items": {item_id: {"oid": oid, "kind": kind, "rev": rng.randint(1, 10_000),
                                "deleted": rng.random() < 0.2}},
        }
        (store / "devices" / "atk.json").write_text(json.dumps(doc))
        return f"forged {item_id} as {kind}"
    if what == "rev":
        for m in (store / "devices").glob("*.json"):
            doc = json.loads(m.read_text())
            for row in doc.get("items", {}).values():
                row["rev"] = rng.choice([0, 10**9, -1])
            m.write_text(json.dumps(doc))
        return "rewrote revs"
    return "no-op"


def history(rng: random.Random, root: Path) -> tuple[bool, str]:
    a = home(root, "a")
    engine.init(a, str(root / "store"), name="a", sync_secrets=True)
    b = home(root, "b")
    engine.join(b, str(root / "store"), engine.open_context(a).identity["code"], name="b", sync_secrets=True)

    notes = []
    for _ in range(6):
        note = corrupt(rng, root)
        notes.append(note)
        try:
            engine.pull(engine.open_context(b))
        except SAFE as exc:
            notes.append(f"surfaced {type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001
            return False, f"{note}: unsafe {type(exc).__name__}: {exc}"
        try:
            (b / "config.yaml").read_text()
            yamlutil.safe_load((b / "config.yaml").read_text())
        except Exception as exc:  # noqa: BLE001
            return False, f"{note}: config invalid after pull ({type(exc).__name__})"

    for p in root.rglob("*"):
        if p.is_file() and p.relative_to(root).parts[0] not in {"a", "b", "store"}:
            return False, f"escaped file after: {notes} — {p.relative_to(root)}"
    return True, "; ".join(notes)


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    bad = 0
    for i in range(n):
        root = Path(tempfile.mkdtemp())
        ok, detail = history(rng, root)
        if not ok:
            bad += 1
            print(f"FAIL {i} (seed {seed}): {detail}")
        shutil.rmtree(root, ignore_errors=True)
    print(f"{n - bad}/{n} corrupt-store histories safe (seed {seed})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
