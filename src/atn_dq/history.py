"""SQLite-basierte Analysehistorie.

Speichert pro Analyse-Lauf einen Zusammenfassungs-Datensatz sowie alle Befunde,
damit spätere Läufe mit dem vorigen verglichen werden können.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .finding import Finding


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    total_records INTEGER NOT NULL,
    rule_count INTEGER NOT NULL,
    overall_score REAL NOT NULL,
    findings_high INTEGER NOT NULL,
    findings_medium INTEGER NOT NULL,
    findings_low INTEGER NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    finding_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    system TEXT,
    file TEXT,
    sheet TEXT,
    row INTEGER,
    field_name TEXT,
    severity TEXT,
    category TEXT,
    priority_label TEXT,
    priority_score REAL,
    country TEXT,
    region TEXT,
    status TEXT,
    message TEXT,
    payload TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_rule ON findings(rule_id);
"""


@dataclass
class RunSummary:
    run_id: int
    run_time: str
    total_records: int
    rule_count: int
    overall_score: float
    findings_high: int
    findings_medium: int
    findings_low: int
    notes: str | None = None


class HistoryDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            if not self._initialized:
                conn.executescript(SCHEMA)
                self._initialized = True
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_run(self, findings: list[Finding], total_records: int,
                 rule_count: int, overall_score: float, notes: str | None = None) -> int:
        with self._conn() as conn:
            cur = conn.cursor()
            sev = {"hoch": 0, "mittel": 0, "niedrig": 0}
            for f in findings:
                sev[f.severity] = sev.get(f.severity, 0) + 1
            cur.execute(
                "INSERT INTO runs (run_time, total_records, rule_count, overall_score,"
                " findings_high, findings_medium, findings_low, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), total_records, rule_count,
                 overall_score, sev["hoch"], sev["mittel"], sev["niedrig"], notes),
            )
            run_id = int(cur.lastrowid)
            for f in findings:
                payload = {k: v for k, v in asdict(f).items() if k not in {
                    "rule_id", "system", "file", "sheet", "row", "field_name",
                    "severity", "category", "priority_label", "priority_score",
                    "country", "region", "status", "message",
                }}
                cur.execute(
                    "INSERT INTO findings (run_id, finding_id, rule_id, system, file,"
                    " sheet, row, field_name, severity, category, priority_label,"
                    " priority_score, country, region, status, message, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, f.finding_id, f.rule_id, f.system, f.file, f.sheet, f.row,
                     f.field_name, f.severity, f.category, f.priority_label, f.priority_score,
                     f.country, f.region, f.status, f.message,
                     json.dumps(payload, default=str, ensure_ascii=False)),
                )
            return run_id

    def list_runs(self) -> list[RunSummary]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT run_id, run_time, total_records, rule_count, overall_score,"
                " findings_high, findings_medium, findings_low, notes FROM runs "
                "ORDER BY run_id DESC"
            ).fetchall()
        return [RunSummary(*r) for r in rows]

    def diff(self, old_run_id: int, new_run_id: int) -> dict:
        with self._conn() as conn:
            old_ids = {r[0] for r in conn.execute(
                "SELECT finding_id FROM findings WHERE run_id = ?", (old_run_id,))}
            new_ids = {r[0] for r in conn.execute(
                "SELECT finding_id FROM findings WHERE run_id = ?", (new_run_id,))}
        return {
            "resolved_or_unseen": sorted(old_ids - new_ids),
            "new": sorted(new_ids - old_ids),
            "still_open": sorted(old_ids & new_ids),
        }
