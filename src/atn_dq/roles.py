"""Rollen und Fachbereiche aus dem Briefing (config/roles.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .finding import Finding


@dataclass
class DomainArea:
    name: str
    person: str
    title: str
    voice: str = ""
    systems: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    def matches(self, f: Finding) -> bool:
        return (f.system in self.systems or f.sheet in self.sheets or f.field_name in self.fields
                or f.category in self.categories)


@dataclass
class Role:
    name: str
    person: str
    title: str
    focus: str


def load_roles(config_dir: str | Path) -> tuple[dict[str, Role], dict[str, DomainArea]]:
    p = Path(config_dir) / "roles.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    roles = {k: Role(k, v.get("person", ""), v.get("title", k), v.get("focus", ""))
             for k, v in (data.get("roles") or {}).items()}
    areas = {k: DomainArea(k, v.get("person", ""), v.get("title", k), v.get("voice", ""),
                           v.get("systems", []), v.get("sheets", []), v.get("fields", []), v.get("categories", []))
             for k, v in (data.get("domain_areas") or {}).items()}
    return roles, areas


def findings_for_area(findings: list[Finding], area: DomainArea) -> list[Finding]:
    return [f for f in findings if area.matches(f)]
