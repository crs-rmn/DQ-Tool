"""Engine: Führt alle aktiven Regeln aus und reichert Befunde an.

Schritte pro Analyse-Lauf:
1. Regeln laufen und erzeugen ``Finding``-Objekte.
2. Jedes Finding bekommt Land/Region basierend auf dem betroffenen Datensatz.
3. Verantwortlichkeiten aus der Konfiguration werden eingetragen.
4. Folgefehler-Gruppen (Ursache → Folge) werden ermittelt.
5. Priorisierung (Score + Label) wird berechnet.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from .config import Config
from .finding import Finding
from .loader import DataPackage
from .normalize import country_to_region, is_missing, strip_str, norm_matnr
from .priority import apply_priority
from .rules import registry

log = logging.getLogger(__name__)


@dataclass
class EngineResult:
    findings: list[Finding]
    rule_count: int
    executed_rules: list[str]
    custom_stats: dict = field(default_factory=dict)  # rule_id -> CustomRuleStat
    rule_finding_counts: dict = field(default_factory=dict)  # Registry-Regel-ID -> Anzahl Befunde


def run_analysis(pkg: DataPackage, cfg: Config, custom_rules=None) -> EngineResult:
    """Führt alle aktivierten Regeln aus und reichert die Befunde an."""
    findings: list[Finding] = []
    executed: list[str] = []
    rule_counts: dict[str, int] = {}
    for rule in registry.all():
        if not rule.enabled:
            continue
        try:
            new = rule.run(pkg, cfg)
        except Exception as exc:  # pragma: no cover - Robustheit
            log.exception("Regel %s fehlgeschlagen: %s", rule.rule_id, exc)
            continue
        findings.extend(new)
        executed.append(rule.rule_id)
        rule_counts[rule.rule_id] = len(new)

    custom_stats: dict = {}
    if custom_rules:
        from .custom_rules import run_custom_rules
        cf, custom_stats = run_custom_rules(custom_rules, pkg)
        findings.extend(cf)
        executed.extend(r.rule_id for r in custom_rules if r.enabled)

    _attach_region(findings, pkg)
    _attach_responsibility(findings, cfg)
    _group_causes_and_effects(findings)
    apply_priority(findings, cfg)
    findings.sort(key=lambda f: (-f.priority_score, f.severity))
    return EngineResult(findings=findings, rule_count=len(executed), executed_rules=executed,
                        custom_stats=custom_stats, rule_finding_counts=rule_counts)


def _attach_region(findings: Iterable[Finding], pkg: DataPackage) -> None:
    """Weist jedem Befund Land/Region zu, wenn der betroffene Datensatz es hergibt."""
    account_country = _account_country_map(pkg)
    asset_country = _asset_country_map(pkg, account_country)
    workorder_country = _workorder_country_map(pkg, asset_country, account_country)
    product_country = _product_country_map(pkg)
    for f in findings:
        country = None
        if f.sheet == "Account" and f.record_id:
            country = account_country.get(f.record_id)
        elif f.sheet == "Contact" and f.record_id:
            # Contact-record_id nicht direkt vorhanden → über AccountId
            country = _contact_country(pkg, f.record_id, account_country)
        elif f.sheet == "Asset" and f.record_id:
            country = asset_country.get(f.record_id)
        elif f.sheet == "WorkOrder" and f.record_id:
            country = workorder_country.get(f.record_id)
        elif f.record_id:
            country = product_country.get(f.record_id)
        if country:
            f.country = country
            f.region = country_to_region(country)
        else:
            f.region = f.region or "Nicht zugeordnet"


def _account_country_map(pkg: DataPackage) -> dict[str, str]:
    acc = pkg.get("SF_Account")
    out: dict[str, str] = {}
    if acc is None:
        return out
    for _, row in acc.df.iterrows():
        aid = strip_str(row.get("Id"))
        country = strip_str(row.get("BillingCountry"))
        if aid and country:
            from .normalize import norm_country
            out[aid] = norm_country(country) or country
    return out


def _asset_country_map(pkg: DataPackage, account_country: dict[str, str]) -> dict[str, str]:
    assets = pkg.get("SF_Asset")
    out: dict[str, str] = {}
    if assets is None:
        return out
    for _, row in assets.df.iterrows():
        aid = strip_str(row.get("Id"))
        if not aid:
            continue
        country = strip_str(row.get("REF_Land"))
        if not country:
            acc = strip_str(row.get("AccountId"))
            country = account_country.get(acc or "")
        if country:
            from .normalize import norm_country
            out[aid] = norm_country(country) or country
    return out


def _workorder_country_map(pkg: DataPackage, asset_country, account_country) -> dict[str, str]:
    wo = pkg.get("SF_WorkOrder")
    out: dict[str, str] = {}
    if wo is None:
        return out
    for _, row in wo.df.iterrows():
        rid = strip_str(row.get("WorkOrderNumber"))
        if not rid:
            continue
        country = strip_str(row.get("REF_Land"))
        if not country:
            country = asset_country.get(strip_str(row.get("AssetId")) or "")
        if not country:
            country = account_country.get(strip_str(row.get("AccountId")) or "")
        if country:
            from .normalize import norm_country
            out[rid] = norm_country(country) or country
    return out


def _product_country_map(pkg: DataPackage) -> dict[str, str]:
    """Produkt-Herkunftsland via SAP MARA HERKL."""
    out: dict[str, str] = {}
    from .normalize import ISO3166_ALIAS
    for key in ("SAP_FERT", "SAP_ERSA"):
        sheet = pkg.get(key)
        if sheet is None or "HERKL" not in sheet.df.columns or "MATNR" not in sheet.df.columns:
            continue
        for _, row in sheet.df.iterrows():
            m = norm_matnr(row["MATNR"])
            herkl = strip_str(row.get("HERKL"))
            if m and herkl:
                out[m] = ISO3166_ALIAS.get(herkl.upper(), herkl)
    return out


def _contact_country(pkg: DataPackage, contact_id: str, account_country: dict[str, str]) -> str | None:
    con = pkg.get("SF_Contact")
    if con is None:
        return None
    for _, row in con.df.iterrows():
        if strip_str(row.get("Id")) == contact_id:
            aid = strip_str(row.get("AccountId"))
            return account_country.get(aid or "")
    return None


def _attach_responsibility(findings: Iterable[Finding], cfg: Config) -> None:
    resp = cfg.responsibilities
    for f in findings:
        if f.responsibility:
            continue
        f.responsibility = resp.get(f.category, "Data_Governance")


def _group_causes_and_effects(findings: list[Finding]) -> None:
    """Fasst Befunde zu Ursache/Folge-Gruppen zusammen.

    Vereinfachte Logik: Alle Befunde, die dieselbe ``record_id`` betreffen und zu
    verwandten Kategorien gehören, bekommen eine gemeinsame ``group_id``. So kann
    das UI die "Ursache + Folgen" gruppieren.
    """
    buckets: dict[str, list[Finding]] = {}
    for f in findings:
        if not f.record_id:
            continue
        buckets.setdefault(f.record_id, []).append(f)
    for rid, group in buckets.items():
        if len(group) < 2:
            continue
        gid = f"GRP-{rid}"
        for f in group:
            f.group_id = gid
