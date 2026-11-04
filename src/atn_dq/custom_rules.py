"""Benutzerdefinierte Regeln: dauerhaft speichern, bearbeiten, ausführen.

Regeln liegen als JSON in ``config/custom_rules.json`` (lokal, überlebt Neustarts).
Zusätzlich speichert ``config/rule_state.json`` den Ein/Aus-Zustand der
eingebauten Regeln.

Unterstützte Regeltypen (``rule_type``):

- ``completeness``  Feld darf nicht leer sein
- ``range``         Zahlenwert innerhalb ``min`` / ``max``
- ``format``        Wert passt vollständig auf einen regulären Ausdruck ``pattern``
- ``allowed_values`` Wert ist in der Liste ``values`` (Groß-/Kleinschreibung egal)
- ``uniqueness``    Wert kommt in der Spalte nur einmal vor
- ``cross_system``  Feld stimmt mit einem Feld in einem anderen Objekt/System überein
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .finding import (
    DIM_CONSISTENCY, DIM_UNIQUENESS, DIM_COMPLETENESS, DIM_VALIDITY, Finding,
)
from .loader import DataPackage, LoadedSheet
from .normalize import is_missing, norm_matnr, norm_price, strip_str

CUSTOM_CATEGORY = "Benutzerregel"

RULE_TYPES = {
    "completeness":   "Vollständigkeit (Feld darf nicht leer sein)",
    "range":          "Wertebereich (Minimum / Maximum)",
    "format":         "Formatprüfung (regulärer Ausdruck)",
    "allowed_values": "Erlaubte Werte (Liste)",
    "uniqueness":     "Eindeutigkeit (keine Dubletten)",
    "cross_system":   "Konsistenz zwischen Systemen",
}

DIMENSION_FOR_TYPE = {
    "completeness": DIM_COMPLETENESS,
    "range": DIM_VALIDITY,
    "format": DIM_VALIDITY,
    "allowed_values": DIM_VALIDITY,
    "uniqueness": DIM_UNIQUENESS,
    "cross_system": DIM_CONSISTENCY,
}

# Formatvorlagen, damit Fachbereiche keine Regex schreiben müssen
FORMAT_PRESETS = {
    "Zwei Großbuchstaben (z. B. Ländercode DE)": r"[A-Z]{2}",
    "Genau 10 Ziffern (z. B. Materialnummer)":    r"\d{10}",
    "Nur Ziffern":                                r"\d+",
    "E-Mail-Adresse":                             r"[^@\s]+@[^@\s]+\.[^@\s]+",
    "Datum JJJJMMTT":                             r"(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])",
    "Eigener Ausdruck":                           "",
}

SEVERITIES = ("hoch", "mittel", "niedrig")


@dataclass
class CustomRule:
    name: str
    sheet_key: str                 # interner Objektschlüssel, z. B. SF_PricebookEntry
    field: str
    rule_type: str
    severity: str = "mittel"
    description: str = ""
    rationale: str = ""            # fachliche Begründung
    department: str = ""           # optional zuständiger Fachbereich
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    rule_id: str = field(default_factory=lambda: "CUST_" + uuid.uuid4().hex[:6].upper())
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CustomRule":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def describe_condition(self) -> str:
        p = self.params
        t = self.rule_type
        if t == "completeness":
            return f"{self.field} darf nicht leer sein"
        if t == "range":
            lo, hi = p.get("min"), p.get("max")
            return f"{self.field} zwischen {lo if lo is not None else '−∞'} und {hi if hi is not None else '+∞'}"
        if t == "format":
            return f"{self.field} muss dem Muster {p.get('pattern', '')} entsprechen"
        if t == "allowed_values":
            return f"{self.field} ∈ {{{', '.join(p.get('values', []))}}}"
        if t == "uniqueness":
            return f"{self.field} muss eindeutig sein"
        if t == "cross_system":
            tol = p.get("tolerance_pct", 0)
            return (f"{self.field} (Schlüssel {p.get('key_field')}) = {p.get('target_sheet')}."
                    f"{p.get('target_field')} (Schlüssel {p.get('target_key_field')}), Toleranz {tol} %")
        return ""


@dataclass
class CustomRuleStat:
    rule_id: str
    records_checked: int
    findings: int
    note: str = ""


# ------------------------------------------------------------ Persistenz --
def rules_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "custom_rules.json"


def state_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "rule_state.json"


def load_custom_rules(config_dir: str | Path) -> list[CustomRule]:
    p = rules_path(config_dir)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [CustomRule.from_dict(d) for d in data.get("rules", [])]


def save_custom_rules(config_dir: str | Path, rules: Iterable[CustomRule]) -> None:
    p = rules_path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "rules": [r.to_dict() for r in rules]}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def upsert_rule(config_dir: str | Path, rule: CustomRule) -> None:
    rules = load_custom_rules(config_dir)
    for i, r in enumerate(rules):
        if r.rule_id == rule.rule_id:
            rule.created_at = r.created_at
            rules[i] = rule
            break
    else:
        rules.append(rule)
    save_custom_rules(config_dir, rules)


def delete_rule(config_dir: str | Path, rule_id: str) -> None:
    save_custom_rules(config_dir, [r for r in load_custom_rules(config_dir) if r.rule_id != rule_id])


def set_rule_enabled(config_dir: str | Path, rule_id: str, enabled: bool) -> None:
    rules = load_custom_rules(config_dir)
    for r in rules:
        if r.rule_id == rule_id:
            r.enabled = enabled
    save_custom_rules(config_dir, rules)


def load_builtin_state(config_dir: str | Path) -> set[str]:
    """IDs der eingebauten Regeln, die der Nutzer deaktiviert hat."""
    p = state_path(config_dir)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("disabled", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_builtin_state(config_dir: str | Path, disabled: Iterable[str]) -> None:
    p = state_path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"disabled": sorted(set(disabled))}, indent=2), encoding="utf-8")


def apply_builtin_state(config_dir: str | Path, registry) -> None:
    disabled = load_builtin_state(config_dir)
    for rule in registry.all():
        registry.set_enabled(rule.rule_id, rule.rule_id not in disabled)


def validate_rule(rule: CustomRule, pkg: DataPackage | None = None) -> list[str]:
    """Liefert verständliche Fehlermeldungen; leere Liste = gültig."""
    errs: list[str] = []
    if not rule.name.strip():
        errs.append("Bitte einen Namen angeben.")
    if rule.severity not in SEVERITIES:
        errs.append("Ungültiger Schweregrad.")
    if rule.rule_type not in RULE_TYPES:
        errs.append("Unbekannter Regeltyp.")
    if not rule.sheet_key or not rule.field:
        errs.append("Objekt und Feld müssen gewählt sein.")
    p = rule.params
    if rule.rule_type == "range":
        lo, hi = p.get("min"), p.get("max")
        if lo is None and hi is None:
            errs.append("Mindestens Minimum oder Maximum angeben.")
        if lo is not None and hi is not None and lo > hi:
            errs.append("Minimum darf nicht größer als Maximum sein.")
    if rule.rule_type == "format":
        pat = p.get("pattern", "")
        if not pat:
            errs.append("Bitte ein Muster angeben.")
        else:
            try:
                re.compile(pat)
            except re.error as exc:
                errs.append(f"Ungültiger regulärer Ausdruck: {exc}")
    if rule.rule_type == "allowed_values" and not p.get("values"):
        errs.append("Bitte mindestens einen erlaubten Wert angeben.")
    if rule.rule_type == "cross_system":
        for k, label in (("key_field", "Schlüsselfeld"), ("target_sheet", "Zielobjekt"),
                         ("target_key_field", "Schlüsselfeld im Zielobjekt"),
                         ("target_field", "Vergleichsfeld im Zielobjekt")):
            if not p.get(k):
                errs.append(f"{label} fehlt.")
    if pkg is not None and not errs:
        sheet = pkg.get(rule.sheet_key)
        if sheet is None:
            errs.append(f"Objekt {rule.sheet_key} ist in den geladenen Daten nicht vorhanden.")
        elif rule.field not in sheet.df.columns:
            errs.append(f"Feld {rule.field} existiert in {rule.sheet_key} nicht.")
    return errs


# ------------------------------------------------------------ Ausführung --
def _record_id(sheet: LoadedSheet, row) -> str | None:
    cols = sheet.df.columns
    key = sheet.key
    if key == "SF_Product2" and "ATN_SAP_Materialnummer__c" in cols:
        return norm_matnr(row.get("ATN_SAP_Materialnummer__c")) or strip_str(row.get("Id"))
    if key == "HS_Products" and "atn_sap_materialnummer" in cols:
        return norm_matnr(row.get("atn_sap_materialnummer")) or strip_str(row.get("hs_object_id"))
    if key.startswith("SAP_") and "MATNR" in cols:
        return norm_matnr(row.get("MATNR"))
    if key == "SF_WorkOrder" and "WorkOrderNumber" in cols:
        return strip_str(row.get("WorkOrderNumber"))
    for c in ("Id", "hs_object_id", "MATNR"):
        if c in cols:
            return strip_str(row.get(c))
    return None


def _num(v: Any) -> float | None:
    return norm_price(v)


def _norm_key(v: Any) -> str | None:
    s = norm_matnr(v)
    if s is None:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s.lower()


def _mk_finding(rule: CustomRule, sheet: LoadedSheet, idx: int, row, message: str,
                explanation: str) -> Finding:
    dept = rule.department or ""
    return Finding(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        category=CUSTOM_CATEGORY,
        dimension=DIMENSION_FOR_TYPE[rule.rule_type],
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(idx),
        field_name=rule.field,
        value=None if is_missing(row.get(rule.field)) else row.get(rule.field),
        message=message,
        severity=rule.severity,
        explanation=explanation,
        business_impact=rule.rationale or "Fachliche Begründung der Regel nicht hinterlegt.",
        cause="Verletzung einer benutzerdefinierten Regel.",
        record_id=_record_id(sheet, row),
        responsibility=dept,
        correction_suggestion="Wert prüfen und im führenden System korrigieren.",
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
        tags=["benutzerregel"],
    )


def run_custom_rule(rule: CustomRule, pkg: DataPackage) -> tuple[list[Finding], CustomRuleStat]:
    sheet = pkg.get(rule.sheet_key)
    if sheet is None:
        return [], CustomRuleStat(rule.rule_id, 0, 0, f"Objekt {rule.sheet_key} nicht geladen")
    if rule.field not in sheet.df.columns:
        return [], CustomRuleStat(rule.rule_id, 0, 0, f"Feld {rule.field} nicht vorhanden")
    df = sheet.df
    out: list[Finding] = []
    t, p = rule.rule_type, rule.params
    checked = 0

    if t == "uniqueness":
        norm = df[rule.field].map(lambda v: None if is_missing(v) else str(strip_str(v)).lower())
        counts = norm.value_counts()
        dups = set(counts[counts > 1].index)
        for idx, row in df.iterrows():
            n = norm.loc[idx]
            if n is None:
                continue
            checked += 1
            if n in dups:
                out.append(_mk_finding(
                    rule, sheet, int(idx), row,
                    f"Wert '{row[rule.field]}' in {rule.field} kommt {int(counts[n])}× vor.",
                    "Das Feld soll laut Regel eindeutig sein."))
        return out, CustomRuleStat(rule.rule_id, checked, len(out))

    target_map: dict[str, list[Any]] = {}
    tsheet = None
    if t == "cross_system":
        tsheet = pkg.get(p.get("target_sheet", ""))
        if tsheet is None or p.get("target_key_field") not in tsheet.df.columns \
                or p.get("target_field") not in tsheet.df.columns \
                or p.get("key_field") not in df.columns:
            return [], CustomRuleStat(rule.rule_id, 0, 0, "Zielobjekt oder Felder nicht vorhanden")
        for _, trow in tsheet.df.iterrows():
            k = _norm_key(trow.get(p["target_key_field"]))
            if k:
                target_map.setdefault(k, []).append(trow.get(p["target_field"]))

    allowed = {str(v).strip().lower() for v in p.get("values", [])} if t == "allowed_values" else set()
    rx = re.compile(p["pattern"]) if t == "format" else None

    for idx, row in df.iterrows():
        val = row.get(rule.field)
        missing = is_missing(val) or (isinstance(val, str) and not val.strip())
        if t == "completeness":
            checked += 1
            if missing:
                out.append(_mk_finding(rule, sheet, int(idx), row,
                                       f"Pflichtfeld {rule.field} ist leer.",
                                       "Das Feld muss laut Regel befüllt sein."))
            continue
        if missing:
            continue  # leere Werte meldet nur die Vollständigkeitsregel
        checked += 1
        if t == "range":
            n = _num(val)
            lo, hi = p.get("min"), p.get("max")
            if n is None:
                out.append(_mk_finding(rule, sheet, int(idx), row,
                                       f"Wert '{val}' ist keine Zahl.",
                                       "Für den Wertebereich muss das Feld numerisch sein."))
            elif (lo is not None and n < lo) or (hi is not None and n > hi):
                out.append(_mk_finding(rule, sheet, int(idx), row,
                                       f"Wert {n:g} liegt außerhalb des Bereichs {lo if lo is not None else '−∞'} bis {hi if hi is not None else '+∞'}.",
                                       "Der Wert verletzt die konfigurierte Grenze."))
        elif t == "format":
            s = str(val) if p.get("raw_check") else str(strip_str(val))
            if s.endswith(".0") and s[:-2].isdigit():
                s = s[:-2]
            if not rx.fullmatch(s):
                out.append(_mk_finding(rule, sheet, int(idx), row,
                                       f"Wert '{val}' entspricht nicht dem Muster {p['pattern']}.",
                                       "Der Wert hat nicht das erwartete Format."))
        elif t == "allowed_values":
            if str(strip_str(val)).lower() not in allowed:
                out.append(_mk_finding(rule, sheet, int(idx), row,
                                       f"Wert '{val}' ist nicht erlaubt (erlaubt: {', '.join(p.get('values', []))}).",
                                       "Der Wert ist nicht in der Liste zulässiger Werte."))
        elif t == "cross_system":
            k = _norm_key(row.get(p["key_field"]))
            if not k:
                continue
            targets = target_map.get(k)
            if not targets:
                continue  # fehlende Gegenstücke prüfen Referenzregeln, nicht diese
            tol = float(p.get("tolerance_pct", 0) or 0)
            a_num = _num(val)
            ok = False
            for tv in targets:
                b_num = _num(tv)
                if a_num is not None and b_num is not None and p.get("compare") != "text":
                    base = max(abs(a_num), abs(b_num), 1e-9)
                    if abs(a_num - b_num) / base * 100 <= tol:
                        ok = True
                        break
                elif str(strip_str(val)).lower() == str(strip_str(tv)).lower():
                    ok = True
                    break
            if not ok:
                out.append(_mk_finding(
                    rule, sheet, int(idx), row,
                    f"{rule.field}='{val}' weicht von {tsheet.system}/{tsheet.sheet_name}."
                    f"{p['target_field']}='{targets[0]}' ab (Schlüssel {row.get(p['key_field'])}).",
                    f"Gleicher Schlüssel, aber unterschiedliche Werte zwischen {sheet.system} und {tsheet.system}."))
    return out, CustomRuleStat(rule.rule_id, checked, len(out))


def run_custom_rules(rules: Iterable[CustomRule], pkg: DataPackage
                     ) -> tuple[list[Finding], dict[str, CustomRuleStat]]:
    findings: list[Finding] = []
    stats: dict[str, CustomRuleStat] = {}
    for r in rules:
        if not r.enabled:
            continue
        try:
            fs, st = run_custom_rule(r, pkg)
        except Exception as exc:  # defensive: eine kaputte Regel stoppt nicht den Lauf
            fs, st = [], CustomRuleStat(r.rule_id, 0, 0, f"Fehler: {exc}")
        findings.extend(fs)
        stats[r.rule_id] = st
    return findings, stats
