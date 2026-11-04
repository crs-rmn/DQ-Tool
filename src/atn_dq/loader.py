"""Excel-Lader für die AgroTechNova-Datenquellen.

Die Dateien enthalten pro Blatt eine Titelzeile vor dem eigentlichen Spaltenkopf.
Dieser Lader erkennt die Kopfzeile automatisch, entfernt leere Zeilen und liefert
ein einheitliches ``DataFrame`` je Blatt zurück.

Die Namen der Eingabeblätter werden auf interne Objektnamen gemappt, damit die
Regel-Engine unabhängig von der tatsächlichen Dateistruktur bleibt.

Eingangsquellen:
- Dateien im Ordner ``data/input/`` (``load_package``)
- Einzelne Dateien von Pfad (``load_file``)
- Hochgeladene Dateien aus der Streamlit-UI (``load_bytes``)
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd


# Mapping von erwarteten Datei-Hinweisen auf Systemnamen
SYSTEM_HINTS = {
    "SAP-MARC": "SAP",
    "SAP_MARC": "SAP",
    "SAP":      "SAP",
    "HubSpot":  "HubSpot",
    "Salesforce_Service": "Salesforce",
    "Service_Salesforce": "Salesforce",
    "Produktdaten_Salesforce": "Salesforce",
}

# Mapping (System, Blattname) -> interner Objektschlüssel
SHEET_KEY_MAP: dict[tuple[str, str], str] = {
    ("SAP", "Produkte (FERT)"):     "SAP_FERT",
    ("SAP", "Ersatzteile (ERSA)"):  "SAP_ERSA",
    ("SAP", "MARA"):                "SAP_MARA",
    ("HubSpot", "Products"):        "HS_Products",
    ("HubSpot", "Price Books"):     "HS_PriceBooks",
    ("HubSpot", "Price Book Items"): "HS_PriceBookItems",
    ("Salesforce_Products", "Product2"):      "SF_Product2",
    ("Salesforce_Products", "Pricebook2"):    "SF_Pricebook2",
    ("Salesforce_Products", "PricebookEntry"): "SF_PricebookEntry",
    ("Salesforce_Service", "Account"):   "SF_Account",
    ("Salesforce_Service", "Contact"):   "SF_Contact",
    ("Salesforce_Service", "Asset"):     "SF_Asset",
    ("Salesforce_Service", "WorkOrder"): "SF_WorkOrder",
}

# Blätter, die beim Laden immer ignoriert werden
IGNORE_SHEETS = {"Uebersicht", "Übersicht", "Feldlegende"}


@dataclass
class LoadedSheet:
    """Eine geladene Tabelle mit Herkunftsmetadaten."""

    key: str                 # z. B. 'SAP_FERT'
    system: str              # z. B. 'SAP'
    source_file: str         # Dateiname
    sheet_name: str          # Original-Blattname
    header_row: int          # 0-basiert
    df: pd.DataFrame = field(repr=False)

    # Für Rückverfolgung: Excel-Zeile = header_row + 1 (Kopfzeile) + df-Index + 1
    def excel_row(self, df_index: int) -> int:
        return int(self.header_row) + 2 + int(df_index)


@dataclass
class DataPackage:
    """Alle geladenen Tabellen eines Analyse-Laufs."""

    sheets: dict[str, LoadedSheet]
    analysis_time: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now())

    def __getitem__(self, key: str) -> LoadedSheet:
        return self.sheets[key]

    def get(self, key: str) -> LoadedSheet | None:
        return self.sheets.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self.sheets

    def keys(self) -> Iterable[str]:
        return self.sheets.keys()


def _detect_header_row(raw: pd.DataFrame, max_scan: int = 15) -> int:
    best_idx, best_score = 0, -1.0
    for i in range(min(max_scan, len(raw))):
        row = raw.iloc[i]
        non_null = row.dropna()
        if len(non_null) < 3:
            continue
        strings = [v for v in non_null if isinstance(v, str)]
        if len(strings) < max(3, len(non_null) * 0.6):
            continue
        uniq = len(set(strings)) / max(1, len(strings))
        score = len(strings) + uniq
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def _detect_subsystem(file_name: str) -> str:
    """Erkennt das Subsystem anhand des Dateinamens.

    Besonderheit: Salesforce-Dateien gibt es als "Produktdaten" und "Service".
    Für die Mapping-Tabelle benutzen wir zwei Varianten.
    """
    low = file_name.lower()
    if "sap" in low:
        return "SAP"
    if "hubspot" in low:
        return "HubSpot"
    if "service_salesforce" in low or "service-salesforce" in low:
        return "Salesforce_Service"
    if "produktdaten_salesforce" in low or "produktdaten-salesforce" in low:
        return "Salesforce_Products"
    if "salesforce" in low and "service" in low:
        return "Salesforce_Service"
    if "salesforce" in low:
        return "Salesforce_Products"
    return "Unbekannt"


def _system_label(subsystem: str) -> str:
    """Externer Systemname für die UI (SAP / Salesforce / HubSpot)."""
    if subsystem.startswith("Salesforce"):
        return "Salesforce"
    return subsystem


def _extract_sheets(xl: pd.ExcelFile, source_name: str) -> dict[str, LoadedSheet]:
    """Interne Helper-Funktion - extrahiert alle relevanten Blätter aus einer offenen Excel-Datei."""
    subsystem = _detect_subsystem(source_name)
    system = _system_label(subsystem)
    sheets: dict[str, LoadedSheet] = {}
    for sheet_name in xl.sheet_names:
        if sheet_name in IGNORE_SHEETS:
            continue
        raw = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
        if raw.empty:
            continue
        header_row = _detect_header_row(raw)
        df = pd.read_excel(xl, sheet_name=sheet_name, header=header_row, dtype=object)
        df = df.dropna(how="all").reset_index(drop=True)
        # verwerfe "Unnamed:"-Spalten (leere Excel-Spalten)
        keep = [c for c in df.columns if not str(c).startswith("Unnamed")]
        df = df[keep]
        df.columns = [str(c).strip() for c in df.columns]
        key = SHEET_KEY_MAP.get((subsystem, sheet_name))
        if key is None:
            key = f"{subsystem}_{sheet_name}".replace(" ", "_")
        sheets[key] = LoadedSheet(
            key=key, system=system, source_file=source_name,
            sheet_name=sheet_name, header_row=header_row, df=df,
        )
    return sheets


def load_file(path: str | Path) -> dict[str, LoadedSheet]:
    """Lädt eine einzelne Excel-Datei von Pfad."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")
    xl = pd.ExcelFile(path)
    return _extract_sheets(xl, path.name)


def load_bytes(data: bytes, source_name: str) -> dict[str, LoadedSheet]:
    """Lädt eine Excel-Datei aus Bytes (z. B. aus einem Streamlit-Upload).

    ``source_name`` sollte der Original-Dateiname sein, damit die
    System-Erkennung (SAP/HubSpot/Salesforce) funktioniert.
    """
    xl = pd.ExcelFile(io.BytesIO(data))
    return _extract_sheets(xl, source_name)


def load_package(
    input_dir: str | Path | None,
    extra_bytes: list[tuple[str, bytes]] | None = None,
    require_any: bool = True,
) -> DataPackage:
    """Lädt Excel-Dateien aus ``input_dir`` und optional zusätzliche Upload-Bytes.

    Parameters
    ----------
    input_dir : Pfad zum Verzeichnis mit Excel-Dateien. Kann ``None`` sein, wenn nur
        Upload-Bytes verwendet werden sollen.
    extra_bytes : Liste von (Dateiname, Byte-Inhalt). Später geladene Dateien
        überschreiben gleichnamige Tabellenkeys aus dem Verzeichnis.
    require_any : Wenn True, wirft eine Exception, falls insgesamt nichts geladen wurde.
    """
    merged: dict[str, LoadedSheet] = {}
    if input_dir is not None:
        input_dir = Path(input_dir)
        if input_dir.exists():
            files = sorted(p for p in input_dir.glob("*.xlsx") if not p.name.startswith("~$"))
            for f in files:
                merged.update(load_file(f))
    if extra_bytes:
        for name, data in extra_bytes:
            try:
                merged.update(load_bytes(data, name))
            except Exception as exc:  # defensive: einzelne kaputte Upload-Datei soll nicht alles blockieren
                raise ValueError(f"Datei '{name}' konnte nicht gelesen werden: {exc}") from exc
    if require_any and not merged:
        raise ValueError(
            f"Keine Excel-Dateien gefunden. Bitte Dateien in '{input_dir}' ablegen "
            "oder in der App hochladen."
        )
    return DataPackage(sheets=merged)
