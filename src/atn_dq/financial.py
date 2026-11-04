"""Geschäftliche Auswirkungen: nur dort ein Euro-Betrag, wo die Daten ihn tragen.

Jede Position nennt Berechnungsgrundlage, verwendete Daten und Unsicherheit.
Wo Daten fehlen, steht ``amount_eur = None`` und der Status
"Finanzieller Einfluss nicht zuverlässig berechenbar" - es wird nichts geschätzt.

Annahmen (bewusst vorsichtig):
- Absatzmenge = Anzahl installierter Geräte (SF Asset, Menge > 0) je Produkt.
  Das ist eine historische Basis, keine Absatzprognose.
- Preise werden nur verglichen, wenn beide Werte numerisch, > 0 und in EUR sind
  und das Produkt (MATNR) in beiden Systemen eindeutig vorkommt.
- Die Preisspanne ist eine **Risikospanne**, kein tatsächlich entstandener Schaden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

import pandas as pd

from .finding import Finding
from .loader import DataPackage
from .normalize import is_missing, norm_currency, norm_matnr, norm_price, parse_date, strip_str

NOT_CALCULABLE = "Finanzieller Einfluss nicht zuverlässig berechenbar"

# Spanne ab diesem Faktor gilt als mutmaßlicher Erfassungsfehler (z. B. Faktor 10)
SUSPECT_RATIO = 3.0


@dataclass
class ImpactItem:
    key: str
    title: str
    cause: str                       # betroffene Ursache
    status: str                      # "berechnet" | "teilweise" | "nicht berechenbar"
    amount_eur: float | None
    basis: str                       # Berechnungsgrundlage
    data_used: list[str]
    uncertainty: str
    records: int = 0                 # betroffene Datensätze
    filter_rule_prefix: str = ""     # für Drill-down in Befunde
    details: pd.DataFrame | None = field(default=None, repr=False)

    @property
    def amount_label(self) -> str:
        if self.amount_eur is None:
            return NOT_CALCULABLE
        return f"{self.amount_eur:,.0f} €".replace(",", ".")


def _sheet(pkg: DataPackage, key: str):
    s = pkg.get(key)
    return None if s is None else s.df


def _units_per_matnr(pkg: DataPackage) -> dict[str, float]:
    prod, assets = _sheet(pkg, "SF_Product2"), _sheet(pkg, "SF_Asset")
    if prod is None or assets is None:
        return {}
    pid2m = {strip_str(r.get("Id")): norm_matnr(r.get("ATN_SAP_Materialnummer__c"))
             for _, r in prod.iterrows() if not is_missing(r.get("Id"))}
    units: dict[str, float] = {}
    for _, r in assets.iterrows():
        m = pid2m.get(strip_str(r.get("Product2Id")))
        if not m:
            continue
        q = norm_price(r.get("Quantity"))
        q = 1.0 if q is None else q
        if q > 0:
            units[m] = units.get(m, 0.0) + q
    return units


def _unique_matnr_prices(pkg: DataPackage) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """(SF-Listenpreis, HS-Preis, HS-Herstellkosten) je eindeutiger MATNR."""
    sf: dict[str, float] = {}
    hs: dict[str, float] = {}
    cost: dict[str, float] = {}

    prod, pbe, pb = _sheet(pkg, "SF_Product2"), _sheet(pkg, "SF_PricebookEntry"), _sheet(pkg, "SF_Pricebook2")
    if prod is not None and pbe is not None:
        std_ids = set()
        if pb is not None:
            std_ids = {strip_str(r.get("Id")) for _, r in pb.iterrows()
                       if "standard" in str(r.get("Name", "")).lower()}
        counts = prod["ATN_SAP_Materialnummer__c"].map(norm_matnr).value_counts()
        pid2m = {strip_str(r.get("Id")): norm_matnr(r.get("ATN_SAP_Materialnummer__c"))
                 for _, r in prod.iterrows() if not is_missing(r.get("Id"))}
        seen: dict[str, int] = {}
        for _, r in pbe.iterrows():
            if strip_str(r.get("Pricebook2Id")) not in std_ids:
                continue
            m = pid2m.get(strip_str(r.get("Product2Id")))
            p = norm_price(r.get("UnitPrice"))
            if not m or p is None or p <= 0 or counts.get(m, 0) != 1:
                continue
            if norm_currency(r.get("CurrencyIsoCode")) != "EUR":
                continue
            seen[m] = seen.get(m, 0) + 1
            sf[m] = p
        sf = {m: p for m, p in sf.items() if seen.get(m) == 1}

    hp = _sheet(pkg, "HS_Products")
    if hp is not None:
        counts = hp["atn_sap_materialnummer"].map(norm_matnr).value_counts()
        for _, r in hp.iterrows():
            m = norm_matnr(r.get("atn_sap_materialnummer"))
            if not m or counts.get(m, 0) != 1:
                continue
            p = norm_price(r.get("price"))
            c = norm_price(r.get("hs_cost_of_goods_sold"))
            if p is not None and p > 0:
                hs[m] = p
            if c is not None and c > 0:
                cost[m] = c
    return sf, hs, cost


def price_gap_impact(pkg: DataPackage) -> ImpactItem:
    sf, hs, _ = _unique_matnr_prices(pkg)
    units = _units_per_matnr(pkg)
    rows: list[dict[str, Any]] = []
    for m in sorted(set(sf) & set(hs)):
        a, b = sf[m], hs[m]
        if abs(a - b) < 0.5:
            continue
        gap = abs(a - b)
        ratio = max(a, b) / min(a, b)
        u = units.get(m)
        suspect = ratio >= SUSPECT_RATIO
        rows.append({
            "MATNR": m, "Salesforce (EUR)": a, "HubSpot (EUR)": b,
            "Spanne je Stück (EUR)": gap,
            "Installierte Geräte": u if u else 0,
            "Risikospanne (EUR)": gap * u if (u and not suspect) else None,
            "Hinweis": ("Faktor ≥ 3: mutmaßlicher Erfassungsfehler - Betrag nicht belastbar"
                        if suspect else ("keine Geräte in den Servicedaten - Menge unbekannt" if not u else "")),
        })
    df = pd.DataFrame(rows)
    total = float(df["Risikospanne (EUR)"].sum()) if not df.empty else 0.0
    calc = int(df["Risikospanne (EUR)"].notna().sum()) if not df.empty else 0
    return ImpactItem(
        key="price_gap",
        title="Preisabweichung Salesforce ↔ HubSpot",
        cause="Preispflege an zwei Stellen ohne führendes System (Governance-Entscheidung offen)",
        status="berechnet" if calc else "nicht berechenbar",
        amount_eur=total if calc else None,
        basis="|Preis Salesforce − Preis HubSpot| × installierte Geräte (Asset-Menge) je MATNR",
        data_used=["SF Pricebook2/PricebookEntry (Standardpreisbuch)", "HS Products.price",
                   "SF Asset (Menge je Produkt)"],
        uncertainty=("Risikospanne, kein Schaden: tatsächlich verkaufte Mengen und gewährte Preise "
                     "stehen nicht in den Daten. "
                     f"{len(df) - calc} von {len(df)} abweichenden Produkten sind nicht eingerechnet "
                     "(Erfassungsfehler-Verdacht oder keine Geräte)."),
        records=len(df), filter_rule_prefix="CONS_PRICE_CROSS", details=df,
    )


def below_cost_impact(pkg: DataPackage) -> ImpactItem:
    sf, hs, cost = _unique_matnr_prices(pkg)
    units = _units_per_matnr(pkg)
    rows = []
    for m in sorted(set(hs) & set(cost)):
        if hs[m] >= cost[m]:
            continue
        per = cost[m] - hs[m]
        u = units.get(m)
        # Liegt der Salesforce-Preis über den Kosten, spricht das für einen Preisfehler in HubSpot
        sf_ok = m in sf and sf[m] >= cost[m]
        suspect = cost[m] / hs[m] >= 10 or sf_ok
        rows.append({
            "MATNR": m, "Preis HubSpot (EUR)": hs[m], "Herstellkosten (EUR)": cost[m],
            "Verlust je Stück (EUR)": per, "Installierte Geräte": u if u else 0,
            "Marge unter Kosten gesamt (EUR)": per * u if (u and not suspect) else None,
            "Hinweis": ("Salesforce-Preis liegt über den Kosten bzw. Kosten ≥ 10× Preis: "
                        "vermutlich Preisfehler in HubSpot - nicht eingerechnet"
                        if suspect else ("keine Geräte in den Servicedaten" if not u else "")),
        })
    df = pd.DataFrame(rows)
    calc = int(df["Marge unter Kosten gesamt (EUR)"].notna().sum()) if not df.empty else 0
    total = float(df["Marge unter Kosten gesamt (EUR)"].sum()) if calc else None
    return ImpactItem(
        key="below_cost",
        title="Preis unter Herstellkosten (HubSpot)",
        cause="Preis oder Herstellkosten falsch gepflegt - ob echter Verlust oder Datenfehler, ist offen",
        status="teilweise" if calc else "nicht berechenbar",
        amount_eur=total,
        basis="(Herstellkosten − Preis) × installierte Geräte je MATNR",
        data_used=["HS Products.price", "HS Products.hs_cost_of_goods_sold", "SF Asset (Menge)"],
        uncertainty=("Herstellkosten stehen nur in HubSpot, nicht in SAP - sie sind nicht gegengeprüft. "
                     "Ob es sich um Verlustverkäufe oder um Datenfehler handelt, muss Controlling klären. "
                     f"{len(df)} Produkte betroffen, {calc} davon mit Menge und plausiblen Werten berechnet."),
        records=len(df), filter_rule_prefix="", details=df,
    )


def warranty_impact(pkg: DataPackage) -> ImpactItem:
    wo, assets = _sheet(pkg, "SF_WorkOrder"), _sheet(pkg, "SF_Asset")
    if wo is None or assets is None:
        return ImpactItem("warranty", "Garantiefälle nach Garantieende", "Service", "nicht berechenbar",
                          None, "-", [], "Service-Daten nicht geladen")
    end = {strip_str(r.get("Id")): parse_date(r.get("UsageEndDate")) for _, r in assets.iterrows()}
    rows = []
    for idx, r in wo.iterrows():
        if str(r.get("ATN_Wartungsart__c", "")).strip().lower() != "garantiefall":
            continue
        e = end.get(strip_str(r.get("AssetId")))
        s = parse_date(r.get("StartDate"))
        if e is None or s is None or s <= e:
            continue
        cost = norm_price(r.get("ATN_Wartungskosten__c"))
        rows.append({
            "Auftrag": strip_str(r.get("WorkOrderNumber")), "Asset": strip_str(r.get("AssetId")),
            "Garantieende": e.date(), "Einsatzbeginn": s.date(),
            "Wartungskosten (EUR)": cost if cost is not None and cost >= 0 else None,
        })
    df = pd.DataFrame(rows)
    known = df["Wartungskosten (EUR)"].dropna() if not df.empty else pd.Series(dtype=float)
    if len(known) and float(known.sum()) == 0.0:
        known = known.iloc[0:0]   # alle Kosten 0: kein belastbarer Betrag
        zero_note = " Alle Einsätze sind mit Kosten 0 € erfasst - die Leistung wurde also nicht berechnet, ihr Wert ist unbekannt."
    else:
        zero_note = ""
    return ImpactItem(
        key="warranty",
        title="Garantiefälle nach Garantieende",
        cause="Garantiestatus wird bei Auftragsanlage nicht gegen das Nutzungsende des Assets geprüft",
        status="teilweise" if len(known) else "nicht berechenbar",
        amount_eur=float(known.sum()) if len(known) else None,
        basis="Summe der Wartungskosten von Einsätzen, die als „Garantiefall“ geführt sind, "
              "obwohl der Beginn nach dem Garantie-/Nutzungsende des Assets liegt",
        data_used=["SF WorkOrder (Wartungsart, StartDate, Wartungskosten)", "SF Asset.UsageEndDate"],
        uncertainty=("Das sind Kosten, kein entgangener Umsatz: ein Verrechnungspreis liegt nicht vor. "
                     "Ob die Leistung hätte berechnet werden dürfen (Kulanz, Vertrag), steht nicht in den Daten. "
                     f"{len(df)} Aufträge betroffen, {len(known)} mit verwertbarer Kostenangabe." + zero_note),
        records=len(df), details=df,
    )


def customs_impact(findings: list[Finding]) -> ImpactItem:
    fs = [f for f in findings if f.field_name in ("STAWN", "HERKL")]
    return ImpactItem(
        key="customs", title="Zolltarifnummer / Ursprungsland",
        cause="Zoll-relevante Felder in SAP fehlen oder sind falsch formatiert",
        status="nicht berechenbar", amount_eur=None,
        basis="Keine Berechnung: Warenwerte pro Sendung, Zollsätze und Strafmaße liegen nicht vor.",
        data_used=["SAP MARC STAWN / HERKL (nur Anzahl betroffener Datensätze)"],
        uncertainty=("Es gibt keine Sendungs- oder Frachtdaten. Ein Betrag wäre erfunden. "
                     "Belegbar ist nur das Compliance-Risiko durch die Anzahl betroffener Materialien."),
        records=len({(f.sheet, f.row) for f in fs}),
    )


def compute_impacts(pkg: DataPackage, findings: list[Finding]) -> list[ImpactItem]:
    return [price_gap_impact(pkg), below_cost_impact(pkg), warranty_impact(pkg), customs_impact(findings)]


def total_calculated(items: list[ImpactItem]) -> tuple[float | None, int]:
    vals = [i.amount_eur for i in items if i.amount_eur is not None]
    return (sum(vals) if vals else None), len(vals)
