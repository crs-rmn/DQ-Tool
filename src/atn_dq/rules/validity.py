"""Validitäts-Regeln: Statuswerte, Datentypen, Formate."""
from __future__ import annotations

import re
from typing import Iterable

from ..config import Config
from ..finding import (
    Finding,
    DIM_VALIDITY,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)
from ..loader import DataPackage, LoadedSheet
from ..normalize import (
    is_missing,
    norm_country,
    norm_currency,
    norm_price,
    norm_upper,
    parse_date,
    strip_str,
)
from .base import registry


# Zuordnung (Blatt, Feld) -> Schlüssel in allowed_values
STATUS_FIELDS = [
    ("HS_Products",      "hs_status",         "HS_product_status",    "Validitaet_Status"),
    ("HS_Products",      "hs_pricing_model",  "HS_pricing_model",     "Validitaet_Allgemein"),
    ("HS_Products",      "hs_product_type",   "HS_product_type",      "Validitaet_Allgemein"),
    ("HS_PriceBookItems","hs_status",         "HS_product_status",    "Validitaet_Status"),
    ("HS_PriceBookItems","hs_pricing_model",  "HS_pricing_model",     "Validitaet_Allgemein"),
    ("SF_Asset",         "Status",            "SF_Asset_status",      "Validitaet_Status"),
    ("SF_WorkOrder",     "Status",            "SF_WorkOrder_status",  "Validitaet_Status"),
    ("SF_WorkOrder",     "Priority",          "SF_WorkOrder_priority","Validitaet_Allgemein"),
    ("SAP_FERT",         "MMSTA",             "SAP_MMSTA",            "Validitaet_Status"),
    ("SAP_ERSA",         "MMSTA",             "SAP_MMSTA",            "Validitaet_Status"),
    ("SAP_FERT",         "MTART",             "SAP_MTART",            "Validitaet_Allgemein"),
    ("SAP_ERSA",         "MTART",             "SAP_MTART",            "Validitaet_Allgemein"),
    ("SAP_MARA",         "MTART",             "SAP_MTART",            "Validitaet_Allgemein"),
]

PRICE_FIELDS = [
    ("HS_Products",       "price",           "Validitaet_Preis"),
    ("HS_Products",       "hs_cost_of_goods_sold", "Validitaet_Preis"),
    ("HS_PriceBookItems", "hs_price_eur",    "Validitaet_Preis"),
    ("HS_PriceBookItems", "hs_cost_of_goods_sold", "Validitaet_Preis"),
    ("SF_PricebookEntry", "UnitPrice",       "Validitaet_Preis"),
    ("SF_Asset",          "Price",           "Validitaet_Preis"),
    ("SF_WorkOrder",      "ATN_Wartungskosten__c", "Validitaet_Preis"),
]

CURRENCY_FIELDS = [
    ("HS_PriceBooks",      "hs_supported_currencies"),
    ("SF_Pricebook2",      "CurrencyIsoCode"),
    ("SF_PricebookEntry",  "CurrencyIsoCode"),
]

UNIT_FIELDS = [
    ("SAP_FERT",   "MEINS"),
    ("SAP_ERSA",   "MEINS"),
    ("SAP_MARA",   "MEINS"),
    ("SF_Product2", "QuantityUnitOfMeasure"),
]

EMAIL_FIELDS = [
    ("SF_Contact", "Email"),
]

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Ab wie vielen gleichartigen Normierungs-Treffern pro Spalte wird zu EINEM
# Sammelbefund zusammengefasst, statt zehntausende Einzelzeilen zu melden.
# (Reine Schreibweise-/Alias-Abweichungen - fachlich eine Spalten-Konvention,
#  kein Fehler je Zeile.)
AGG_THRESHOLD = 50


def _record_ids_for(sheet: LoadedSheet) -> list:
    """Record-IDs der ganzen Tabelle in einem Rutsch (schnell, ohne iloc je Zeile)."""
    for cand in ("MATNR", "Id", "hs_object_id", "WorkOrderNumber", "SerialNumber"):
        if cand in sheet.df.columns:
            col = sheet.df[cand]
            return [None if is_missing(v) else str(v).strip() for v in col]
    return [None] * len(sheet.df)


def _aggregate_finding(sheet: LoadedSheet, field_name: str, cat: str, label: str,
                       items: list[tuple[int, object, str]], total: int) -> Finding:
    """Ein Sammelbefund für eine ganze, systematisch betroffene Spalte."""
    examples = ", ".join(f"'{r}' → '{t}'" for _, r, t in items[:3])
    first_idx = items[0][0]
    n = len(items)
    return Finding(
        rule_id=f"VALID_{sheet.key}_{field_name}_{label}_AGG",
        rule_name=f"Spalten-Normierung '{field_name}' ({n} Werte, Sammelbefund)",
        category=cat,
        dimension=DIM_VALIDITY,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(int(first_idx)),
        field_name=field_name,
        value=None,
        record_id=None,
        message=(f"{n} von {total} Werten im Feld '{field_name}' sind nur anders geschrieben "
                 f"(z. B. {examples}). Als EIN Sammelbefund zusammengefasst - einmalige Spalten-Normierung behebt alle."),
        severity=SEVERITY_LOW,
        explanation=(f"{n} Datensätze sind betroffen - das betrifft praktisch die ganze Spalte und deutet "
                     f"auf eine Schreibkonvention des Quellsystems hin, nicht auf {n} unabhängige Einzelfehler."),
        business_impact=("Erschwert maschinelle Vergleiche und Filter. Betrifft so viele Zeilen, dass eine "
                         "einmalige Normierung im Import-Prozess sinnvoller ist als Einzelkorrekturen."),
        cause="Das Quellsystem erfasst diese Spalte in abweichender Schreibweise/Benennung.",
        correction_suggestion=(f"Spalte '{field_name}' einmalig per Mapping normieren (z. B. im Import). "
                               "Details je Zeile sind über die Normierungsregel reproduzierbar."),
        correction_type="Sichere_Korrektur",
        confidence="sicher",
        tags=["sammelbefund", f"betrifft_{n}"],
    )


def _emit_normalization(sheet, field_name, cat, label, rule_suffix, items, total,
                        msg_fn, expl, impact, cause, corr_fn) -> Iterable[Finding]:
    """Entweder 1 Sammelbefund (viele Treffer) oder Einzelbefunde (wenige)."""
    if not items:
        return
    if len(items) > AGG_THRESHOLD:
        yield _aggregate_finding(sheet, field_name, cat, label, items, total)
        return
    ids = _record_ids_for(sheet)
    for idx, raw, target in items:
        yield Finding(
            rule_id=f"VALID_{sheet.key}_{field_name}_{rule_suffix}",
            rule_name=f"{label} in '{field_name}'",
            category=cat, dimension=DIM_VALIDITY, system=sheet.system,
            file=sheet.source_file, sheet=sheet.sheet_name, row=sheet.excel_row(int(idx)),
            field_name=field_name, value=raw, record_id=ids[idx] if idx < len(ids) else None,
            message=msg_fn(raw, target), severity=SEVERITY_LOW, explanation=expl,
            business_impact=impact, cause=cause, correction_suggestion=corr_fn(raw, target),
            correction_type="Sichere_Korrektur", confidence="sicher",
        )


@registry.register(
    rule_id="VALIDITY_STATUS",
    name="Zulässige Status-/Typwerte",
    description="Prüft, ob Statuswerte zur konfigurierten Wertemenge gehören. Reine Schreibweise-/Alias-Abweichungen werden pro Spalte zu einem Sammelbefund gebündelt.",
    category="Validitaet_Status",
    dimension=DIM_VALIDITY,
)
def rule_status(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    allowed = cfg.allowed_values
    aliases = cfg.value_aliases
    for sheet_key, field_name, key_in_cfg, cat in STATUS_FIELDS:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        allowed_set = {str(v).upper().strip() for v in allowed.get(key_in_cfg, [])}
        if not allowed_set:
            continue
        alias_map = {k.upper(): v for k, v in aliases.get(key_in_cfg, {}).items()}
        col = sheet.df[field_name]
        total = int(col.map(lambda v: not is_missing(v)).sum())
        case_items: list[tuple[int, object, str]] = []
        alias_items: list[tuple[int, object, str]] = []
        invalid_items: list[tuple[int, object]] = []
        for i, raw in col.items():
            if is_missing(raw):
                continue
            up = norm_upper(raw)
            if up in allowed_set:
                if str(raw).strip() != up:            # nur Groß-/Kleinschreibung
                    case_items.append((int(i), raw, up))
                continue
            if up in alias_map:                        # bekannter Alias
                alias_items.append((int(i), raw, alias_map[up]))
                continue
            invalid_items.append((int(i), raw))        # echter unbekannter Wert

        yield from _emit_normalization(
            sheet, field_name, cat, "Groß-/Kleinschreibung", "CASE", case_items, total,
            msg_fn=lambda r, t: f"Wert '{r}' entspricht dem Standard, ist aber nicht normiert ({t}).",
            expl="Der Wert ist zulässig, aber in abweichender Groß-/Kleinschreibung erfasst.",
            impact="Erschwert maschinelle Vergleiche und kann zu doppelten Buckets in Reports führen.",
            cause="Manuelle Eingabe ohne Normierung.",
            corr_fn=lambda r, t: f"Wert auf '{t}' normieren.")
        yield from _emit_normalization(
            sheet, field_name, cat, "Alias-Wert", "ALIAS", alias_items, total,
            msg_fn=lambda r, t: f"Wert '{r}' ist bekannt als Alias von '{t}'.",
            expl="Der Wert wird laut Governance-Alias-Tabelle als Standardwert interpretiert.",
            impact="Berichte und Filter zeigen den Wert ggf. doppelt.",
            cause="Fach- oder lokalsprachliche Erfassung ohne Normierung.",
            corr_fn=lambda r, t: f"Wert auf '{t}' standardisieren.")

        # echte unbekannte Werte bleiben als Einzelbefunde (brauchen fachliche Prüfung)
        ids = _record_ids_for(sheet) if invalid_items else []
        severity = SEVERITY_HIGH if field_name in ("hs_status", "Status", "MMSTA") else SEVERITY_MEDIUM
        for idx, raw in invalid_items:
            yield Finding(
                rule_id=f"VALID_{sheet_key}_{field_name}",
                rule_name=f"Ungültiger Wert in '{field_name}'",
                category=cat, dimension=DIM_VALIDITY, system=sheet.system,
                file=sheet.source_file, sheet=sheet.sheet_name, row=sheet.excel_row(int(idx)),
                field_name=field_name, value=raw, record_id=ids[idx] if idx < len(ids) else None,
                message=f"Wert '{raw}' ist für Feld '{field_name}' nicht zulässig.",
                severity=severity,
                explanation=(f"Der Wert '{raw}' entspricht weder der Standardliste {sorted(allowed_set)} "
                             "noch einem bekannten Alias. Tippfehler oder nicht gepflegte Werte wahrscheinlich."),
                business_impact=("Ungültige Status können dazu führen, dass Produkte fälschlich "
                                 "ausgeblendet oder weiterhin angeboten werden."),
                cause="Manuelle Eingabe ohne Validierung oder nicht gepflegte Mapping-Regel.",
                correction_suggestion=(f"Wert fachlich prüfen und auf einen der zulässigen Werte korrigieren: {sorted(allowed_set)}."),
                correction_type="Manuelle_Pruefung", confidence="wahrscheinlich",
            )


@registry.register(
    rule_id="VALIDITY_PRICE",
    name="Plausible Preiswerte",
    description="Preise müssen numerisch, nicht negativ und nicht übermäßig hoch sein.",
    category="Validitaet_Preis",
    dimension=DIM_VALIDITY,
)
def rule_price(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    for sheet_key, field_name, cat in PRICE_FIELDS:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            if is_missing(raw):
                continue
            val = norm_price(raw)
            if val is None:
                yield _price_finding(sheet, int(i), field_name, raw, cat,
                                     "ist kein gültiger Zahlenwert",
                                     SEVERITY_HIGH,
                                     "Preis als Zahl nachtragen (Dezimaltrennung prüfen).")
                continue
            if val < 0:
                yield _price_finding(sheet, int(i), field_name, raw, cat,
                                     f"ist negativ ({val}).", SEVERITY_HIGH,
                                     "Preis prüfen - negative Preise sind nicht zulässig.")
            elif val == 0:
                yield _price_finding(sheet, int(i), field_name, raw, cat,
                                     "beträgt 0.", SEVERITY_MEDIUM,
                                     "Nullpreise fachlich prüfen (kostenlos? oder Daten fehlen?)")
            elif val > 10_000_000:
                yield _price_finding(sheet, int(i), field_name, raw, cat,
                                     f"ist ungewöhnlich hoch ({val:,.0f}).", SEVERITY_MEDIUM,
                                     "Wert plausibilisieren - evtl. falsche Dezimalstelle.")


def _price_finding(sheet, idx, field_name, raw, cat, msg_tail, severity, correction) -> Finding:
    return Finding(
        rule_id=f"VALID_PRICE_{sheet.key}_{field_name}",
        rule_name="Preis-Plausibilität",
        category=cat,
        dimension=DIM_VALIDITY,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(idx),
        field_name=field_name,
        value=raw,
        record_id=_record_id(sheet, idx),
        message=f"Preis '{raw}' im Feld '{field_name}' {msg_tail}",
        severity=severity,
        explanation=(
            "Preise sollen numerisch, nicht negativ und in einem plausiblen Bereich liegen. "
            "Unplausible Werte deuten auf Erfassungsfehler oder falsche Einheiten hin."
        ),
        business_impact=(
            "Falsche Preise können zu fehlerhaften Angeboten, falschen Katalogpreisen "
            "und Verlusten im Vertrieb führen."
        ),
        cause="Erfassungsfehler, falsche Dezimaltrennung oder falsche Einheit.",
        correction_suggestion=correction,
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
    )


@registry.register(
    rule_id="VALIDITY_CURRENCY",
    name="Zulässige Währungen",
    description="Währungen müssen ISO-4217 entsprechen (siehe governance.yaml).",
    category="Validitaet_Allgemein",
    dimension=DIM_VALIDITY,
)
def rule_currency(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    allowed = {c.upper() for c in cfg.allowed_currencies}
    for sheet_key, field_name in CURRENCY_FIELDS:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            if is_missing(raw):
                continue
            norm = norm_currency(raw)
            if norm not in allowed:
                yield Finding(
                    rule_id=f"VALID_CUR_{sheet.key}_{field_name}",
                    rule_name="Ungültige Währung",
                    category="Validitaet_Allgemein",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"Währung '{raw}' ist nicht in der zulässigen Liste {sorted(allowed)}.",
                    severity=SEVERITY_MEDIUM,
                    explanation=(
                        "Nicht-ISO-konforme Währungen (z. B. 'EURO' statt 'EUR') verhindern den "
                        "automatischen Datenabgleich zwischen Systemen."
                    ),
                    business_impact=(
                        "Preise können fehlerhaft konvertiert oder nicht richtig verglichen werden."
                    ),
                    cause="Manueller Export oder abweichende Erfassungskonvention.",
                    correction_suggestion=(
                        f"Auf ISO-4217 normieren - z. B. '{raw}' → '{norm if norm else 'EUR'}'."
                    ),
                    correction_type="Sichere_Korrektur" if norm in allowed else "Vorschlag",
                    confidence="sicher" if norm in allowed else "wahrscheinlich",
                )


@registry.register(
    rule_id="VALIDITY_UNIT",
    name="Zulässige Mengeneinheiten",
    description="Mengeneinheiten müssen konfigurierter Liste entsprechen.",
    category="Validitaet_Allgemein",
    dimension=DIM_VALIDITY,
)
def rule_unit(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    allowed = {u.upper() for u in cfg.allowed_units}
    # fachlich bekannte Mapping-Vorschläge
    aliases = {"STUECK": "ST", "STÜCK": "ST", "STK": "ST", "STUECKS": "ST"}
    for sheet_key, field_name in UNIT_FIELDS:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        col = sheet.df[field_name]
        total = int(col.map(lambda v: not is_missing(v)).sum())
        known_items: list[tuple[int, object, str]] = []   # bekannter Alias -> aggregierbar
        unknown_items: list[tuple[int, object]] = []       # unbekannt -> Einzelbefund
        for i, raw in col.items():
            if is_missing(raw):
                continue
            up = norm_upper(raw)
            if up in allowed:
                continue
            suggestion = aliases.get(up)
            if suggestion:
                known_items.append((int(i), raw, suggestion))
            else:
                unknown_items.append((int(i), raw))

        yield from _emit_normalization(
            sheet, field_name, "Validitaet_Allgemein", "Mengeneinheit", "UNIT", known_items, total,
            msg_fn=lambda r, t: f"Mengeneinheit '{r}' ist nicht standardisiert (→ '{t}').",
            expl=f"Abweichende Einheiten erschweren den Vergleich zwischen Systemen. Erwartet: {sorted(allowed)}.",
            impact="Fehlerhafte Lagerbestände oder Preisberechnungen bei systemübergreifendem Vergleich möglich.",
            cause="Fach- oder Lokalsprachliche Erfassung ohne Einheiten-Mapping.",
            corr_fn=lambda r, t: f"Auf '{t}' standardisieren.")

        ids = _record_ids_for(sheet) if unknown_items else []
        for idx, raw in unknown_items:
            yield Finding(
                rule_id=f"VALID_UNIT_{sheet.key}_{field_name}",
                rule_name="Ungültige Mengeneinheit",
                category="Validitaet_Allgemein", dimension=DIM_VALIDITY, system=sheet.system,
                file=sheet.source_file, sheet=sheet.sheet_name, row=sheet.excel_row(int(idx)),
                field_name=field_name, value=raw, record_id=ids[idx] if idx < len(ids) else None,
                message=f"Mengeneinheit '{raw}' ist nicht standardisiert.",
                severity=SEVERITY_LOW,
                explanation=f"Abweichende Einheiten erschweren den Vergleich zwischen Systemen. Erwartet: {sorted(allowed)}.",
                business_impact="Fehlerhafte Lagerbestände oder Preisberechnungen bei systemübergreifendem Vergleich möglich.",
                cause="Fach- oder Lokalsprachliche Erfassung ohne Einheiten-Mapping.",
                correction_suggestion=f"Auf eine der Standardeinheiten mappen: {sorted(allowed)}.",
                correction_type="Vorschlag", confidence="wahrscheinlich",
            )


@registry.register(
    rule_id="VALIDITY_EMAIL",
    name="Plausibles E-Mail-Format",
    description="E-Mail-Adressen müssen ein plausibles Format haben.",
    category="Validitaet_Allgemein",
    dimension=DIM_VALIDITY,
)
def rule_email(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    for sheet_key, field_name in EMAIL_FIELDS:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            if is_missing(raw):
                continue
            s = strip_str(raw) or ""
            if not EMAIL_RX.match(s):
                yield Finding(
                    rule_id=f"VALID_EMAIL_{sheet.key}",
                    rule_name="Ungültiges E-Mail-Format",
                    category="Validitaet_Allgemein",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"E-Mail '{raw}' ist formal ungültig.",
                    severity=SEVERITY_LOW,
                    explanation="Die E-Mail entspricht nicht dem erwarteten Muster.",
                    business_impact="Automatisierte Kommunikation (Newsletter, Service-Updates) schlägt fehl.",
                    cause="Erfassungsfehler oder Platzhalterwert.",
                    correction_suggestion="Korrekte E-Mail-Adresse erfassen.",
                    correction_type="Manuelle_Pruefung",
                    confidence="sicher",
                )


@registry.register(
    rule_id="VALIDITY_COUNTRY",
    name="Plausibles Länder-Feld",
    description="Länder müssen auf einen bekannten Standardnamen abbildbar sein.",
    category="Validitaet_Allgemein",
    dimension=DIM_VALIDITY,
)
def rule_country(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    from ..normalize import COUNTRY_TO_REGION
    country_fields = [
        ("SF_Account", "BillingCountry"),
        ("SF_Contact", "MailingCountry"),
    ]
    for sheet_key, field_name in country_fields:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            if is_missing(raw):
                continue
            norm = norm_country(raw)
            if not norm or norm not in COUNTRY_TO_REGION:
                yield Finding(
                    rule_id=f"VALID_COUNTRY_{sheet.key}",
                    rule_name="Land nicht standardisiert",
                    category="Validitaet_Allgemein",
                    dimension=DIM_VALIDITY,
                    system=sheet.system,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"Land '{raw}' kann keiner Region zugeordnet werden.",
                    severity=SEVERITY_LOW,
                    explanation=(
                        "Das Land ist weder als ISO-Code noch als Standardname erkannt worden. "
                        "Markt- und Regions-Reports werden dadurch unvollständig."
                    ),
                    business_impact="Regionale Auswertungen enthalten Lücken oder falsche Gruppierungen.",
                    cause="Uneinheitliche Länderbezeichnungen über Systeme hinweg.",
                    correction_suggestion="Auf ISO-Bezeichnung oder Standard-Englisch standardisieren.",
                    correction_type="Vorschlag",
                    confidence="wahrscheinlich",
                )


def _record_id(sheet: LoadedSheet, idx: int):
    for cand in ("MATNR", "Id", "hs_object_id", "WorkOrderNumber", "SerialNumber"):
        if cand in sheet.df.columns:
            v = sheet.df.iloc[idx][cand]
            if not is_missing(v):
                return str(v).strip()
    return None
