"""Regelverwaltung: Übersicht, Regel erstellen/bearbeiten/löschen, Regelvorschläge."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from atn_dq.custom_rules import (
    FORMAT_PRESETS, RULE_TYPES, SEVERITIES, CustomRule, delete_rule, load_custom_rules,
    run_custom_rule, save_builtin_state, set_rule_enabled, upsert_rule, validate_rule,
)
from atn_dq.rules import registry
from atn_dq.suggest import suggest_rules

from .ctx import Ctx

OTHER = "Sonstiger Fachbereich …"


def build_rules_info(ctx_cfg_dir, result, custom_rules) -> list[dict]:
    """Einheitliche Regelliste (eingebaut + Benutzer) für Tabelle und Assistent."""
    counts = getattr(result, "rule_finding_counts", {})
    stats = getattr(result, "custom_stats", {})
    info = []
    for r in registry.all():
        info.append({"id": r.rule_id, "name": r.name, "source": "System", "kind": r.category,
                     "dimension": r.dimension, "severity": r.default_severity, "enabled": r.enabled,
                     "checked": None, "total": None, "findings": counts.get(r.rule_id),
                     "object": "mehrere Objekte", "description": r.description, "department": ""})
    for c in custom_rules:
        st_ = stats.get(c.rule_id)
        info.append({"id": c.rule_id, "name": c.name, "source": "Benutzer", "kind": RULE_TYPES[c.rule_type].split(" (")[0],
                     "dimension": "", "severity": c.severity, "enabled": c.enabled,
                     "checked": st_.records_checked if st_ else None, "total": None,
                     "findings": st_.findings if st_ else None,
                     "object": f"{c.sheet_key} · {c.field}", "description": c.describe_condition(),
                     "department": c.department})
    return info


def _sheet_labels(ctx: Ctx) -> dict[str, str]:
    return {k: f"{s.system} · {s.sheet_name}" for k, s in ctx.pkg.sheets.items()}


def _departments(ctx: Ctx) -> list[str]:
    deps = set(ctx.cfg.responsibilities.values()) | set(ctx.areas.keys())
    return sorted(d for d in deps if d)


def _split_values(text: str) -> list[str]:
    parts = [p.strip() for line in text.splitlines() for p in line.split(";")]
    out = []
    for p in parts:
        out += [x.strip() for x in p.split(",")] if "," in p and "\n" not in text else [p]
    return [x for x in dict.fromkeys(out) if x]


def _num_or_none(txt: str):
    txt = (txt or "").strip().replace(",", ".")
    if not txt:
        return None, False
    try:
        return float(txt), False
    except ValueError:
        return None, True


@st.dialog("Regel", width="large")
def rule_dialog(ctx: Ctx, rule_id: str | None = None, preset: CustomRule | None = None) -> None:
    existing = next((r for r in load_custom_rules(ctx.config_dir) if r.rule_id == rule_id), None) if rule_id else preset
    ex = existing
    p = ex.params if ex else {}
    labels = _sheet_labels(ctx)
    st.markdown("**Neue Regel erstellen**" if not rule_id else f"**Regel bearbeiten** · `{rule_id}`")
    name = st.text_input("Name der Regel", value=ex.name if ex else "", key="rd_name",
                         placeholder="z. B. Preis größer 0")
    desc = st.text_area("Beschreibung", value=ex.description if ex else "", key="rd_desc", height=70)
    systems = sorted({s.system for s in ctx.pkg.sheets.values()})
    cur_sys = ctx.pkg.sheets[ex.sheet_key].system if ex and ex.sheet_key in ctx.pkg.sheets else systems[0]
    c1, c2, c3 = st.columns(3)
    system = c1.selectbox("System", systems, index=systems.index(cur_sys), key="rd_sys")
    sheet_keys = [k for k, s in ctx.pkg.sheets.items() if s.system == system]
    sk_idx = sheet_keys.index(ex.sheet_key) if ex and ex.sheet_key in sheet_keys else 0
    sheet_key = c2.selectbox("Datenobjekt", sheet_keys, index=sk_idx, key="rd_sheet",
                             format_func=lambda k: ctx.pkg.sheets[k].sheet_name)
    cols = list(ctx.pkg.sheets[sheet_key].df.columns)
    f_idx = cols.index(ex.field) if ex and ex.field in cols and ex.sheet_key == sheet_key else 0
    field = c3.selectbox("Feld", cols, index=f_idx, key="rd_field")
    types = list(RULE_TYPES)
    rtype = st.selectbox("Regeltyp", types, index=types.index(ex.rule_type) if ex else 0,
                         format_func=lambda t: RULE_TYPES[t], key="rd_type")
    params: dict = {}
    if rtype == "range":
        a, b = st.columns(2)
        lo_txt = a.text_input("Minimum (leer = keine Untergrenze)", value="" if p.get("min") is None else str(p.get("min")), key="rd_min")
        hi_txt = b.text_input("Maximum (leer = keine Obergrenze)", value="" if p.get("max") is None else str(p.get("max")), key="rd_max")
        lo, e1 = _num_or_none(lo_txt)
        hi, e2 = _num_or_none(hi_txt)
        if e1 or e2:
            st.error("Bitte Zahlen eingeben (z. B. 0 oder 500000).")
        params = {"min": lo, "max": hi}
    elif rtype == "format":
        presets = list(FORMAT_PRESETS)
        cur = next((k for k, v in FORMAT_PRESETS.items() if v and v == p.get("pattern")), "Eigener Ausdruck")
        preset_name = st.selectbox("Formatvorlage", presets, index=presets.index(cur), key="rd_preset")
        default_pat = FORMAT_PRESETS[preset_name] or p.get("pattern", "")
        pattern = st.text_input("Muster (regulärer Ausdruck, muss den ganzen Wert beschreiben)",
                                value=default_pat, key=f"rd_pat_{preset_name}")
        params = {"pattern": pattern}
    elif rtype == "allowed_values":
        top = ctx.pkg.sheets[sheet_key].df[field].dropna().astype(str).str.strip().value_counts().head(8)
        st.caption("Häufigste Werte in den Daten: " + ", ".join(f"{k} ({v}×)" for k, v in top.items()))
        txt = st.text_area("Erlaubte Werte (einer pro Zeile oder mit Komma getrennt)",
                           value="\n".join(p.get("values", [])), key="rd_vals", height=100)
        params = {"values": _split_values(txt)}
    elif rtype == "cross_system":
        tsys = st.selectbox("Vergleichen mit System", systems, key="rd_tsys")
        tkeys = [k for k, s in ctx.pkg.sheets.items() if s.system == tsys]
        t_idx = tkeys.index(p["target_sheet"]) if p.get("target_sheet") in tkeys else 0
        tsheet = st.selectbox("Zielobjekt", tkeys, index=t_idx, key="rd_tsheet",
                              format_func=lambda k: ctx.pkg.sheets[k].sheet_name)
        tcols = list(ctx.pkg.sheets[tsheet].df.columns)
        k1, k2 = st.columns(2)
        key_field = k1.selectbox("Schlüsselfeld in diesem Objekt (verbindet beide Seiten)", cols,
                                 index=cols.index(p["key_field"]) if p.get("key_field") in cols else 0, key="rd_kf")
        tkey = k2.selectbox("Schlüsselfeld im Zielobjekt", tcols,
                            index=tcols.index(p["target_key_field"]) if p.get("target_key_field") in tcols else 0, key="rd_tkf")
        v1, v2, v3 = st.columns(3)
        tfield = v1.selectbox("Vergleichsfeld im Zielobjekt", tcols,
                              index=tcols.index(p["target_field"]) if p.get("target_field") in tcols else 0, key="rd_tf")
        mode = v2.selectbox("Vergleich als", ["Zahl", "Text"], index=1 if p.get("compare") == "text" else 0, key="rd_cmp")
        tol = v3.number_input("Toleranz in % (nur Zahlen)", min_value=0.0, max_value=100.0,
                              value=float(p.get("tolerance_pct", 0) or 0), key="rd_tol")
        params = {"key_field": key_field, "target_sheet": tsheet, "target_key_field": tkey,
                  "target_field": tfield, "tolerance_pct": tol, "compare": "text" if mode == "Text" else "number"}
        st.caption("Fehlt ein Gegenstück im Zielobjekt, prüfen das die Referenzregeln, nicht diese Regel.")
    elif rtype == "uniqueness":
        st.caption("Meldet jeden Datensatz, dessen Wert in dieser Spalte mehrfach vorkommt.")
    s1, s2 = st.columns(2)
    sev = s1.selectbox("Schweregrad", list(SEVERITIES), index=list(SEVERITIES).index(ex.severity) if ex else 1, key="rd_sev")
    deps = [""] + _departments(ctx) + [OTHER]
    cur_dep = ex.department if ex else ""
    dep_idx = deps.index(cur_dep) if cur_dep in deps else deps.index(OTHER)
    dep_pick = s2.selectbox("Zuständiger Fachbereich (optional)", deps, index=dep_idx, key="rd_dep",
                            format_func=lambda d: "- keiner -" if d == "" else d)
    dep = dep_pick
    if dep_pick == OTHER:
        dep = st.text_input("Fachbereich", value=cur_dep if cur_dep not in deps else "", key="rd_dep_free")
    rationale = st.text_area("Fachliche Begründung", value=ex.rationale if ex else "", key="rd_rat", height=70,
                             placeholder="Warum ist diese Regel wichtig? Was passiert, wenn sie verletzt wird?")

    rule = CustomRule(name=name.strip(), sheet_key=sheet_key, field=field, rule_type=rtype, severity=sev,
                      description=desc.strip(), rationale=rationale.strip(), department=(dep or "").strip(),
                      params=params, enabled=ex.enabled if ex else True,
                      **({"rule_id": ex.rule_id} if ex else {}))
    errs = validate_rule(rule, ctx.pkg)
    b1, b2, b3 = st.columns(3)
    if b1.button("Regel testen", key="rd_test"):
        if errs:
            st.error(" ".join(errs))
        else:
            fs, stat = run_custom_rule(rule, ctx.pkg)
            st.info(f"Test: {stat.records_checked} Datensätze geprüft, {len(fs)} Treffer. Noch nichts gespeichert.")
            if fs:
                st.dataframe(pd.DataFrame([{"Zeile": f.row, "Wert": f.value, "Befund": f.message} for f in fs[:8]]),
                             use_container_width=True, hide_index=True)
    if b2.button("Speichern", type="primary", key="rd_save"):
        if errs:
            st.error(" ".join(errs))
        else:
            upsert_rule(ctx.config_dir, rule)
            st.session_state.flash = f"Regel „{rule.name}“ gespeichert und beim nächsten Lauf angewendet."
            st.rerun()
    if rule_id and b3.button("Löschen", key="rd_delete"):
        delete_rule(ctx.config_dir, rule_id)
        st.session_state.flash = "Regel gelöscht."
        st.rerun()


def render(ctx: Ctx) -> None:
    st.title("Regel-Engine")
    st.markdown('<p class="subtitle">Alle Prüfungen - eigene Regeln anlegen, Vorschläge prüfen, jede Regel nachvollziehbar.</p>',
                unsafe_allow_html=True)
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    top = st.columns([2, 1, 3])
    if top[0].button("➕ Neue Regel erstellen", type="primary", key="new_rule_btn"):
        rule_dialog(ctx)
    custom = load_custom_rules(ctx.config_dir)
    info = build_rules_info(ctx.config_dir, ctx.result, custom)
    t_all, t_new, t_sug = st.tabs([f"Regelübersicht ({sum(r['enabled'] for r in info)} aktiv)",
                                   f"Eigene Regeln ({len(custom)})", "Regelvorschläge aus den Daten"])

    # ------------------------------------------------------------ Übersicht --
    with t_all:
        df = pd.DataFrame([{
            "Aktiv": r["enabled"], "Regel-ID": r["id"], "Name": r["name"], "Quelle": r["source"],
            "Typ / Kategorie": r["kind"], "Schweregrad": r["severity"], "Geprüftes Objekt": r["object"],
            "Geprüfte Datensätze": r["checked"], "Befunde im letzten Lauf": r["findings"],
            "Beschreibung / Bedingung": r["description"],
        } for r in info])
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, key="rules_editor",
            disabled=[c for c in df.columns if c != "Aktiv"],
            column_config={"Aktiv": st.column_config.CheckboxColumn("Aktiv", help="Ein-/Ausschalten wird dauerhaft gespeichert."),
                           "Geprüfte Datensätze": st.column_config.NumberColumn(
                               help="Bei Benutzerregeln: tatsächlich geprüfte (nicht leere) Datensätze. "
                                    "Bei Systemregeln wird der Prüfumfang nicht einzeln erfasst.")})
        changed = edited[edited["Aktiv"] != df["Aktiv"]]
        if len(changed):
            builtin_disabled = {r.rule_id for r in registry.all() if not r.enabled}
            for _, row in changed.iterrows():
                rid, on = row["Regel-ID"], bool(row["Aktiv"])
                if row["Quelle"] == "Benutzer":
                    set_rule_enabled(ctx.config_dir, rid, on)
                else:
                    (builtin_disabled.discard if on else builtin_disabled.add)(rid)
                    registry.set_enabled(rid, on)
            save_builtin_state(ctx.config_dir, builtin_disabled)
            st.rerun()
        st.caption("Systemregeln melden ihre Befunde, aber nicht die Zahl der geprüften Zeilen. "
                   "Benutzerregeln zeigen beides. Deaktivierte Regeln laufen nicht mehr mit.")

    # --------------------------------------------------------- Eigene Regeln --
    with t_new:
        if not custom:
            st.info("Noch keine eigenen Regeln. Mit „Neue Regel erstellen“ legst du die erste an.")
        stats = ctx.result.custom_stats
        for c in custom:
            s = stats.get(c.rule_id)
            head = f"{'🟢' if c.enabled else '⚪'} {c.name} · {c.severity}"
            with st.expander(head):
                st.markdown(f"**Bedingung:** {c.describe_condition()}  \n**Objekt:** `{c.sheet_key}` · Feld `{c.field}`")
                if c.description:
                    st.markdown(f"**Beschreibung:** {c.description}")
                if c.rationale:
                    st.markdown(f"**Fachliche Begründung:** {c.rationale}")
                if c.department:
                    st.markdown(f"**Zuständig:** {c.department}")
                if s:
                    total = len(ctx.pkg.sheets[c.sheet_key].df) if c.sheet_key in ctx.pkg.sheets else 0
                    st.markdown(f"**Prüfumfang:** {s.records_checked} von {total} Datensätzen geprüft "
                                f"(leere Werte werden nur von Vollständigkeitsregeln gemeldet) · **{s.findings} Befunde**"
                                + (f" · Hinweis: {s.note}" if s.note else ""))
                elif not c.enabled:
                    st.caption("Deaktiviert - läuft nicht mit.")
                a, b, d = st.columns(3)
                if a.button("Bearbeiten", key=f"edit_{c.rule_id}"):
                    rule_dialog(ctx, rule_id=c.rule_id)
                if b.button("Deaktivieren" if c.enabled else "Aktivieren", key=f"tog_{c.rule_id}"):
                    set_rule_enabled(ctx.config_dir, c.rule_id, not c.enabled)
                    st.rerun()
                if d.button("Löschen", key=f"del_{c.rule_id}"):
                    delete_rule(ctx.config_dir, c.rule_id)
                    st.rerun()

    # ----------------------------------------------------------- Vorschläge --
    with t_sug:
        _suggestions(ctx, custom)


def _suggestions(ctx: Ctx, custom: list[CustomRule]) -> None:
    st.markdown("Muster aus **euren echten Daten**. Nichts davon ist aktiv. Prüfe Beispiele und Unsicherheit, "
                "dann bestätigst du die Regel selbst.")
    sig = tuple(sorted((k, len(s.df)) for k, s in ctx.pkg.sheets.items())) + tuple(sorted(c.rule_id for c in custom))
    if st.session_state.get("sugg_sig") != sig:
        st.session_state.sugg_cache = suggest_rules(ctx.pkg, custom)
        st.session_state.sugg_sig = sig
    sugg, skipped = st.session_state.sugg_cache
    dismissed = st.session_state.setdefault("sugg_dismissed", set())
    kinds = sorted({s.kind for s in sugg})
    c1, c2, c3 = st.columns(3)
    conf = c1.multiselect("Sicherheit", ["hoch", "mittel", "gering"], default=["hoch", "mittel"], key="sg_conf")
    kind = c2.multiselect("Art", kinds, default=kinds, key="sg_kind")
    q = c3.text_input("Suche (Feld/Objekt)", key="sg_q")
    shown = [s for s in sugg if s.confidence in conf and s.kind in kind and s.sid not in dismissed
             and (not q or q.lower() in f"{s.field} {s.sheet_name}".lower())]
    st.caption(f"{len(shown)} Vorschläge von {len(sugg)} (Mindestgröße je Spalte: 30 Werte).")
    for s in shown[:40]:
        with st.expander(f"[{s.confidence}] {s.kind} · {s.system} / {s.sheet_name} · {s.field} - {s.affected} von {s.total}"):
            st.markdown(f"**Beobachtetes Muster:** {s.pattern}")
            st.markdown(f"**Betroffen:** {s.affected} von {s.total} Datensätzen ({s.share * 100:.1f} %)")
            st.markdown("**Beispielwerte:** " + ", ".join(f"`{e}`" for e in s.examples))
            st.markdown(f"**Vorgeschlagene Regel:** {s.rule.name} - {s.rule.describe_condition()}")
            st.markdown(f"**Unsicherheit:** {s.uncertainty}")
            ok = st.checkbox("Ich habe Muster und Beispiele geprüft und möchte die Regel aktivieren", key=f"ok_{s.sid}")
            sev = st.selectbox("Schweregrad", list(SEVERITIES), index=list(SEVERITIES).index(s.rule.severity), key=f"sev_{s.sid}")
            a, b = st.columns(2)
            if a.button("Als Regel übernehmen", key=f"adopt_{s.sid}", disabled=not ok, type="primary"):
                r = s.rule
                r.severity, r.enabled = sev, True
                r.description = "Aus Datenmuster vorgeschlagen und vom Nutzer bestätigt."
                upsert_rule(ctx.config_dir, r)
                st.session_state.flash = f"Regel „{r.name}“ übernommen."
                st.rerun()
            if b.button("Verwerfen", key=f"dis_{s.sid}"):
                dismissed.add(s.sid)
                st.rerun()
    if skipped:
        with st.expander(f"Bewusst nicht vorgeschlagen ({len(skipped)})"):
            for k in skipped:
                st.markdown(f"- **{k.sheet} · {k.field}**: {k.reason}")
