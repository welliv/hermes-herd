"""Randomised three-device state machine for herd.

Each history: three homes, one store, random edits/pushes/pulls over a small
value space. Then it settles everyone and checks the invariants that matter:

  * if no device recorded a conflict, all devices agree (convergence)
  * every store object a manifest names still exists and decrypts (integrity)
  * nothing was written outside a device's home (containment)
  * config is still valid YAML everywhere (no corruption)

Run: python fuzz.py [histories] [seed]
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from herd import engine, items, crypto, yamlutil  # noqa: E402

# Windows consoles default to cp1252 and blow up on the emoji these
# checks print. Force UTF-8 on the streams the harness writes to.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


KEYS = ["display.skin", "model.default"]          # synced
LOCAL = ["webapp.port"]                              # machine-bound, must never travel
VALUES = ["v0", "v1", "v2", "v3", "naïve 🎨", 'q"uote', "a b"]


def home(root: Path, name: str) -> Path:
    h = root / name
    (h / "skills").mkdir(parents=True, exist_ok=True)
    (h / "memories").mkdir(exist_ok=True)
    (h / "memories" / "MEMORY.md").write_text("start\n")
    (h / "config.yaml").write_text("model:\n  default: v0\n  provider: p\ndisplay:\n  skin: v0\nwebapp:\n  port: 9120\n")
    return h


def set_value(h: Path, dotted: str, value: str) -> None:
    data = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    node = data
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value
    (h / "config.yaml").write_text(yamlutil.safe_dump(data))


def get_value(h: Path, dotted: str):
    node = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def write_skill(h: Path, name: str, body: str) -> None:
    d = h / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n")


def read_skill(h: Path, name: str):
    p = h / "skills" / name / "SKILL.md"
    return p.read_text().splitlines()[-1] if p.exists() else None


def history(rng: random.Random, root: Path) -> tuple[bool, str]:
    homes = [home(root, n) for n in ("a", "b", "c")]
    engine.init(homes[0], str(root / "store"), name="a", sync_secrets=True)
    code = engine.open_context(homes[0]).identity["code"]
    for h, n in zip(homes[1:], ("b", "c")):
        engine.join(h, str(root / "store"), code, name=n, sync_secrets=True)

    trace = []
    ops = 14
    for _ in range(ops):
        h = rng.choice(homes)
        op = rng.choice(["cfg", "cfg", "skill", "skill", "memory", "push", "pull", "sync", "del"])
        try:
            if op == "cfg":
                set_value(h, rng.choice(KEYS), rng.choice(VALUES))
            elif op == "skill":
                write_skill(h, rng.choice(["s1", "s2"]), rng.choice(VALUES))
            elif op == "memory":
                (h / "memories" / "MEMORY.md").write_text(rng.choice(VALUES) + "\n")
            elif op == "push":
                engine.push(engine.open_context(h))
            elif op == "pull":
                engine.pull(engine.open_context(h))
            elif op == "sync":
                engine.sync(h)
            elif op == "del":
                name = rng.choice(["s1", "s2"])
                shutil.rmtree(h / "skills" / name, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            return False, f"op {op} raised {type(exc).__name__}: {exc}"
        if os.environ.get("TRACE"):
            try:
                ctx = engine.open_context(h)
                b = json.loads((ctx.data / "base.json").read_text())
                bi = (b.get("items") or {}).get("memory:agent") or {}
                pu = (b.get("pushed") or {}).get("memory:agent") or {}
                m = ctx.store.merged().get("memory:agent")
                f = h / "memories" / "MEMORY.md"
                sk = h / "skills" / "s2" / "SKILL.md"
                bsk = (b.get("items") or {}).get("skill:s2") or {}
                psk = (b.get("pushed") or {}).get("skill:s2") or {}
                msk = ctx.store.merged().get("skill:s2")
                fr = (json.loads((h / "plugin-data" / "herd" / "state.json").read_text()).get("frozen") or [])
                extra = (f" frozen={fr} s2={(sk.read_text().splitlines()[-1] if sk.exists() else None)!r}"
                         f" b={str(bsk.get('oid'))[:6]}/{bsk.get('rev')} p={str(psk.get('oid'))[:6]}/{psk.get('rev')}"
                         f" m={None if not msk else (msk.oid[:6], msk.rev, msk.deleted, msk.parent_rev)}")
                trace.append(extra + f" | {h.name}:{op} mem={(f.read_text().strip() if f.exists() else None)!r} "
                             f"base={str(bi.get('oid'))[:6]}/{bi.get('rev')} pushed={str(pu.get('oid'))[:6]}/{pu.get('rev')} "
                             f"merged={None if not m else (m.oid[:6], m.rev, m.parent_rev)}")
            except Exception as exc:  # noqa: BLE001
                trace.append(f"snap fail {exc}")

    # settle: everyone syncs until quiet
    # Fixed rounds, no early exit: `differs` is 0 for an item that has never been
    # pushed, so breaking on it would leave a new skill unpublished.
    for _ in range(6):
        for h in homes:
            engine.sync(h)

    conflicts = sum(len(engine.conflicts(h)) for h in homes)
    problems = []

    # integrity: every referenced object decrypts
    store = engine.open_context(homes[0]).store
    ctx = engine.open_context(homes[0])
    for m in (root / "store" / "devices").glob("*.json"):
        for iid, row in (json.loads(m.read_text()).get("items") or {}).items():
            if row.get("oid"):
                try:
                    store.get(ctx.key, row["oid"])
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{iid}: object unreadable ({type(exc).__name__})")

    # convergence when nobody reported a conflict
    if conflicts == 0:
        for key in KEYS:
            vals = {str(get_value(h, key)) for h in homes}
            if len(vals) > 1:
                problems.append(f"no conflict but {key} differs: {vals}")
        for name in ("s1", "s2"):
            vals = {read_skill(h, name) for h in homes}
            if len(vals) > 1:
                problems.append(f"no conflict but skill {name} differs: {vals}")
        mems = {(h / "memories" / "MEMORY.md").read_text() for h in homes}
        if len(mems) > 1:
            problems.append(f"no conflict but memory differs: {len(mems)} versions")

    # a machine-bound key never takes a peer's value
    for key in LOCAL:
        for h in homes:
            if str(get_value(h, key)) in VALUES:
                problems.append(f"{key} travelled: {get_value(h, key)}")

    # containment: nothing outside the three homes
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            if rel.parts[0] not in {"a", "b", "c", "store"}:
                problems.append(f"file outside the homes: {rel}")

    if problems:
        try:
            for h in homes:
                engine.sync(h)
            m = engine.open_context(homes[0]).store.merged().get("skill:s2")
            problems.append(f"after extra sync merged={None if not m else (m.oid[:6], m.rev, m.deleted)}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"extra sync raised {type(exc).__name__}: {exc}")
    if problems and os.environ.get("TRACE"):
        print("\n".join(trace[-20:]))
    return not problems, "; ".join(problems[:3])


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    bad = 0
    for i in range(n):
        root = Path(tempfile.mkdtemp())
        try:
            ok, detail = history(rng, root)
        except Exception:  # noqa: BLE001
            ok, detail = False, "harness raised:\n" + traceback.format_exc(limit=4)
        if not ok:
            bad += 1
            print(f"FAIL history {i} (seed {seed}): {detail}")
        shutil.rmtree(root, ignore_errors=True)
    print(f"{n - bad}/{n} histories clean (seed {seed})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
