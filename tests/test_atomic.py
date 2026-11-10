"""atomic_write has to survive a Windows peer holding the file open."""

from __future__ import annotations

import os
from pathlib import Path

from herd import util


def test_atomic_write_retries_while_the_target_is_held(tmp_path, monkeypatch):
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:          # a reader still has the old file open
            raise PermissionError(13, "in use")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    util.atomic_write(tmp_path / "device.json", b'{"ok":true}')

    assert calls["n"] == 3
    assert (tmp_path / "device.json").read_bytes() == b'{"ok":true}'


def test_atomic_write_gives_up_loudly(tmp_path, monkeypatch):
    def always(src, dst):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(os, "replace", always)
    try:
        util.atomic_write(Path(tmp_path) / "device.json", b"{}")
    except PermissionError:
        pass
    else:                              # pragma: no cover - the assertion is the point
        raise AssertionError("a permanently held file must not be reported as written")
