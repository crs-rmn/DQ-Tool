"""Tests für Export - prüft Pflichtspalten gemäß Hackathon-Briefing."""
from __future__ import annotations

import pandas as pd

from atn_dq.engine import run_analysis
from atn_dq.export import REQUIRED_COLUMNS, export_csv, export_xlsx, findings_to_dataframe


def test_dataframe_contains_mandatory_columns(pkg, cfg):
    result = run_analysis(pkg, cfg)
    df = findings_to_dataframe(result.findings)
    for col in REQUIRED_COLUMNS:
        assert col in df.columns, f"Pflichtspalte '{col}' fehlt im Export"


def test_dataframe_severity_values(pkg, cfg):
    result = run_analysis(pkg, cfg)
    df = findings_to_dataframe(result.findings)
    assert set(df["Schweregrad"]).issubset({"hoch", "mittel", "niedrig"})


def test_csv_export_roundtrip(tmp_path, pkg, cfg):
    result = run_analysis(pkg, cfg)
    path = export_csv(result.findings, tmp_path / "out.csv")
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
    for col in REQUIRED_COLUMNS:
        assert col in df.columns
    assert len(df) == len(result.findings)


def test_xlsx_export_creates_file(tmp_path, pkg, cfg):
    result = run_analysis(pkg, cfg)
    path = export_xlsx(result.findings, tmp_path / "out.xlsx")
    assert path.exists()
    assert path.stat().st_size > 0
