"""Eindeutigkeits-Regeln: Primärschlüssel und fachliche Schlüssel sind einzigartig."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_UNIQUENESS, SEVERITY_HIGH, SEVERITY_MEDIUM
from ..loader import DataPackage, LoadedSheet
from ..normalize import is_missing, norm_matnr, norm_name, strip_str
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


@registry.register(
    rule_id="UNIQUENESS_ACCOUNT_NAME",
    name="Mögliche Kunden-Dubletten (gleicher Name)",
    description=("Findet Accounts mit identischem Namen (schreibweisen-normalisiert). "
                 "Die Account-Id ist systemgeneriert und immer eindeutig - doppelte Kunden "
                 "erkennt man nur über Name/Ort."),
    category="Eindeutigkeit",
    dimension=DIM_UNIQUENESS,
)
def rule_duplicate_accounts(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    """Dublettenverdacht bei Kunden: gleicher normalisierter Name (optional + Ort/PLZ).

    Adressiert die Stimme aus Customer Success ("manche Kunden gibt es mehrfach").
    Severity mittel + manuelle Prüfung, weil ein gleicher Name selten auch legitim sein kann.
    """
    acc = pkg.get("SF_Account")
    if acc is None or "Name" not in acc.df.columns:
        return
    df = acc.df
    has_city = "BillingCity" in df.columns

    # Normierten Schlüssel je Zeile bilden (Name, optional + Ort)
    keys: list[str | None] = []
    for i in range(len(df)):
        name = norm_name(df["Name"].iloc[i])
        if not name:
            keys.append(None)
            continue
        if has_city:
            city = norm_name(df["BillingCity"].iloc[i]) or ""
            keys.append(f"{name}|{city}")
        else:
            keys.append(name)

    import pandas as pd
    key_series = pd.Series(keys, index=df.index)
    counts = key_series.value_counts(dropna=True)
    dup_keys = set(counts[counts > 1].index)
    if not dup_keys:
        return

    id_col = df["Id"] if "Id" in df.columns else None
    for pos, (idx, key) in enumerate(key_series.items()):
        if key is None or key not in dup_keys:
            continue
        name_raw = strip_str(df["Name"].iloc[pos]) or ""
        city_raw = strip_str(df["BillingCity"].iloc[pos]) if has_city else None
        n = int(counts[key])
        where = f" in {city_raw}" if city_raw else ""
        rec = strip_str(id_col.iloc[pos]) if id_col is not None else None
        yield Finding(
            rule_id="UNIQUE_SF_Account_Name",
            rule_name="Mögliche Kunden-Dublette",
            category="Eindeutigkeit",
            dimension=DIM_UNIQUENESS,
            system=acc.system,
            file=acc.source_file,
            sheet=acc.sheet_name,
            row=acc.excel_row(int(pos)),
            field_name="Name" + ("+BillingCity" if has_city else ""),
            value=name_raw,
            record_id=rec,
            message=f"Kunde '{name_raw}'{where} kommt {n}-mal vor (gleicher Name).",
            severity=SEVERITY_MEDIUM,
            explanation=(
                "Mehrere Accounts tragen denselben Namen (schreibweisen-unabhängig). "
                "Da die Account-Id systemseitig immer eindeutig ist, bleiben solche Dubletten "
                "sonst unentdeckt - der Kunde existiert dann faktisch mehrfach."
            ),
            business_impact=(
                "Kunden erhalten Post doppelt oder gar nicht, Umsätze verteilen sich auf mehrere "
                "Datensätze und Marktberichte zeigen ein falsches Bild."
            ),
            cause="Kunde wurde mehrfach angelegt (z. B. durch unterschiedliche Erfassende/Importe).",
            correction_suggestion=(
                "Datensätze fachlich prüfen und zu einem Golden Record zusammenführen. "
                "Vor dem Zusammenführen Adressen und Ansprechpartner abgleichen."
            ),
            correction_type="Manuelle_Pruefung",
            confidence="wahrscheinlich",
            tags=["dublette", "kunde"],
        )
