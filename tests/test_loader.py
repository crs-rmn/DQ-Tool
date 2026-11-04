"""Tests für den Excel-Lader."""
from __future__ import annotations

from atn_dq.loader import load_package


def test_loader_finds_all_expected_sheets(pkg):
    expected = {
        "SAP_FERT", "SAP_ERSA", "SAP_MARA",
        "HS_Products", "HS_PriceBooks", "HS_PriceBookItems",
        "SF_Product2", "SF_Pricebook2", "SF_PricebookEntry",
        "SF_Account", "SF_Contact", "SF_Asset", "SF_WorkOrder",
    }
    assert expected.issubset(set(pkg.keys())), f"Fehlend: {expected - set(pkg.keys())}"


def test_sap_sheets_have_matnr(pkg):
    for key in ("SAP_FERT", "SAP_ERSA", "SAP_MARA"):
        sheet = pkg[key]
        assert "MATNR" in sheet.df.columns
        assert len(sheet.df) > 0


def test_hs_products_has_sap_mapping_column(pkg):
    sheet = pkg["HS_Products"]
    assert "atn_sap_materialnummer" in sheet.df.columns


def test_sf_product2_has_sap_mapping(pkg):
    sheet = pkg["SF_Product2"]
    assert "ATN_SAP_Materialnummer__c" in sheet.df.columns


def test_excel_row_offset(pkg):
    sheet = pkg["SF_Account"]
    # Header_row + Kopfzeile selbst + Datenindex -> 1-basierte Excel-Zeile
    assert sheet.excel_row(0) == sheet.header_row + 2
