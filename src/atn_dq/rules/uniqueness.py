"""Eindeutigkeits-Regeln: Primärschlüssel und fachliche Schlüssel sind einzigartig."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_UNIQUENESS, SEVERITY_HIGH, SEVERITY_MEDIUM
from ..loader import DataPackage, LoadedSheet
from ..normalize import is_missing, norm_matnr, strip_str
from .base import registry


# Welche Blätter haben welche eindeutigen Schlüssel.
# Für SAP (MARC): Material ist pro WERK einzigartig -> Kombi-Key
UNIQUE_KEYS = [
    ("SAP_FERT", ["MATNR", "WERKS"], SEVERITY_HIGH, "Material + Werk"),
    ("SAP_ERSA", ["MATNR", "WERKS"], SEVERITY_HIGH, "Material + Werk"),
    ("SAP_MARA", ["MATNR"],          SEVERITY_HIGH, "Materialnummer"),
    ("HS_Products",     ["hs_object_id"], SEVERITY_HIGH, "HubSpot-Objekt-ID"),
    ("HS_Products",     ["hs_sku"],       SEVERITY_MEDIUM, "SKU"),
    ("HS_PriceBooks",   ["hs_object_id"], SEVERITY_HIGH, "Preisbuch-ID"),
    ("HS_PriceBookItems", ["hs_object_id"], SEVERITY_HIGH, "Preiseintrag-ID"),
    ("HS_PriceBookItems", ["price_book_id", "hs_associated_product_id"],
     SEVERITY_HIGH, "Preiseintrag (Produkt im Preisbuch)"),
    ("SF_Product2",       ["Id"], SEVERITY_HIGH, "Salesforce-Id"),
    ("SF_Product2",       ["ProductCode"], SEVERITY_MEDIUM, "Produktcode"),
    ("SF_Pricebook2",     ["Id"], SEVERITY_HIGH, "Preisbuch-Id"),
    ("SF_PricebookEntry", ["Id"], SEVERITY_HIGH, "Preiseintrag-Id"),
    ("SF_PricebookEntry", ["Pricebook2Id", "Product2Id"],
     SEVERITY_HIGH, "Produkt im Preisbuch"),
    ("SF_Account",   ["Id"], SEVERITY_HIGH, "Account-Id"),
    ("SF_Contact",   ["Id"], SEVERITY_HIGH, "Contact-Id"),
    ("SF_Asset",     ["Id"], SEVERITY_HIGH, "Asset-Id"),
    ("SF_Asset",     ["SerialNumber"], SEVERITY_HIGH, "Seriennummer"),
    ("SF_WorkOrder", ["Id"], SEVERITY_HIGH, "WorkOrder-Id"),
    ("SF_WorkOrder", ["WorkOrderNumber"], SEVERITY_HIGH, "Auftragsnummer"),
]

CATEGORY_MAP = {
    "SAP_FERT":          "Eindeutigkeit",
    "SAP_ERSA":          "Eindeutigkeit",
    "SAP_MARA":          "Eindeutigkeit",
    "HS_Products":       "Eindeutigkeit",
    "HS_PriceBooks":     "Eindeutigkeit",
    "HS_PriceBookItems": "Eindeutigkeit",
    "SF_Product2":       "Eindeutigkeit",
    "SF_Pricebook2":     "Eindeutigkeit",
    "SF_PricebookEntry": "Eindeutigkeit",
    "SF_Account":        "Eindeutigkeit",
    "SF_Contact":        "Eindeutigkeit",
    "SF_Asset":          "Eindeutigkeit",
    "SF_WorkOrder":      "Eindeutigkeit",
}


@registry.register(
    rule_id="UNIQUENESS_KEYS",
    name="Primär- und Fachschlüssel eindeutig",
    description="Prüft, ob definierte Schlüssel in jedem Datensatz einzigartig sind.",
    category="Eindeutigkeit",
    dimension=DIM_UNIQUENESS,
)
def rule_uniqueness(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    for sheet_key, fields, severity, label in UNIQUE_KEYS:
        sheet = pkg.get(sheet_key)
        if sheet is None:
            continue
        missing_cols = [f for f in fields if f not in sheet.df.columns]
        if missing_cols:
            continue  # bereits durch COMPLETENESS abgedeckt
        yield from _duplicates(sheet, fields, severity, label)


def _duplicates(sheet: LoadedSheet, fields: list[str], severity: str, label: str) -> Iterable[Finding]:
    df = sheet.df
    norm_series = _combo_series(df, fields)
    counts = norm_series.value_counts(dropna=False)
    dup_values = counts[counts > 1].index.tolist()
    for value in dup_values:
        if value is None or (isinstance(value, str) and value == ""):
            continue  # fehlende Werte werden von COMPLETENESS gemeldet
        dup_mask = norm_series == value
        dup_indices = df.index[dup_mask].tolist()
        for idx in dup_indices:
            raw = _display_value(df, fields, idx)
            yield Finding(
                rule_id=f"UNIQUE_{sheet.key}_{'_'.join(fields)}",
                rule_name=f"Doppelter Wert: {label}",
                category=CATEGORY_MAP.get(sheet.key, "Eindeutigkeit"),
                dimension=DIM_UNIQUENESS,
                system=sheet.system,
                file=sheet.source_file,
                sheet=sheet.sheet_name,
                row=sheet.excel_row(int(idx)),
                field_name="+".join(fields),
                value=raw,
                record_id=raw,
                message=f"{label} '{raw}' kommt {len(dup_indices)}-mal vor.",
                severity=severity,
                explanation=(
                    f"Der Schlüssel '{label}' muss im Blatt '{sheet.sheet_name}' "
                    f"einzigartig sein. Der Wert '{raw}' erscheint jedoch {len(dup_indices)}-mal."
                ),
                business_impact=(
                    "Doppelte Schlüssel können zu falschen Zuordnungen führen - z. B. in "
                    "Bestands-, Service- oder Preislisten - und erschweren verlässliche Berichte."
                ),
                cause="Datensatz wurde mehrfach angelegt oder beim Import nicht dedupliziert.",
                correction_suggestion=(
                    "Doppelte Datensätze zusammenführen oder mit eindeutiger Kennung versehen. "
                    "Vor der Zusammenführung fachliche Prüfung erforderlich."
                ),
                correction_type="Manuelle_Pruefung",
                confidence="sicher",
                tags=fields,
            )


def _combo_series(df, fields: list[str]):
    import pandas as pd
    parts = []
    for f in fields:
        col = df[f].map(lambda v: norm_matnr(v) if v is not None else None)
        parts.append(col.fillna("").astype(str).str.strip())
    return parts[0].str.cat(parts[1:], sep="|") if len(parts) > 1 else parts[0]


def _display_value(df, fields: list[str], idx: int) -> str:
    vals = []
    for f in fields:
        v = df.iloc[idx][f]
        vals.append("" if is_missing(v) else str(v).strip())
    return "+".join(vals)
