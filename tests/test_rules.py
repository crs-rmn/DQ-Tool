"""Smoke-Tests für die Regel-Engine mit den echten Excel-Dateien."""
from __future__ import annotations

from atn_dq.engine import run_analysis
from atn_dq.finding import (
    DIM_COMPLETENESS, DIM_VALIDITY, DIM_UNIQUENESS, DIM_CONSISTENCY, DIM_REFERENCE,
)
from atn_dq.rules import registry
from atn_dq.score import overall_score, region_scores


def test_engine_runs_without_error(pkg, cfg):
    result = run_analysis(pkg, cfg)
    assert result.rule_count > 0
    assert len(result.findings) > 0


def test_all_main_dimensions_have_findings(pkg, cfg):
    result = run_analysis(pkg, cfg)
    dims = {f.dimension for f in result.findings}
    assert DIM_COMPLETENESS in dims
    assert DIM_VALIDITY in dims
    assert DIM_UNIQUENESS in dims
    assert DIM_CONSISTENCY in dims
    assert DIM_REFERENCE in dims


def test_finding_mandatory_fields_populated(pkg, cfg):
    result = run_analysis(pkg, cfg)
    sample = result.findings[0]
    assert sample.file
    assert sample.sheet
    assert sample.row > 0
    assert sample.field_name
    assert sample.message
    assert sample.severity in ("hoch", "mittel", "niedrig")
    assert sample.priority_label in ("Hoch", "Mittel", "Niedrig")
    assert 0 <= sample.priority_score <= 100


def test_price_cross_system_rule_catches_known_mismatch(pkg, cfg):
    result = run_analysis(pkg, cfg)
    cross_price = [f for f in result.findings if f.rule_id == "CONS_PRICE_CROSS"]
    assert len(cross_price) > 0, "Erwartet mindestens einen Preis-Abgleich-Befund"


def test_region_scores_cover_known_markets(pkg, cfg):
    result = run_analysis(pkg, cfg)
    regions = {r.region for r in region_scores(result.findings, pkg, cfg)}
    # Daten umfassen mindestens DACH, Benelux, Osteuropa
    assert "DACH" in regions
    assert "Benelux" in regions


def test_overall_score_is_within_range(pkg, cfg):
    result = run_analysis(pkg, cfg)
    ov = overall_score(result.findings, pkg, cfg)
    assert 0 <= ov.score <= 100
    assert ov.findings_high + ov.findings_medium + ov.findings_low == len(result.findings)


def test_rule_registry_has_expected_rules():
    rule_ids = {r.rule_id for r in registry.all()}
    expected = {
        "COMPLETENESS_MANDATORY",
        "UNIQUENESS_KEYS",
        "VALIDITY_STATUS",
        "VALIDITY_PRICE",
        "CONSISTENCY_SAP_MATNR_IN_CRM",
        "CONSISTENCY_PRODUCT_NAME",
        "CONSISTENCY_PRICE_CROSS_SYSTEM",
        "REFERENCE_CONTACT_ACCOUNT",
        "REFERENCE_ASSET_ACCOUNT",
        "REFERENCE_WORKORDER_ASSET",
        "TEMPORAL_DATE_RANGE",
        "ANOMALY_PRICE_OUTLIER",
    }
    assert expected.issubset(rule_ids), f"Fehlend: {expected - rule_ids}"
