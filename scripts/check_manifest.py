"""Admission-lite: the manifest parses and still names the tools it ships.

Runs on every OS in CI, so it avoids shell heredocs (PowerShell has none) and
imports nothing the plugin itself does not already require.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    doc = YAML(typ="safe").load((root / "plugin.yaml").read_text(encoding="utf-8"))
    assert doc["name"] == "herd", doc.get("name")
    assert doc["provides_tools"], "no tools declared"
    assert doc.get("requires_hermes"), "requires_hermes missing"
    print("plugin.yaml ok:", doc["name"], doc["version"], doc["requires_hermes"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
