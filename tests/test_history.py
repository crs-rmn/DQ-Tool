"""Tests für Historie und Diff."""
from __future__ import annotations

from atn_dq.engine import run_analysis
from atn_dq.history import HistoryDB
from atn_dq.score import overall_score


def test_history_save_and_diff(tmp_path, pkg, cfg):
    db = HistoryDB(tmp_path / "hist.sqlite")
    result = run_analysis(pkg, cfg)
    ov = overall_score(result.findings, pkg, cfg)
    run1 = db.save_run(result.findings, ov.total_records, result.rule_count, ov.score, notes="first")
    # Simulate "fixed" state: 2. Lauf ohne die ersten 10 Befunde
    fewer = result.findings[10:]
    run2 = db.save_run(fewer, ov.total_records, result.rule_count, ov.score, notes="second")
    runs = db.list_runs()
    assert len(runs) == 2
    diff = db.diff(run1, run2)
    assert len(diff["resolved_or_unseen"]) >= 10
    assert len(diff["still_open"]) >= 1
