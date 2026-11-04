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
    contact_country = _contact_country_map(pkg, account_country)
    for f in findings:
        country = None
        if f.sheet == "Account" and f.record_id:
            country = account_country.get(f.record_id)
        elif f.sheet == "Contact" and f.record_id:
            # Contact-record_id nicht direkt vorhanden → über AccountId
            country = contact_country.get(f.record_id)
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


def _col(df, name):
    """Spalte als Liste oder leere Liste (vektorfreundlich, ohne iterrows)."""
    return df[name].tolist() if name in df.columns else []


def _account_country_map(pkg: DataPackage) -> dict[str, str]:
    from .normalize import norm_country
    acc = pkg.get("SF_Account")
    out: dict[str, str] = {}
    if acc is None:
        return out
    ids = _col(acc.df, "Id")
    countries = _col(acc.df, "BillingCountry")
    for aid, country in zip(ids, countries):
        aid = strip_str(aid); country = strip_str(country)
        if aid and country:
            out[aid] = norm_country(country) or country
    return out


def _asset_country_map(pkg: DataPackage, account_country: dict[str, str]) -> dict[str, str]:
    from .normalize import norm_country
    assets = pkg.get("SF_Asset")
    out: dict[str, str] = {}
    if assets is None:
        return out
    n = len(assets.df)
    ids = _col(assets.df, "Id") or [None] * n
    lands = _col(assets.df, "REF_Land") or [None] * n
    accs = _col(assets.df, "AccountId") or [None] * n
    for aid, land, acc in zip(ids, lands, accs):
        aid = strip_str(aid)
        if not aid:
            continue
        country = strip_str(land) or account_country.get(strip_str(acc) or "")
        if country:
            out[aid] = norm_country(country) or country
    return out


def _workorder_country_map(pkg: DataPackage, asset_country, account_country) -> dict[str, str]:
    from .normalize import norm_country
    wo = pkg.get("SF_WorkOrder")
    out: dict[str, str] = {}
    if wo is None:
        return out
    n = len(wo.df)
    rids = _col(wo.df, "WorkOrderNumber") or [None] * n
    lands = _col(wo.df, "REF_Land") or [None] * n
    assetids = _col(wo.df, "AssetId") or [None] * n
    accs = _col(wo.df, "AccountId") or [None] * n
    for rid, land, assetid, acc in zip(rids, lands, assetids, accs):
        rid = strip_str(rid)
        if not rid:
            continue
        country = (strip_str(land)
                   or asset_country.get(strip_str(assetid) or "")
                   or account_country.get(strip_str(acc) or ""))
        if country:
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
        for matnr, herkl in zip(sheet.df["MATNR"].tolist(), sheet.df["HERKL"].tolist()):
            m = norm_matnr(matnr)
            herkl = strip_str(herkl)
            if m and herkl:
                out[m] = ISO3166_ALIAS.get(herkl.upper(), herkl)
    return out


def _contact_country_map(pkg: DataPackage, account_country: dict[str, str]) -> dict[str, str]:
    """Contact-Id -> Land (einmal aufgebaut statt pro Befund gesucht)."""
    con = pkg.get("SF_Contact")
    out: dict[str, str] = {}
    if con is None:
        return out
    for cid, aid in zip(con.df.get("Id", []), con.df.get("AccountId", [])):
        cid, aid = strip_str(cid), strip_str(aid)
        if cid and aid and aid in account_country and cid not in out:
            out[cid] = account_country[aid]
    return out


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
