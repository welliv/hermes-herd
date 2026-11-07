"""YAML 1.1, matching how Hermes itself reads `config.yaml`.

Hermes treats bare `y/n/on/off` as booleans, so a merge that used YAML 1.2 rules
would silently change values on the way back out. This module reproduces the
same resolver locally instead of importing a private Hermes helper: plugins may
only lean on public surfaces, and a rename upstream must not break a sync.
"""

from __future__ import annotations

from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.resolver import VersionedResolver

WIDTH = 2 ** 31 - 1


class _Yaml11Resolver(VersionedResolver):
    """YAML 1.1 scalars without emitting a ``%YAML`` directive."""

    @property
    def processing_version(self) -> tuple[int, int]:
        return (1, 1)


def _yaml(typ: str) -> YAML:
    yaml = YAML(typ=typ, pure=True)
    yaml.Resolver = _Yaml11Resolver
    yaml.allow_unicode = True
    yaml.width = WIDTH
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def safe_load(text: str | bytes):
    return _yaml("safe").load(text)


def safe_dump(data) -> str:
    yaml = _yaml("safe")
    yaml.default_flow_style = False
    yaml.sort_base_mapping_type_on_output = True
    buf = StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def roundtrip(text: str):
    """Load for editing with comments and quoting preserved."""
    yaml = _yaml("rt")
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    return yaml, yaml.load(text)


def dump_roundtrip(yaml, doc) -> str:
    buf = StringIO()
    yaml.dump(doc, buf)
    return buf.getvalue()
