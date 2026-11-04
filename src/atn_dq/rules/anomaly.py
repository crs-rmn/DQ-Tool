"""Anomalie-Erkennung: Preisausreißer, verdächtige Muster."""
from __future__ import annotations

from statistics import median
from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_ANOMALY, SEVERITY_MEDIUM
from ..loader import DataPackage
from ..normalize import is_missing, norm_matnr, norm_price, strip_str
from .base import registry


@registry.register(
    rule_id="ANOMALY_PRICE_OUTLIER",
    name="Preis-Ausreißer gegenüber Median",
    description="Preiseinträge, die mehr als das 5-fache vom Median je MATNR abweichen.",
    category="Anomalie_Preis",
    dimension=DIM_ANOMALY,
    default_severity="niedrig",
)
def rule_price_outlier(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    # Kombiniere HS + SF Preise pro MATNR
    prices_per_matnr: dict[str, list[tuple]] = {}

    hs_products = pkg.get("HS_Products")
    hs_entries = pkg.get("HS_PriceBookItems")
    if hs_products is not None and hs_entries is not None:
        pid_to_matnr = {
            strip_str(r["hs_object_id"]): norm_matnr(r.get("atn_sap_materialnummer"))
            for _, r in hs_products.df.iterrows()
            if not is_missing(r.get("hs_object_id"))
        }
        for i, row in hs_entries.df.iterrows():
            m = pid_to_matnr.get(strip_str(row.get("hs_associated_product_id")))
            p = norm_price(row.get("hs_price_eur"))
            if m and p and p > 0:
                prices_per_matnr.setdefault(m, []).append((hs_entries, int(i), "hs_price_eur", p))

    sf_products = pkg.get("SF_Product2")
    sf_entries = pkg.get("SF_PricebookEntry")
    if sf_products is not None and sf_entries is not None:
        pid_to_matnr = {
            strip_str(r["Id"]): norm_matnr(r.get("ATN_SAP_Materialnummer__c"))
            for _, r in sf_products.df.iterrows()
            if not is_missing(r.get("Id"))
        }
        for i, row in sf_entries.df.iterrows():
            m = pid_to_matnr.get(strip_str(row.get("Product2Id")))
            p = norm_price(row.get("UnitPrice"))
            if m and p and p > 0:
                prices_per_matnr.setdefault(m, []).append((sf_entries, int(i), "UnitPrice", p))

    for matnr, entries in prices_per_matnr.items():
        if len(entries) < 2:
            continue
        values = [p for _, _, _, p in entries]
        med = median(values)
        if med == 0:
            continue
        for sheet, idx, field_name, p in entries:
            ratio = p / med
            if ratio > 5 or ratio < 0.2:
                yield Finding(
                    rule_id="ANOM_PRICE_OUTLIER",
                    rule_name="Preisausreißer gegenüber Median",
                    category="Anomalie_Preis",
                    dimension=DIM_ANOMALY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(idx),
                    field_name=field_name,
                    value=p,
                    record_id=matnr,
                    message=f"Preis {p:.2f} weicht stark vom Median {med:.2f} ab (Faktor {ratio:.1f}).",
                    severity=SEVERITY_MEDIUM,
                    explanation=(
                        f"Der Preis liegt beim {ratio:.1f}-fachen des Medians der Preise für diese "
                        "Materialnummer über die Preisbücher hinweg."
                    ),
                    business_impact=(
                        "Fachliche Prüfung nötig - möglicherweise Tippfehler oder bewusst abweichender Preis."
                    ),
                    cause="Erfassungsfehler oder spezielle Konditionen ohne Dokumentation.",
                    correction_suggestion="Preis fachlich prüfen.",
                    correction_type="Manuelle_Pruefung",
                    confidence="wahrscheinlich",
                )
