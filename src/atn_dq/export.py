"""Export der Befundliste (CSV + Excel) mit den Pflichtspalten aus dem Briefing."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pandas as pd

from .finding import Finding


# Pflichtspalten laut Briefing
REQUIRED_COLUMNS = ["Datei", "Blatt", "Zeile", "Feld", "Befund", "Schweregrad"]


def findings_to_dataframe(findings: list[Finding]) -> pd.DataFrame:
    rows = [f.to_export_row() for f in findings]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    # Pflichtspalten zuerst, dann Rest
    rest = [c for c in df.columns if c not in REQUIRED_COLUMNS]
    df = df[REQUIRED_COLUMNS + rest]
    df["Analysezeitpunkt"] = datetime.now().isoformat(timespec="seconds")
    return df


def export_csv(findings: list[Finding], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = findings_to_dataframe(findings)
    # BOM für Excel-Kompatibilität (deutsches Excel)
    df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")
    return path


def export_xlsx(findings: list[Finding], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = findings_to_dataframe(findings)
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Befunde", index=False)
        workbook = writer.book
        ws = writer.sheets["Befunde"]
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#F2F2F2", "border": 1,
            "align": "left", "valign": "vcenter", "text_wrap": True,
        })
        for col_idx, name in enumerate(df.columns):
            ws.write(0, col_idx, name, header_fmt)
            # auto-width (vereinfacht)
            width = min(60, max(12, int(df[name].astype(str).map(len).max() if len(df) else 12) + 2))
            ws.set_column(col_idx, col_idx, width)
        ws.freeze_panes(1, 0)
        if len(df):
            ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    return path
