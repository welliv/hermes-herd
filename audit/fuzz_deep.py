"""Harder randomised histories: four devices, deletions, secrets, and the
invariant that divergence is always explained by a recorded conflict.

Run: python fuzz2.py [histories] [seed]
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
from herd import engine, items, yamlutil  # noqa: E402

# Windows consoles default to cp1252 and blow up on the emoji these
# checks print. Force UTF-8 on the streams the harness writes to.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


SYNCED = ["display.skin", "model.default"]
VALUES = ["v0", "v1", "v2", "naïve 🎨", 'q"uote', "a b", "x\ty"]


def home(root: Path, name: str) -> Path:
    h = root / name
    (h / "skills").mkdir(parents=True, exist_ok=True)
    (h / "memories").mkdir(exist_ok=True)
    (h / "memories" / "MEMORY.md").write_text("start\n")
    (h / "config.yaml").write_text("model:\n  default: v0\n  provider: p\ndisplay:\n  skin: v0\nwebapp:\n  port: 9120\n")
    (h / ".env").write_text("OPENAI_API_KEY=sk-0\n")
    return h


def set_dotted(h: Path, dotted: str, value) -> None:
    data = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    node = data
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value
    (h / "config.yaml").write_text(yamlutil.safe_dump(data))


def get_dotted(h: Path, dotted: str):
    try:
        node = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    except Exception:
        return "<invalid yaml>"
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def env_of(h: Path) -> dict:
    p = h / ".env"
    return items.parse_env(p.read_text()) if p.exists() else {}



def _snap(h: Path) -> str:
    try:
        ctx = engine.open_context(h)
        b = json.loads((ctx.data / "base.json").read_text())
        out = []
        for item in ("skill:s1", "skill:s2"):
            bi = (b.get("items") or {}).get(item) or {}
            pu = (b.get("pushed") or {}).get(item) or {}
            m = ctx.store.merged().get(item)
            f = h / "skills" / item.split(":")[1] / "SKILL.md"
            out.append(f"{item[-2:]} local={(f.read_text().splitlines()[-1] if f.exists() else None)!r} "
                       f"base={str(bi.get('oid'))[:6]}/{bi.get('rev')} pushed={str(pu.get('oid'))[:6]}/{pu.get('rev')} "
                       f"merged={None if not m else (m.oid[:6], m.rev, m.deleted, m.parent_rev)}")
        return " | ".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"[snap failed: {type(exc).__name__}]"

def history(rng: random.Random, root: Path) -> tuple[bool, str]:
    names = ["a", "b", "c", "d"][: rng.choice([3, 4])]
    homes = [home(root, n) for n in names]
    engine.init(homes[0], str(root / "store"), name=names[0], sync_secrets=True)
    code = engine.open_context(homes[0]).identity["code"]
    for h, n in zip(homes[1:], names[1:]):
        engine.join(h, str(root / "store"), code, name=n, sync_secrets=True)

    trace = []
    for _ in range(rng.randint(10, 20)):
        h = rng.choice(homes)
        op = rng.choice(["cfg", "cfg", "del", "skill", "skill", "delskill", "memory", "env",
                         "push", "pull", "sync", "sync"])
        try:
            if op == "cfg":
                set_dotted(h, rng.choice(SYNCED), rng.choice(VALUES))
            elif op == "del":
                set_dotted(h, rng.choice(SYNCED), None)
            elif op == "skill":
                d = h / "skills" / rng.choice(["s1", "s2"])
                d.mkdir(exist_ok=True)
                (d / "SKILL.md").write_text(f"---\nname: {d.name}\n---\n{rng.choice(VALUES)}\n")
            elif op == "delskill":
                shutil.rmtree(h / "skills" / rng.choice(["s1", "s2"]), ignore_errors=True)
            elif op == "memory":
                (h / "memories" / "MEMORY.md").write_text(rng.choice(VALUES) + "\n")
            elif op == "env":
                (h / ".env").write_text(f"OPENAI_API_KEY=sk-{rng.choice(VALUES)}\n")
            elif op == "push":
                engine.push(engine.open_context(h))
            elif op == "pull":
                engine.pull(engine.open_context(h))
            elif op == "sync":
                engine.sync(h)
            trace.append(f"{h.name}:{op}")
            if os.environ.get("TRACE"):
                trace[-1] += " " + _snap(h)
        except Exception as exc:  # noqa: BLE001
            return False, f"op {op} raised {type(exc).__name__}: {exc}"

    skipped_notes = []
    for round_no in range(8):
        for h in homes:
            r = engine.sync(h)
            if os.environ.get("TRACE"):
                trace.append(f"settle{round_no}:{h.name}:sync {_snap(h)}")
            for phase in ("first", "second"):
                for note in (r.get(phase) or {}).get("skipped", []) or []:
                    if "s2" in str(note):
                        skipped_notes.append(f"{h.name}:{note}")

    problems = []
    conflicts = sum(len(engine.conflicts(h)) for h in homes)

    # every synced value that still differs must be explained by a conflict
    for key in SYNCED:
        vals = {str(get_dotted(h, key)) for h in homes}
        if "<invalid yaml>" in vals:
            problems.append(f"{key}: config became invalid YAML")
        elif len(vals) > 1 and conflicts == 0:
            problems.append(f"{key} differs with no conflict: {vals}")
    for name in ("s1", "s2"):
        bodies = set()
        for h in homes:
            p = h / "skills" / name / "SKILL.md"
            bodies.add(p.read_text().splitlines()[-1] if p.exists() else None)
        if len(bodies) > 1 and conflicts == 0:
            problems.append(f"skill {name} differs with no conflict")
    envs = {json.dumps(env_of(h), sort_keys=True) for h in homes}
    if len(envs) > 1 and conflicts == 0:
        problems.append(f".env differs with no conflict: {envs}")

    # machine-bound key never travels
    for h in homes:
        if str(get_dotted(h, "webapp.port")) != "9120":
            problems.append(f"webapp.port travelled: {get_dotted(h, 'webapp.port')}")

    # integrity
    ctx = engine.open_context(homes[0])
    for m in (root / "store" / "devices").glob("*.json"):
        for iid, row in (json.loads(m.read_text()).get("items") or {}).items():
            if row.get("oid"):
                try:
                    ctx.store.get(ctx.key, row["oid"])
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{iid}: unreadable ({type(exc).__name__})")

    if problems:
        try:
            m = engine.open_context(homes[0]).store.merged().get("skill:s2")
            m1 = engine.open_context(homes[0]).store.merged().get("skill:s1")
            problems.append(f"merged s1={None if not m1 else (m1.oid[:8], m1.rev, m1.deleted, m1.parent_rev)}")
            problems.append(f"merged s2={None if not m else (m.oid[:8], m.rev, m.deleted, m.parent_rev, m.parent_dev[:4])}")
            for h in homes:
                f = h / "skills" / "s2" / "SKILL.md"
                problems.append(f"{h.name}: conflicts={len(engine.conflicts(h))} s2={(f.read_text().splitlines()[-1] if f.exists() else None)!r}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"diag failed: {exc}")
        try:
            problems.append(f"skipnotes={skipped_notes[-4:]}")
            orig = engine._decision
            seen = []
            def spy(l, b, pr, e):
                r = orig(l, b, pr, e)
                if e.item_id == "skill:s2":
                    seen.append(f"decision={r} local={str(l)[:8]} base={str((b or {}).get('oid'))[:8]} "
                                f"pushed={str((pr or {}).get('oid'))[:8]} parent=({e.parent_rev},{e.parent_dev[:4]})")
                return r
            engine._decision = spy
            try:
                rr = engine.pull(engine.open_context(homes[0]))
            finally:
                engine._decision = orig
            problems.append(f"replay applied={rr['applied']} skipped={[x for x in rr.get('skipped', []) if 's2' in str(x)][:2]}")
            problems.extend(seen)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"replay failed: {exc}")

    # containment
    for p in root.rglob("*"):
        if p.is_file() and p.relative_to(root).parts[0] not in set(names) | {"store"}:
            problems.append(f"escaped file {p.relative_to(root)}")

    if problems and os.environ.get("TRACE"):
        print("\n".join(trace[-18:]))
    return not problems, "; ".join(problems) + (" | ops=" + " ".join(trace) if problems else "")


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    bad = 0
    for i in range(n):
        root = Path(tempfile.mkdtemp())
        try:
            ok, detail = history(rng, root)
        except Exception:  # noqa: BLE001
            ok, detail = False, "harness: " + traceback.format_exc(limit=3).replace("\n", " | ")
        if not ok:
            bad += 1
            print(f"FAIL {i} (seed {seed}): {detail}")
        shutil.rmtree(root, ignore_errors=True)
    print(f"{n - bad}/{n} clean (seed {seed})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
