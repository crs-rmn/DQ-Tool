"""Zeitliche Plausibilitäts-Regeln."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..config import Config
from ..finding import (
    Finding,
    DIM_VALIDITY,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)
from ..loader import DataPackage
from ..normalize import is_missing, parse_date, strip_str
from .base import registry


@registry.register(
    rule_id="TEMPORAL_DATE_RANGE",
    name="Datum im zulässigen Bereich",
    description="Datumsfelder dürfen nicht weit in der Vergangenheit oder Zukunft liegen.",
    category="Validitaet_Datum",
    dimension=DIM_VALIDITY,
)
def rule_date_range(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    rng = cfg.date_range
    min_year = int(rng.get("min_year", 2000))
    max_future_years = int(rng.get("max_future_years", 1))
    today = datetime.now()
    max_date = datetime(today.year + max_future_years, 12, 31)
    min_date = datetime(min_year, 1, 1)

    date_fields = [
        ("SF_Asset", "PurchaseDate"),
        ("SF_Asset", "InstallDate"),
        ("SF_Asset", "UsageEndDate"),
        ("SF_Asset", "CreatedDate"),
        ("SF_WorkOrder", "StartDate"),
        ("SF_WorkOrder", "EndDate"),
        ("SF_WorkOrder", "CreatedDate"),
        ("SF_Product2", "CreatedDate"),
        ("SF_Product2", "LastModifiedDate"),
        ("SF_Pricebook2", "CreatedDate"),
        ("SF_Account", "CreatedDate"),
        ("HS_Products", "createdate"),
        ("HS_Products", "hs_lastmodifieddate"),
    ]
    for sheet_key, field_name in date_fields:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            if is_missing(raw):
                continue
            dt = parse_date(raw)
            if dt is None:
                yield Finding(
                    rule_id=f"TEMP_PARSE_{sheet.key}_{field_name}",
                    rule_name="Datum nicht interpretierbar",
                    category="Validitaet_Datum",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"Datum '{raw}' im Feld '{field_name}' ist kein gültiges Datum.",
                    severity=SEVERITY_MEDIUM,
                    explanation="Das Datum konnte in kein bekanntes Format überführt werden.",
                    business_impact="Zeitbezogene Auswertungen schließen den Datensatz aus.",
                    cause="Erfassungsformat weicht von Standard ab (z. B. 30.12.2025 vs. 2025-12-30).",
                    correction_suggestion="Datum in ISO-Format YYYY-MM-DD überführen.",
                    correction_type="Vorschlag",
                    confidence="sicher",
                )
                continue
            if dt > max_date:
                yield Finding(
                    rule_id=f"TEMP_FUTURE_{sheet.key}_{field_name}",
                    rule_name="Datum liegt in der Zukunft",
                    category="Validitaet_Datum",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"Datum '{raw}' liegt zu weit in der Zukunft.",
                    severity=SEVERITY_MEDIUM,
                    explanation=(
                        f"Das Datum liegt nach {max_date.date()} - zulässig sind nur "
                        f"bis zu {max_future_years} Jahre in der Zukunft."
                    ),
                    business_impact=(
                        "Zeitreihen und Wartungspläne werden verzerrt, Reports werden unzuverlässig."
                    ),
                    cause="Tippfehler bei Jahreszahl (z. B. 2028 statt 2024).",
                    correction_suggestion="Datum fachlich prüfen und ggf. korrigieren.",
                    correction_type="Manuelle_Pruefung",
                    confidence="sicher",
                )
            elif dt < min_date:
                yield Finding(
                    rule_id=f"TEMP_PAST_{sheet.key}_{field_name}",
                    rule_name="Datum liegt sehr weit in der Vergangenheit",
                    category="Validitaet_Datum",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"Datum '{raw}' liegt vor {min_year}.",
                    severity=SEVERITY_MEDIUM,
                    explanation=f"Das Datum liegt unterhalb des zulässigen Minimums {min_year}.",
                    business_impact="Unplausible historische Werte in Reports.",
                    cause="Platzhalter oder Migrationsfehler (z. B. 1900-01-01).",
                    correction_suggestion="Datum korrigieren oder leer lassen.",
                    correction_type="Manuelle_Pruefung",
                    confidence="sicher",
                )


@registry.register(
    rule_id="TEMPORAL_ASSET_SEQUENCE",
    name="Asset-Zeitfolge (Kauf → Installation → Ende)",
    description="PurchaseDate ≤ InstallDate ≤ UsageEndDate.",
    category="Validitaet_Datum",
    dimension=DIM_VALIDITY,
)
def rule_asset_sequence(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    assets = pkg.get("SF_Asset")
    if assets is None:
        return
    for i, row in assets.df.iterrows():
        purchase = parse_date(row.get("PurchaseDate"))
        install = parse_date(row.get("InstallDate"))
        end = parse_date(row.get("UsageEndDate"))
        if purchase and install and install < purchase:
            yield _seq_finding(assets, int(i), "InstallDate",
                               row.get("InstallDate"),
                               f"Installation ({install.date()}) vor Kauf ({purchase.date()}).",
                               "Installationsdatum liegt vor dem Kaufdatum - fachlich meist nicht zulässig.")
        if install and end and end < install:
            yield _seq_finding(assets, int(i), "UsageEndDate",
                               row.get("UsageEndDate"),
                               f"Nutzungsende ({end.date()}) vor Installation ({install.date()}).",
                               "Das Ende der Nutzung liegt vor der Installation.")


@registry.register(
    rule_id="TEMPORAL_WORKORDER_SEQUENCE",
    name="WorkOrder-Zeitfolge (Start ≤ Ende)",
    description="StartDate muss vor oder gleich EndDate liegen.",
    category="Validitaet_Datum",
    dimension=DIM_VALIDITY,
)
def rule_wo_sequence(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    wo = pkg.get("SF_WorkOrder")
    if wo is None:
        return
    for i, row in wo.df.iterrows():
        start = parse_date(row.get("StartDate"))
        end = parse_date(row.get("EndDate"))
        if start and end and end < start:
            yield _seq_finding(wo, int(i), "EndDate",
                               row.get("EndDate"),
                               f"EndDate ({end.date()}) vor StartDate ({start.date()}).",
                               "EndDate liegt vor StartDate - der Einsatz hat negative Dauer.")


def _seq_finding(sheet, idx, field_name, value, message, explanation) -> Finding:
    return Finding(
        rule_id=f"TEMP_SEQ_{sheet.key}_{field_name}",
        rule_name="Zeitliche Reihenfolge inkonsistent",
        category="Validitaet_Datum",
        dimension=DIM_VALIDITY,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(idx),
        field_name=field_name,
        value=value,
        record_id=_record_id(sheet, idx),
        message=message,
        severity=SEVERITY_HIGH,
        explanation=explanation,
        business_impact="Service-Planung, Garantie- und Finanzauswertungen werden unzuverlässig.",
        cause="Datumsformat-Fehler oder Tippfehler bei Jahreszahl.",
        correction_suggestion="Fachlich korrektes Datum nachtragen.",
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
    )


def _record_id(sheet, idx):
    for cand in ("Id", "WorkOrderNumber", "MATNR", "hs_object_id"):
        if cand in sheet.df.columns:
            v = sheet.df.iloc[idx][cand]
            if not is_missing(v):
                return str(v).strip()
    return None
