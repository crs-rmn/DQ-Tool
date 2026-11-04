"""Vollständigkeits-Regeln: Pflichtfelder sind befüllt."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_COMPLETENESS, SEVERITY_HIGH, SEVERITY_MEDIUM
from ..loader import DataPackage, LoadedSheet
from ..normalize import is_missing
from .base import registry


# Welche Blätter in welche Kategorie fallen (für die Verantwortlichkeitszuordnung)
CATEGORY_MAP = {
    "SAP_FERT":            "Vollstaendigkeit_SAP",
    "SAP_ERSA":            "Vollstaendigkeit_SAP",
    "SAP_MARA":            "Vollstaendigkeit_SAP",
    "HS_Products":         "Vollstaendigkeit_HS",
    "HS_PriceBooks":       "Vollstaendigkeit_HS",
    "HS_PriceBookItems":   "Vollstaendigkeit_HS",
    "SF_Product2":         "Vollstaendigkeit_SF",
    "SF_Pricebook2":       "Vollstaendigkeit_SF",
    "SF_PricebookEntry":   "Vollstaendigkeit_SF",
    "SF_Account":          "Vollstaendigkeit_SF_Service",
    "SF_Contact":          "Vollstaendigkeit_SF_Service",
    "SF_Asset":            "Vollstaendigkeit_SF_Service",
    "SF_WorkOrder":        "Vollstaendigkeit_SF_Service",
}


# Pflichtfelder, bei deren Fehlen der Befund hoch eingestuft wird (Schlüssel/Preis/Status)
HIGH_IMPACT_FIELDS = {
    "MATNR", "Id", "hs_object_id", "AccountId", "Product2Id", "AssetId",
    "SerialNumber", "WorkOrderNumber",
    "price", "UnitPrice", "hs_price_eur",
    "atn_sap_materialnummer", "ATN_SAP_Materialnummer__c",
}


@registry.register(
    rule_id="COMPLETENESS_MANDATORY",
    name="Pflichtfelder befüllt",
    description="Prüft, ob laut Governance-Konfiguration definierte Pflichtfelder gefüllt sind.",
    category="Vollstaendigkeit",
    dimension=DIM_COMPLETENESS,
)
def rule_mandatory(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    """Prüft Pflichtfelder pro Blatt gemäß governance.yaml."""
    for sheet_key, fields in cfg.mandatory_fields.items():
        sheet = pkg.get(sheet_key)
        if sheet is None:
            continue
        for field_name in fields:
            if field_name not in sheet.df.columns:
                yield _missing_column(sheet, field_name)
                continue
            yield from _missing_values(sheet, field_name)


def _missing_column(sheet: LoadedSheet, field_name: str) -> Finding:
    cat = CATEGORY_MAP.get(sheet.key, "Vollstaendigkeit")
    return Finding(
        rule_id="COMPLETENESS_MANDATORY_COLUMN",
        rule_name="Pflichtspalte fehlt",
        category=cat,
        dimension=DIM_COMPLETENESS,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.header_row + 1,
        field_name=field_name,
        value=None,
        message=f"Pflichtspalte '{field_name}' fehlt im Blatt.",
        severity=SEVERITY_HIGH,
        explanation=(
            f"Die laut Governance erforderliche Spalte '{field_name}' ist im Blatt "
            f"'{sheet.sheet_name}' nicht vorhanden. Alle Prüfungen, die dieses Feld benötigen, "
            "schlagen damit systematisch fehl."
        ),
        business_impact=(
            "Ohne diese Spalte kann der Datensatz nicht zuverlässig verarbeitet oder "
            "mit anderen Systemen abgeglichen werden."
        ),
        cause="Spalte wurde beim Export aus dem Quellsystem nicht mit ausgegeben.",
        correction_suggestion="Export-Mapping im Quellsystem anpassen und Pflichtspalte ergänzen.",
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
    )


def _missing_values(sheet: LoadedSheet, field_name: str) -> Iterable[Finding]:
    col = sheet.df[field_name]
    for i, raw in col.items():
        if is_missing(raw):
            yield _finding_missing_value(sheet, int(i), field_name, raw)


def _finding_missing_value(sheet: LoadedSheet, idx: int, field_name: str, raw) -> Finding:
    cat = CATEGORY_MAP.get(sheet.key, "Vollstaendigkeit")
    severity = SEVERITY_HIGH if field_name in HIGH_IMPACT_FIELDS else SEVERITY_MEDIUM
    record_id = _best_record_id(sheet, idx)
    return Finding(
        rule_id="COMPLETENESS_MISSING",
        rule_name="Pflichtfeld leer",
        category=cat,
        dimension=DIM_COMPLETENESS,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(idx),
        field_name=field_name,
        value=raw,
        record_id=record_id,
        message=f"Pflichtfeld '{field_name}' ist leer.",
        severity=severity,
        explanation=(
            f"Das Pflichtfeld '{field_name}' ist für diesen Datensatz nicht gefüllt. "
            f"Ohne Wert ist eine vollständige Verarbeitung nicht möglich."
        ),
        business_impact=(
            "Fehlende Pflichtfelder führen zu Lücken in Auswertungen, zu fehlerhaften "
            "Katalog- und Angebotsdaten und erhöhen den manuellen Prüfaufwand."
        ),
        cause="Pflichtfeld wurde beim Anlegen oder Aktualisieren nicht gesetzt.",
        correction_suggestion=f"Fehlenden Wert für '{field_name}' aus der fachlich korrekten Quelle ergänzen.",
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
        tags=[field_name],
    )


def _best_record_id(sheet: LoadedSheet, idx: int):
    for cand in ("MATNR", "Id", "hs_object_id", "WorkOrderNumber"):
        if cand in sheet.df.columns:
            v = sheet.df.iloc[idx][cand]
            if not is_missing(v):
                return str(v).strip()
    return None
