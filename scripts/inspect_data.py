"""Quick structural inspection of the four AgroTechNova Excel files.

Prints each sheet's real header (auto-detected), row count and a short sample.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "input"

FILES = [
    "AgroTechNova_Stammdaten_SAP-MARC_dirty.xlsx",
    "AgroTechNova_Produktdaten_HubSpot_dirty.xlsx",
    "AgroTechNova_Produktdaten_Salesforce_dirty.xlsx",
    "AgroTechNova_Service_Salesforce_dirty.xlsx",
]


def detect_header_row(raw: pd.DataFrame, max_scan: int = 15) -> int:
    """Return the row index (0-based) that looks like the column header.

    Heuristic: the row with the most non-empty, mostly unique string cells.
    """
    best_idx = 0
    best_score = -1
    for i in range(min(max_scan, len(raw))):
        row = raw.iloc[i]
        non_null = row.dropna()
        if len(non_null) < 3:
            continue
        strings = [v for v in non_null if isinstance(v, str)]
        if len(strings) < max(3, len(non_null) * 0.6):
            continue
        uniq_ratio = len(set(strings)) / max(1, len(strings))
        score = len(strings) + uniq_ratio
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def main() -> None:
    for name in FILES:
        path = DATA / name
        print("\n" + "=" * 90)
        print(f"FILE: {name}  ({path.stat().st_size // 1024} KB)")
        print("=" * 90)
        xl = pd.ExcelFile(path)
        print(f"Sheets: {xl.sheet_names}")
        for sheet in xl.sheet_names:
            raw = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object)
            header_row = detect_header_row(raw)
            df = pd.read_excel(xl, sheet_name=sheet, header=header_row, dtype=object)
            df = df.dropna(how="all")
            print(f"\n  Sheet: {sheet!r}  header_row={header_row}  rows={len(df)}  cols={len(df.columns)}")
            cols = [str(c) for c in df.columns if not str(c).startswith("Unnamed")]
            print(f"  Columns: {cols}")
            if len(df):
                sample = df.head(2).to_dict(orient="records")
                for row in sample:
                    short = {}
                    for k, v in row.items():
                        if str(k).startswith("Unnamed"):
                            continue
                        s = str(v)
                        short[k] = s[:50] + ("…" if len(s) > 50 else "")
                    print(f"  Row: {short}")


if __name__ == "__main__":
    main()
