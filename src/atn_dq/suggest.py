"""Automatische Regelvorschläge aus Datenmustern.

Arbeitet ohne feste Spaltennamen: Typen und Muster werden aus den Werten erkannt.
Vorschläge werden **nie automatisch aktiviert**; sie enthalten das beobachtete Muster,
Anzahl/Anteil, Beispiele und eine ehrliche Unsicherheitsangabe.

Schutz vor falschen Regeln:
- Mindestens ``min_rows`` nicht-leere Werte je Spalte (Standard 30).
- Zahlenbereiche werden nicht vorgeschlagen, wenn die Werte je Gruppe
  (andere Spalte mit wenigen Ausprägungen) stark auseinanderliegen.
- Freitextspalten (viele verschiedene Formen) bekommen keine Formatregel.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any

import pandas as pd

from .custom_rules import CustomRule
from .loader import DataPackage, LoadedSheet
from .normalize import is_missing, norm_price, strip_str

MIN_ROWS = 30


@dataclass
class Suggestion:
    sid: str
    sheet_key: str
    system: str
    sheet_name: str
    field: str
    kind: str                 # Vollständigkeit | Format | Erlaubte Werte | Wertebereich | Eindeutigkeit | Leerzeichen
    pattern: str              # beobachtetes Muster (Text)
    affected: int
    total: int
    examples: list[str]
    uncertainty: str
    confidence: str           # hoch | mittel | gering
    rule: CustomRule

    @property
    def share(self) -> float:
        return self.affected / self.total if self.total else 0.0


@dataclass
class Skipped:
    sheet: str
    field: str
    reason: str


def _shape(s: str) -> str:
    out = []
    for ch in s:
        out.append("9" if ch.isdigit() else ("A" if ch.isupper() else ("a" if ch.islower() else ch)))
    return "".join(out)


def _shape_to_regex(shape: str) -> str:
    parts, i = [], 0
    cls = {"9": r"\d", "A": "[A-Z]", "a": "[a-z]"}
    while i < len(shape):
        c = shape[i]
        j = i
        while j < len(shape) and shape[j] == c:
            j += 1
        n = j - i
        tok = cls.get(c, re.escape(c))
        parts.append(tok + (f"{{{n}}}" if n > 1 else ""))
        i = j
    return "".join(parts)


def _clean(v: Any) -> str | None:
    s = strip_str(v)
    if s is None:
        return None
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        s = s[:-2]
    return s


def _is_id_like(name: str) -> bool:
    n = name.lower()
    return n.endswith("id") or n.endswith("_id") or n in ("id",) or "number" in n


def _group_columns(df: pd.DataFrame, exclude: str) -> list[str]:
    out = []
    for c in df.columns:
        if c == exclude:
            continue
        vals = df[c].map(_clean).dropna()
        if len(vals) < MIN_ROWS:
            continue
        nun = vals.nunique()
        if 2 <= nun <= 15 and vals.value_counts().min() >= 3:
            out.append(c)
    return out


def _heterogeneous(df: pd.DataFrame, col: str, nums: pd.Series) -> str | None:
    """Gibt den Gruppennamen zurück, wenn die Werte je Gruppe stark auseinanderliegen."""
    pos = nums[nums > 0]
    if len(pos) < MIN_ROWS:
        return None
    logv = pos.map(math.log10)
    total_var = logv.var()
    if not total_var or math.isnan(total_var):
        return None
    for g in _group_columns(df.loc[pos.index], col):
        grp = df.loc[pos.index, g].map(_clean)
        means = logv.groupby(grp).transform("mean")
        eta2 = 1 - ((logv - means) ** 2).sum() / (((logv - logv.mean()) ** 2).sum() or 1)
        if eta2 > 0.5:
            return g
    return None


def _mk_rule(sheet: LoadedSheet, col: str, rtype: str, name: str, params: dict, rationale: str,
             severity: str = "mittel") -> CustomRule:
    return CustomRule(name=name, sheet_key=sheet.key, field=col, rule_type=rtype, severity=severity,
                      description="Automatisch vorgeschlagen aus Datenmustern - noch nicht geprüft.",
                      rationale=rationale, params=params, enabled=False)


def suggest_rules(pkg: DataPackage, existing: list[CustomRule] | None = None,
                  min_rows: int = MIN_ROWS) -> tuple[list[Suggestion], list[Skipped]]:
    existing = existing or []
    have = {(r.sheet_key, r.field, r.rule_type) for r in existing}
    sugg: list[Suggestion] = []
    skipped: list[Skipped] = []

    for key, sheet in pkg.sheets.items():
        df = sheet.df
        if len(df) < min_rows:
            continue
        for col in df.columns:
            raw = df[col]
            vals = raw.map(_clean)
            nn = vals.dropna()
            n_all = len(df)
            if len(nn) < min_rows:
                continue
            sid = f"{key}.{col}"
            num_series = nn.map(norm_price)
            numeric_share = num_series.notna().mean()
            looks_code = nn.str.fullmatch(r"\d{6,}").mean() >= 0.9   # lange Ziffernfolgen = Codes, keine Mengen
            is_numeric_col = numeric_share >= 0.9 and not _is_id_like(col) and not looks_code

            # 1) Vollständigkeit
            null_share = 1 - len(nn) / n_all
            if 0 < null_share <= 0.25 and (key, col, "completeness") not in have:
                miss = n_all - len(nn)
                conf = "hoch" if null_share <= 0.05 and miss >= 2 else "mittel"
                sugg.append(Suggestion(
                    f"{sid}:compl", key, sheet.system, sheet.sheet_name, col, "Vollständigkeit",
                    f"{col} ist zu {100 - null_share * 100:.1f} % befüllt, {miss} Werte fehlen.",
                    miss, n_all, [f"Zeile {sheet.excel_row(i)}" for i in df.index[vals.isna()][:3]],
                    "Das Feld könnte bewusst optional sein (z. B. nur für bestimmte Produkte).", conf,
                    _mk_rule(sheet, col, "completeness", f"{col} befüllt ({sheet.sheet_name})", {},
                             f"In {100 - null_share * 100:.0f} % der Datensätze ist {col} befüllt.")))

            # 2) Leerzeichen
            ws = nn[(raw.loc[nn.index].astype(str) != raw.loc[nn.index].astype(str).str.strip())]
            if len(ws) >= 1 and (key, col, "format") not in have and not is_numeric_col:
                sugg.append(Suggestion(
                    f"{sid}:ws", key, sheet.system, sheet.sheet_name, col, "Leerzeichen",
                    f"{len(ws)} Werte in {col} haben führende oder nachgestellte Leerzeichen.",
                    len(ws), len(nn), [repr(str(raw.loc[i])) for i in ws.index[:3]],
                    "Kosmetisch; kann Vergleiche und Dublettenprüfung stören.",
                    "hoch" if len(ws) >= 2 else "gering",
                    _mk_rule(sheet, col, "format", f"{col} ohne Leerzeichen am Rand", {"pattern": r"\S(.*\S)?"},
                             "Leerzeichen am Rand verhindern saubere Vergleiche.", "niedrig")))
                # ohne Rohwert-Strip prüft die Regel auf dem bereinigten Wert nicht -> nur Hinweis
                sugg[-1].rule.params["raw_check"] = True

            # 3) Format / erlaubte Werte / Bereich / Eindeutigkeit
            if is_numeric_col:
                _numeric_suggestions(sugg, skipped, sheet, key, col, df, nn, num_series, have, n_all)
            else:
                _text_suggestions(sugg, skipped, sheet, key, col, nn, have, n_all)
    sugg.sort(key=lambda s: ({"hoch": 0, "mittel": 1, "gering": 2}[s.confidence], -s.affected))
    return sugg, skipped


def _numeric_suggestions(sugg, skipped, sheet, key, col, df, nn, nums, have, n_all):
    if (key, col, "range") in have:
        return
    x = nums.dropna()
    if len(x) < MIN_ROWS:
        return
    pos_share = (x > 0).mean()
    neg = x[x < 0]
    q1, q3 = x.quantile(.25), x.quantile(.75)
    iqr = q3 - q1
    hetero = _heterogeneous(df, col, x.reindex(df.index))
    # a) negative / null Werte bei überwiegend positiven Zahlen
    if pos_share >= 0.97 and (x <= 0).sum() >= 1:
        bad = x[x <= 0]
        if hetero is None or True:  # Positivität gilt unabhängig von Gruppen
            sugg.append(Suggestion(
                f"{key}.{col}:pos", key, sheet.system, sheet.sheet_name, col, "Wertebereich",
                f"{pos_share * 100:.1f} % der Werte in {col} sind > 0, {len(bad)} sind ≤ 0.",
                len(bad), len(x), [str(v) for v in bad.head(3).tolist()],
                "Null oder Negativwerte können in Ausnahmefällen gewollt sein (z. B. Gutschriften).",
                "hoch" if len(bad) >= 2 else "mittel",
                _mk_rule(sheet, col, "range", f"{col} größer als 0", {"min": 0.0001},
                         f"{pos_share * 100:.0f} % der Werte sind positiv.")))
    # b) Ausreißer nach oben
    if iqr > 0 and len(x) >= MIN_ROWS:
        upper = q3 + 5 * iqr
        out = x[x > upper]
        if len(out) >= 1 and len(out) / len(x) <= 0.05:
            if hetero is not None:
                skipped.append(Skipped(sheet.sheet_name, col,
                    f"Werte unterscheiden sich stark je „{hetero}“; eine gemeinsame Obergrenze wäre unfair. "
                    "Gruppenspezifische Regel manuell anlegen."))
            else:
                sugg.append(Suggestion(
                    f"{key}.{col}:max", key, sheet.system, sheet.sheet_name, col, "Wertebereich",
                    f"{len(out)} Werte in {col} liegen deutlich über dem üblichen Bereich "
                    f"(> {upper:,.0f}; Median {median(x):,.0f}).".replace(",", "."),
                    len(out), len(x), [str(v) for v in out.sort_values(ascending=False).head(3).tolist()],
                    "Hohe Werte können echte Sonderfälle sein. Die Regel meldet sie nur zur Prüfung.",
                    "mittel" if len(out) >= 2 else "gering",
                    _mk_rule(sheet, col, "range", f"{col} unter Obergrenze", {"max": float(round(upper))},
                             "Werte weit über dem Interquartilsbereich sind selten und prüfenswert.")))


def _text_suggestions(sugg, skipped, sheet, key, col, nn, have, n_all):
    avg_len = nn.map(len).mean()
    shapes = nn.map(_shape)
    nun_vals = nn.nunique()
    # Eindeutigkeit
    if (key, col, "uniqueness") not in have and nun_vals / len(nn) >= 0.9 and avg_len >= 4 \
            and nun_vals < len(nn) and (_is_id_like(col) or col.lower().endswith(("sku", "code", "nummer", "matnr"))
                                         or nun_vals / len(nn) >= 0.97):
        dup_vals = nn.value_counts()
        dup_vals = dup_vals[dup_vals > 1]
        affected = int(dup_vals.sum())
        if affected / len(nn) <= 0.15:
            sugg.append(Suggestion(
                f"{key}.{col}:uniq", key, sheet.system, sheet.sheet_name, col, "Eindeutigkeit",
                f"{col} ist zu {nun_vals / len(nn) * 100:.1f} % eindeutig, {affected} Werte kommen mehrfach vor.",
                affected, len(nn), [str(v) for v in dup_vals.index[:3]],
                "Mehrfache Werte können bei Feldern wie Werk oder Preisbuch erlaubt sein (Mehrfachzeilen je Schlüssel).",
                "mittel", _mk_rule(sheet, col, "uniqueness", f"{col} eindeutig", {},
                                   "Fast alle Werte sind einmalig - Mehrfachwerte deuten auf Dubletten.")))
    # Erlaubte Werte (kategorisch)
    if (key, col, "allowed_values") not in have and 2 <= nun_vals <= 15 and len(nn) >= MIN_ROWS:
        vc = nn.value_counts()
        top = vc[vc / len(nn) >= 0.03]
        rare = vc[vc / len(nn) < 0.03]
        # Schreibvarianten: gleicher Wert case-/whitespace-normalisiert
        norm_groups: dict[str, list[str]] = {}
        for v in vc.index:
            norm_groups.setdefault(re.sub(r"\s+", " ", v.strip().lower()), []).append(v)
        variants = {k: g for k, g in norm_groups.items() if len(g) > 1}
        if len(rare) >= 1 and len(top) >= 1 and top.sum() / len(nn) >= 0.95:
            sugg.append(Suggestion(
                f"{key}.{col}:enum", key, sheet.system, sheet.sheet_name, col, "Erlaubte Werte",
                f"{col} hat {len(top)} übliche Werte ({', '.join(top.index[:5])}); "
                f"{int(rare.sum())} Werte weichen ab ({', '.join(rare.index[:4])}).",
                int(rare.sum()), len(nn), list(rare.index[:3]),
                "Seltene Werte können neue, gültige Ausprägungen sein. Bitte die Liste prüfen.",
                "mittel" if int(rare.sum()) >= 2 else "gering",
                _mk_rule(sheet, col, "allowed_values", f"{col} nur übliche Werte",
                         {"values": [str(v) for v in top.index]},
                         f"{top.sum() / len(nn) * 100:.0f} % der Werte stammen aus {len(top)} Ausprägungen.")))
        elif variants:
            ex = [" / ".join(g) for g in list(variants.values())[:3]]
            sugg.append(Suggestion(
                f"{key}.{col}:case", key, sheet.system, sheet.sheet_name, col, "Erlaubte Werte",
                f"{col} verwendet unterschiedliche Schreibweisen desselben Wertes.",
                sum(int(vc[v]) for g in variants.values() for v in g[1:]), len(nn), ex,
                "Welche Schreibweise gilt, muss der Fachbereich festlegen.", "mittel",
                _mk_rule(sheet, col, "allowed_values", f"{col} einheitlich geschrieben",
                         {"values": [str(g[0]) for g in norm_groups.values()]},
                         "Schreibweisen sollen einheitlich sein.", "niedrig")))
        return
    # Formatmuster (nur kurze, strukturierte Werte, keine Freitexte)
    if (key, col, "format") in have or avg_len > 30 or nun_vals < 3:
        return
    shape_counts = shapes.value_counts()
    if len(shape_counts) > max(8, len(nn) * 0.2):
        return  # Freitext / sehr uneinheitlich
    dom_shape, dom_n = shape_counts.index[0], int(shape_counts.iloc[0])
    share = dom_n / len(nn)
    if share >= 0.9 and dom_n < len(nn):
        bad = nn[shapes != dom_shape]
        rx = _shape_to_regex(dom_shape)
        sugg.append(Suggestion(
            f"{key}.{col}:fmt", key, sheet.system, sheet.sheet_name, col, "Format",
            f"{share * 100:.1f} % der Werte in {col} haben das Muster {rx}, {len(bad)} weichen ab.",
            len(bad), len(nn), list(bad.head(3)),
            "Das Muster ist aus den Daten abgeleitet; abweichende Werte können gültige Sonderfälle sein "
            f"(Stichprobe {len(nn)} Werte).",
            "hoch" if share >= 0.97 and len(nn) >= 100 else "mittel",
            _mk_rule(sheet, col, "format", f"{col} im üblichen Format", {"pattern": rx},
                     f"{share * 100:.0f} % der Werte folgen diesem Muster.")))
