"""Tests für das Insights-Modul."""
from __future__ import annotations

from atn_dq.engine import run_analysis
from atn_dq.insights import (
    affected_record_count,
    build_recommendations,
    cause_groups,
    department_summary,
    priority_reason,
    recurring_patterns,
    simulate_resolution,
    unique_affected_records,
)


def test_affected_records_smaller_than_findings(pkg, cfg):
    result = run_analysis(pkg, cfg)
    unique = affected_record_count(result.findings)
    # Ein Datensatz hat oft mehrere Befunde
    assert unique > 0
    assert unique <= len(result.findings)


def test_unique_affected_records_is_set(pkg, cfg):
    result = run_analysis(pkg, cfg)
    s = unique_affected_records(result.findings)
    assert isinstance(s, set)
    assert len(s) == affected_record_count(result.findings)


def test_build_recommendations_returns_at_most_five(pkg, cfg):
    result = run_analysis(pkg, cfg)
    recs = build_recommendations(result.findings)
    assert 0 < len(recs) <= 5
    # Jede Empfehlung basiert auf echten Befunden
    for r in recs:
        assert r.count > 0
        assert r.title
        assert r.detail


def test_priority_reason_is_informative(pkg, cfg):
    result = run_analysis(pkg, cfg)
    sample = result.findings[0]
    reason = priority_reason(sample, cfg)
    assert len(reason) > 50
    assert sample.priority_label in reason  # Hoch/Mittel/Niedrig erwähnt


def test_cause_groups_only_multi_member_entries(pkg, cfg):
    result = run_analysis(pkg, cfg)
    groups = cause_groups(result.findings)
    for g in groups:
        assert len(g.members) >= 2
        assert g.primary is g.members[0] or g.primary == g.members[0]


def test_recurring_patterns_minimum_count(pkg, cfg):
    result = run_analysis(pkg, cfg)
    patterns = recurring_patterns(result.findings)
    for p in patterns:
        assert p.count >= 3
        assert p.unique_records >= 1


def test_department_summary_covers_all_findings(pkg, cfg):
    result = run_analysis(pkg, cfg)
    summaries = department_summary(result.findings)
    total = sum(s.total for s in summaries)
    assert total == len(result.findings)


def test_simulation_removes_given_ids(pkg, cfg):
    result = run_analysis(pkg, cfg)
    first_ids = {f.finding_id for f in result.findings[:5]}
    after = simulate_resolution(result.findings, first_ids)
    assert len(after) == len(result.findings) - 5
    assert all(f.finding_id not in first_ids for f in after)
