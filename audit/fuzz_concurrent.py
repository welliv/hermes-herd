"""Concurrency fuzz: three devices edit and sync at the same time, repeatedly.

Each round writes a random value on every device, then runs all three `sync`
calls as separate processes so their file locks and git-less store writes really
race. Afterwards everyone settles and the invariants are checked: convergence
when no conflict was recorded, unreadable objects, escapes outside the homes.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from herd import engine, yamlutil  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# `python -c` has no __file__, so the child's import path is passed in rather
# than discovered — otherwise every process dies with NameError and the harness
# reports it as a sync failure.
SCRIPT = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO)!r})\n"
    "from pathlib import Path\n"
    "from herd import engine\n"
    "engine.sync(Path(sys.argv[1]))\n"
)


def home(root: Path, name: str) -> Path:
    h = root / name
    (h / "skills").mkdir(parents=True, exist_ok=True)
    (h / "memories").mkdir(exist_ok=True)
    (h / "memories" / "MEMORY.md").write_text("start\n")
    (h / "config.yaml").write_text("model:\n  default: v0\n  provider: p\ndisplay:\n  skin: v0\n")
    return h


def value(h: Path) -> str:
    data = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    return str((data.get("display") or {}).get("skin"))


def set_value(h: Path, v: str) -> None:
    data = yamlutil.safe_load((h / "config.yaml").read_text()) or {}
    data.setdefault("display", {})["skin"] = v
    (h / "config.yaml").write_text(yamlutil.safe_dump(data))


def history(rng: random.Random, root: Path) -> tuple[bool, str]:
    homes = [home(root, n) for n in ("a", "b", "c")]
    engine.init(homes[0], str(root / "store"), name="a", sync_secrets=False)
    code = engine.open_context(homes[0]).identity["code"]
    for h, n in zip(homes[1:], ("b", "c")):
        engine.join(h, str(root / "store"), code, name=n)

    for round_no in range(6):
        for h in homes:
            set_value(h, f"{h.name}{round_no}")
        procs = [subprocess.Popen([sys.executable, "-c", SCRIPT, str(h)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for h in homes]
        results = [p.communicate() for p in procs]
        codes = [p.returncode for p in procs]
        if any(c != 0 for c in codes):
            err = next((err.strip().splitlines()[-1] for _out, err in results if err.strip()), "")
            return False, f"round {round_no}: sync exited {codes}: {err}"

    for _ in range(5):
        for h in homes:
            engine.sync(h)

    conflicts = sum(len(engine.conflicts(h)) for h in homes)
    problems = []
    if conflicts == 0:
        vals = {value(h) for h in homes}
        if len(vals) > 1:
            problems.append(f"no conflict but values differ: {vals}")

    ctx = engine.open_context(homes[0])
    for m in (root / "store" / "devices").glob("*.json"):
        for iid, row in (json.loads(m.read_text()).get("items") or {}).items():
            if row.get("oid"):
                try:
                    ctx.store.get(ctx.key, row["oid"])
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{iid}: {type(exc).__name__}")
    for p in root.rglob("*"):
        if p.is_file() and p.relative_to(root).parts[0] not in {"a", "b", "c", "store"}:
            problems.append(f"escaped file {p.relative_to(root)}")
    return not problems, "; ".join(problems[:3])


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    bad = 0
    for i in range(n):
        root = Path(tempfile.mkdtemp())
        try:
            ok, detail = history(rng, root)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            bad += 1
            print(f"FAIL concurrent history {i} (seed {seed}): {detail}")
        shutil.rmtree(root, ignore_errors=True)
    print(f"{n - bad}/{n} concurrent histories clean (seed {seed})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
