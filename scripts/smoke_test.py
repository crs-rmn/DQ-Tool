"""Smoke-Test: Lädt Daten, führt alle Regeln aus und druckt eine Zusammenfassung."""
from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from atn_dq.config import load_config
from atn_dq.engine import run_analysis
from atn_dq.loader import load_package
from atn_dq.score import overall_score, region_scores

logging.basicConfig(level=logging.INFO)


def main() -> None:
    cfg = load_config(ROOT / "config")
    pkg = load_package(ROOT / "data" / "input")
    print(f"Geladene Tabellen: {list(pkg.keys())}")
    for key, sheet in pkg.sheets.items():
        print(f"  {key:20s}: {len(sheet.df):5d} rows, {len(sheet.df.columns):3d} cols")

    result = run_analysis(pkg, cfg)
    print(f"\nBefunde insgesamt: {len(result.findings)} (Regeln ausgeführt: {result.rule_count})")

    sev = Counter(f.severity for f in result.findings)
    prio = Counter(f.priority_label for f in result.findings)
    cat = Counter(f.category for f in result.findings)
    rules = Counter(f.rule_id for f in result.findings)

    print("\n== Nach Schweregrad ==")
    for s in ("hoch", "mittel", "niedrig"):
        print(f"  {s:10s}: {sev.get(s, 0)}")
    print("\n== Nach Priorität ==")
    for p in ("Hoch", "Mittel", "Niedrig"):
        print(f"  {p:10s}: {prio.get(p, 0)}")
    print("\n== Top-10 Regeln nach Anzahl ==")
    for rid, n in rules.most_common(10):
        print(f"  {rid:40s}: {n}")
    print("\n== Top-10 Kategorien ==")
    for c, n in cat.most_common(10):
        print(f"  {c:30s}: {n}")

    ov = overall_score(result.findings, pkg, cfg)
    print(f"\nGesamt-Score: {ov.score}")
    for dim, s in ov.by_dimension.items():
        print(f"  {dim:30s}: {s}")

    print("\n== Regionen ==")
    for rs in region_scores(result.findings, pkg, cfg):
        score_s = f"{rs.score:5.1f}" if rs.sufficient_data else "  n/a"
        print(f"  {rs.region:20s}  Score: {score_s}  "
              f"Hoch={rs.findings_high:3d}  Mittel={rs.findings_medium:3d}  Niedrig={rs.findings_low:3d}  "
              f"Datensätze≈{rs.records_estimated}")

    print("\n== Top-5 Befunde nach Priorität ==")
    for f in result.findings[:5]:
        print(f"  [{f.priority_label:6s} {f.priority_score:5.1f}] {f.rule_name} | {f.sheet} Z{f.row} | {f.message[:120]}")


if __name__ == "__main__":
    main()
