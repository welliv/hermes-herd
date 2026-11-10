#!/usr/bin/env python3
"""Install the package in a clean venv, twice.

``pip install -e .`` used to die in setuptools with "Multiple top-level
packages discovered in a flat-layout: ['herd', 'demo', 'audit']".
``hermes plugins validate --install-deps`` reported success anyway, because
it does not notice a failed editable install. This script does.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python(env: Path) -> Path:
    if sys.platform == "win32":
        return env / "Scripts" / "python.exe"
    return env / "bin" / "python"


def install(mode: str) -> None:
    env = Path(tempfile.mkdtemp(prefix=f"herd-{mode}-")) / "venv"
    venv.create(env, with_pip=True, clear=True)
    py = _python(env)
    cmd = [str(py), "-m", "pip", "install"]
    if mode == "editable":
        cmd.append("-e")
    cmd.append(str(ROOT))
    subprocess.run(cmd, check=True)
    probe = (
        "import herd, herd.engine, herd.hooks, herd.tools\n"
        "import importlib.util\n"
        "from pathlib import Path\n"
        f"path = Path({str(ROOT)!r}) / '__init__.py'\n"
        "spec = importlib.util.spec_from_file_location('herd_plugin', path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "assert callable(mod.register)\n"
        "print(mode, herd.__version__)\n"
    ).replace("mode", repr(mode), 1)
    subprocess.run([str(py), "-c", probe], check=True)


def main() -> int:
    install("regular")
    install("editable")
    print("install ok — regular and editable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
