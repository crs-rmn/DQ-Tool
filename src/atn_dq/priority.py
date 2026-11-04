"""Transparente Prioritätsberechnung pro Befund.

Score (0-100) = Schweregrad + Geschäftliche Auswirkung + Betroffene Datensätze
              + Abhängigkeiten/Folgefehler

Die Gewichtung je Komponente ist in ``weights.yaml`` konfigurierbar.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .config import Config
from .finding import Finding


SEVERITY_BASE = {
    "hoch":    1.0,
    "mittel":  0.6,
    "niedrig": 0.25,
}


def apply_priority(findings: list[Finding], cfg: Config) -> None:
    weights = cfg.priority_weights
    severity_w = weights.get("severity", 40)
    impact_w = weights.get("business_impact", 30)
    rows_w = weights.get("affected_rows", 15)
    deps_w = weights.get("dependencies", 15)
    thresholds = weights.get("thresholds", {"high": 70, "medium": 40})
    high_t = thresholds.get("high", 70)
    med_t = thresholds.get("medium", 40)

    # Wie viele Befunde pro Regel/Kategorie (Anteil der Datenbasis)
    rule_counts = Counter(f.rule_id for f in findings)
    max_count = max(rule_counts.values()) if rule_counts else 1

    for f in findings:
        sev = SEVERITY_BASE.get(f.severity, 0.5)
        impact = cfg.business_impact.get(f.category, 5) / 10.0
        row_share = min(1.0, rule_counts.get(f.rule_id, 1) / max_count)
        deps = min(1.0, (len(f.follow_on) + (1 if f.group_id else 0)) / 3.0)
        score = (
            sev * severity_w
            + impact * impact_w
            + row_share * rows_w
            + deps * deps_w
        )
        f.priority_score = round(score, 2)
        if score >= high_t:
            f.priority_label = "Hoch"
        elif score >= med_t:
            f.priority_label = "Mittel"
        else:
            f.priority_label = "Niedrig"
