"""Zentrale Konfiguration (lädt governance.yaml und weights.yaml)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    governance: dict[str, Any]
    weights: dict[str, Any]

    @property
    def mandatory_fields(self) -> dict[str, list[str]]:
        return self.governance.get("mandatory_fields", {})

    @property
    def allowed_values(self) -> dict[str, list[str]]:
        return self.governance.get("allowed_values", {})

    @property
    def leading_systems(self) -> dict[str, str]:
        return self.governance.get("leading_systems", {})

    @property
    def responsibilities(self) -> dict[str, str]:
        return self.governance.get("responsibilities", {})

    @property
    def allowed_currencies(self) -> list[str]:
        return self.governance.get("allowed_currencies", [])

    @property
    def allowed_units(self) -> list[str]:
        return self.governance.get("allowed_units", [])

    @property
    def value_aliases(self) -> dict[str, dict[str, str]]:
        return self.governance.get("value_aliases", {})

    @property
    def date_range(self) -> dict[str, int]:
        return self.governance.get("date_range", {"min_year": 2000, "max_future_years": 1})

    @property
    def priority_weights(self) -> dict[str, Any]:
        return self.weights.get("priority", {})

    @property
    def business_impact(self) -> dict[str, int]:
        return self.weights.get("business_impact", {})

    @property
    def quality_score_cfg(self) -> dict[str, Any]:
        return self.weights.get("quality_score", {})


def load_config(config_dir: str | Path) -> Config:
    config_dir = Path(config_dir)
    gov = _read_yaml(config_dir / "governance.yaml")
    wts = _read_yaml(config_dir / "weights.yaml")
    return Config(governance=gov, weights=wts)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Konfiguration fehlt: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
