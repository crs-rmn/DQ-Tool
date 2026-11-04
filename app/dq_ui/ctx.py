"""Gemeinsamer Kontext, den die Streamlit-Hauptdatei an die Ansichten übergibt."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Ctx:
    cfg: Any
    pkg: Any
    result: Any
    findings: list
    overall: Any
    regions: list
    impacts: list
    roles: dict
    areas: dict
    config_dir: Path
    history: Any
    kpi: Callable            # kpi(col, label, value, css, help_text)
    badge: Callable          # badge(label) -> html
    goto_findings: Callable  # goto_findings(filters: dict)
    goto_page: Callable      # goto_page(name: str)
    rules_info: list = field(default_factory=list)
