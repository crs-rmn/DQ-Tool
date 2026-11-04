"""Qualitäts-Score pro Datenbasis und pro Region.

Jede Dimension (Vollständigkeit, Validität, ...) startet bei 100. Pro Befund
in dieser Dimension werden Punkte abgezogen, gewichtet nach Schweregrad.
Das Ergebnis wird mit den Dimensionsgewichten zu einem Gesamtscore kombiniert.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .config import Config
from .finding import Finding
from .loader import DataPackage
from .normalize import country_to_region, strip_str


@dataclass
class RegionScore:
    region: str
    score: float
    findings_high: int
    findings_medium: int
    findings_low: int
    records_estimated: int
    sufficient_data: bool


@dataclass
class OverallScore:
    score: float
    by_dimension: dict[str, float]
    findings_high: int
    findings_medium: int
    findings_low: int
    total_records: int


def overall_score(findings: list[Finding], pkg: DataPackage, cfg: Config) -> OverallScore:
    cfg_score = cfg.quality_score_cfg
    dims = cfg_score.get("dimensions", {})
    sev_penalty = cfg_score.get("severity_penalty", {"hoch": 1.0, "mittel": 0.4, "niedrig": 0.1})
    total_records = _total_records(pkg)

    # Ein einziger Durchlauf: Abzüge je Dimension, Gesamtabzug und Schweregrad-Zähler.
    dim_penalty: dict[str, float] = {d: 0.0 for d in dims}
    total_penalty = 0.0
    sev = {"hoch": 0, "mittel": 0, "niedrig": 0}
    for f in findings:
        p = sev_penalty.get(f.severity, 0.2)
        total_penalty += p
        if f.dimension in dim_penalty:
            dim_penalty[f.dimension] += p
        sev[f.severity] = sev.get(f.severity, 0) + 1

    max_penalty = max(total_records, 10)
    per_dim = {d: (100.0 if pen == 0 else max(0.0, 100.0 - (pen / max_penalty) * 100.0))
               for d, pen in dim_penalty.items()}
    # Gesamtscore mit derselben Formel wie die Regions-Scores:
    # alle gewichteten Abzüge im Verhältnis zur Gesamtzahl der Datensätze.
    overall = max(0.0, 100.0 - (total_penalty / max_penalty) * 100.0)

    return OverallScore(
        score=round(overall, 1),
        by_dimension={k: round(v, 1) for k, v in per_dim.items()},
        findings_high=sev["hoch"],
        findings_medium=sev["mittel"],
        findings_low=sev["niedrig"],
        total_records=total_records,
    )


def region_scores(findings: list[Finding], pkg: DataPackage, cfg: Config) -> list[RegionScore]:
    cfg_score = cfg.quality_score_cfg
    sev_penalty = cfg_score.get("severity_penalty", {"hoch": 1.0, "mittel": 0.4, "niedrig": 0.1})
    min_records = int(cfg_score.get("min_records_for_score", 5))

    records_per_region = _records_per_region(pkg)
    findings_per_region: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        findings_per_region[f.region or "Nicht zugeordnet"].append(f)

    all_regions = set(records_per_region.keys()) | set(findings_per_region.keys())
    results: list[RegionScore] = []
    for region in sorted(all_regions):
        fs = findings_per_region.get(region, [])
        records = records_per_region.get(region, 0)
        sev = {"hoch": 0, "mittel": 0, "niedrig": 0}
        for f in fs:
            sev[f.severity] = sev.get(f.severity, 0) + 1
        if records < min_records and region != "Nicht zugeordnet":
            results.append(RegionScore(
                region=region, score=float("nan"),
                findings_high=sev["hoch"], findings_medium=sev["mittel"], findings_low=sev["niedrig"],
                records_estimated=records, sufficient_data=False,
            ))
            continue
        penalty = sum(sev_penalty.get(f.severity, 0.2) for f in fs)
        divisor = max(records, 10)
        score = max(0.0, 100.0 - (penalty / divisor) * 100.0)
        results.append(RegionScore(
            region=region, score=round(score, 1),
            findings_high=sev["hoch"], findings_medium=sev["mittel"], findings_low=sev["niedrig"],
            records_estimated=records, sufficient_data=True,
        ))
    return results


def _total_records(pkg: DataPackage) -> int:
    return sum(len(sheet.df) for sheet in pkg.sheets.values())


def _count_regions(df, col: str, out: dict[str, int]) -> None:
    """Zählt Datensätze je Region für eine Spalte vektorisiert (value_counts)."""
    if col not in df.columns:
        return
    vc = df[col].map(lambda v: country_to_region(strip_str(v))).value_counts()
    for region, n in vc.items():
        out[region] += int(n)


def _records_per_region(pkg: DataPackage) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    acc = pkg.get("SF_Account")
    if acc is not None:
        _count_regions(acc.df, "BillingCountry", out)
    assets = pkg.get("SF_Asset")
    if assets is not None:
        _count_regions(assets.df, "REF_Land", out)
    wo = pkg.get("SF_WorkOrder")
    if wo is not None:
        _count_regions(wo.df, "REF_Land", out)
    # Produktbezogene Datensätze (ohne Markt) in "Nicht zugeordnet" summieren,
    # damit der Score dort realistisch bleibt und nicht auf 0 fällt.
    for key in ("SAP_FERT", "SAP_ERSA", "SAP_MARA",
                "HS_Products", "HS_PriceBookItems", "HS_PriceBooks",
                "SF_Product2", "SF_PricebookEntry", "SF_Pricebook2",
                "SF_Contact"):
        sheet = pkg.get(key)
        if sheet is not None:
            out["Nicht zugeordnet"] += len(sheet.df)
    return out
