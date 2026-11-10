#!/usr/bin/env python3
"""Fail if a relative link in the docs points at nothing.

Reviewers read the README first; a 404 in it is a broken first impression, and
renames break links silently. External links are not fetched — CI should not
depend on the network being up.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_GLOBS = ("*.md", "docs/*.md", "demo/*.sh")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")


def docs() -> list[Path]:
    out: list[Path] = []
    for pattern in DOC_GLOBS:
        out.extend(sorted(ROOT.glob(pattern)))
    return [p for p in out if p.is_file()]


def main() -> int:
    bad: list[str] = []
    for doc in docs():
        for m in LINK.finditer(doc.read_text(encoding="utf-8", errors="ignore")):
            target = m.group(1)
            if target.startswith("#") or SCHEME.match(target):
                continue
            path = (doc.parent / target.split("#", 1)[0]).resolve()
            if not path.exists():
                bad.append(f"{doc.relative_to(ROOT)} → {target}")

    if bad:
        print("broken relative links:")
        for row in bad:
            print(f"  {row}")
        return 1
    print(f"links ok — {len(docs())} documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
