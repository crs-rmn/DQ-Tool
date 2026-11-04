"""Tests für Upload-basiertes Laden (Streamlit-Drag-and-Drop)."""
from __future__ import annotations

from pathlib import Path

from atn_dq.loader import load_bytes, load_package


ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "data" / "input"


def test_load_bytes_equivalent_to_load_file():
    sample = next(p for p in INPUT_DIR.glob("AgroTechNova_Produktdaten_HubSpot_*.xlsx")
                  if not p.name.startswith("~$"))
    data = sample.read_bytes()
    from_bytes = load_bytes(data, sample.name)
    assert "HS_Products" in from_bytes
    assert len(from_bytes["HS_Products"].df) > 0


def test_load_package_merges_folder_and_uploads(tmp_path):
    # tmp_path leer, uploads simulieren vollständige Datei
    sample = next(p for p in INPUT_DIR.glob("AgroTechNova_Stammdaten_SAP-MARC_*.xlsx")
                  if not p.name.startswith("~$"))
    pkg = load_package(
        input_dir=tmp_path,
        extra_bytes=[(sample.name, sample.read_bytes())],
    )
    assert "SAP_FERT" in pkg.sheets
    assert pkg["SAP_FERT"].source_file == sample.name


def test_load_package_raises_when_empty(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="hochladen|data/input"):
        load_package(input_dir=tmp_path, require_any=True)


def test_load_package_no_require_when_empty(tmp_path):
    pkg = load_package(input_dir=tmp_path, require_any=False)
    assert len(pkg.sheets) == 0
