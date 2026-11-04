"""Rollenbasierte Dashboards (CEO, Head of MDM, Domain Expert, Governance, AI)."""
from __future__ import annotations

import io
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

from atn_dq.export import findings_to_dataframe
from atn_dq.financial import NOT_CALCULABLE, total_calculated
from atn_dq.insights import (
    affected_record_count, build_recommendations, cause_groups, department_summary,
)
from atn_dq.roles import findings_for_area

from .ctx import Ctx

ROLE_ICONS = {
    "CEO": "🧭", "Head of MDM": "🗂️", "Domain Expert": "🔎",
    "Head of Data Governance": "⚖️", "Head of AI": "🤖",
}
SEV_COLORS = {"hoch": "#b31b2a", "mittel": "#e8a33a", "niedrig": "#8fb996"}


# --------------------------------------------------------------- Auswahl --
def role_selector(ctx: Ctx) -> None:
    """Gut sichtbarer Rollen-Button für die Seitenleiste."""
    role = st.session_state.get("role")
    label = f"👤 Rolle: {role}" if role else "👤 Rolle wählen"
    with st.popover(label, use_container_width=True):
        st.markdown("**Wer schaut hier hin?**")
        st.caption("Die Rolle ändert nur die Sicht, keine Rechte.")
        for name, r in ctx.roles.items():
            if st.button(f"{ROLE_ICONS.get(name, '👤')} {name}", key=f"rolepick_{name}",
                         use_container_width=True, type="primary" if name == role else "secondary"):
                st.session_state.role = name
                st.session_state.nav_target = "Mein Dashboard"
                st.rerun()
        if role and st.button("Rolle zurücksetzen", key="role_reset", use_container_width=True):
            st.session_state.role = None
            st.rerun()


def _picker(ctx: Ctx) -> None:
    st.title("Mein Dashboard")
    st.markdown('<p class="subtitle">Wähle deine Rolle - du siehst zuerst, was für dich zählt. '
                'Alle Details bleiben per Drill-down erreichbar.</p>', unsafe_allow_html=True)
    cols = st.columns(len(ctx.roles))
    for col, (name, r) in zip(cols, ctx.roles.items()):
        with col:
            st.markdown(f"### {ROLE_ICONS.get(name, '👤')} {name}")
            st.caption(r.title)
            st.write(r.focus)
            if st.button("Dashboard öffnen", key=f"pick_{name}", use_container_width=True):
                st.session_state.role = name
                st.rerun()


def render(ctx: Ctx) -> None:
    role = st.session_state.get("role")
    if not role or role not in ctx.roles:
        _picker(ctx)
        return
    r = ctx.roles[role]
    st.title(f"{ROLE_ICONS.get(role, '')} {role}")
    st.markdown(f'<p class="subtitle">{r.focus}</p>',
                unsafe_allow_html=True)
    {"CEO": _ceo, "Head of MDM": _mdm, "Domain Expert": _domain,
     "Head of Data Governance": _governance, "Head of AI": _ai}[role](ctx)


# ------------------------------------------------------------------- CEO --
def _label(cat: str) -> str:
    return cat.replace("_", " ")


def _clickable_bar(df: pd.DataFrame, cat_col: str, key: str, height: int = 280):
    """Gestapelte horizontale Balken; liefert die angeklickte Kategorie oder None."""
    fig = px.bar(df, x="Anzahl", y=cat_col, color="Schweregrad", orientation="h",
                 color_discrete_map=SEV_COLORS,
                 category_orders={"Schweregrad": ["hoch", "mittel", "niedrig"]})
    fig.update_layout(height=height, margin=dict(l=0, r=10, t=10, b=0), legend_title_text="",
                      legend=dict(orientation="h", y=-0.2), yaxis=dict(autorange="reversed"), clickmode="event+select")
    ev = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", key=key)
    pts = []
    try:
        pts = ev["selection"]["points"]
    except Exception:  # noqa: BLE001
        pts = []
    return pts[0].get("y") if pts else None


def _ceo(ctx: Ctx) -> None:
    f_all = ctx.findings
    valid = sorted([r for r in ctx.regions if r.sufficient_data], key=lambda r: r.score)
    total, n_calc = total_calculated(ctx.impacts)

    c1, c2, c3, c4 = st.columns(4)
    ctx.kpi(c1, "Gesamt-Score (0-100)", f"{ctx.overall.score}", help_text="Gewichtete Datenqualität.")
    ctx.kpi(c2, "Kritische Befunde", f"{ctx.overall.findings_high}", "prio-h",
            help_text="Schweregrad hoch.")
    if valid:
        ctx.kpi(c3, "Schwächste Region", f"{valid[0].region}", "prio-h",
                help_text=f"Score {valid[0].score}, {valid[0].findings_high} kritische Befunde.")
    else:
        ctx.kpi(c3, "Schwächste Region", "n/a", help_text="Zu wenige Daten je Region.")
    if total is not None:
        ctx.kpi(c4, "Belastbar berechnetes Risiko", f"≥ {total:,.0f} €".replace(",", "."),
                help_text=f"{n_calc} von {len(ctx.impacts)} Positionen berechenbar - siehe Berechnungsgrundlage.")
    else:
        ctx.kpi(c4, "Finanzielles Risiko", "n/a", help_text=NOT_CALCULABLE)

    st.markdown(" ")
    cl, cr = st.columns([3, 2])
    with cl:
        st.subheader("Entwicklung der Datenqualität")
        try:
            runs = ctx.history.list_runs()
        except Exception:  # noqa: BLE001 - Verlaufsdatenbank nicht erreichbar
            runs = []
            st.caption("Verlaufsdatenbank derzeit nicht erreichbar.")
        if len(runs) >= 2:
            hdf = pd.DataFrame([{"Zeitpunkt": r.run_time, "Score": r.overall_score, "Hoch": r.findings_high}
                                for r in reversed(runs)])
            fig = px.line(hdf, x="Zeitpunkt", y="Score", markers=True, range_y=[0, 100])
            fig.update_layout(height=240, margin=dict(l=0, r=10, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Der Verlauf entsteht, sobald mindestens zwei Läufe gespeichert sind. "
                    "So sieht man, ob Maßnahmen wirken.")
        if st.button("Aktuellen Lauf im Verlauf speichern", key="ceo_save_run"):
            ctx.history.save_run(findings=f_all, total_records=ctx.overall.total_records,
                                 rule_count=ctx.result.rule_count, overall_score=ctx.overall.score,
                                 notes="Gespeichert im CEO-Dashboard")
            st.success("Lauf gespeichert.")
            st.rerun()
    with cr:
        st.subheader("Wer packt was zuerst an?")
        depts = department_summary(f_all)
        for d in depts[:3]:
            cats = ", ".join(_label(c) for c, _ in d.top_categories[:2])
            st.markdown(f"**{d.department}** · {d.high} kritisch  \n<small>{cats}</small>", unsafe_allow_html=True)
        st.caption("Woran man merkt, dass es wirkt: Score steigt und kritische Befunde sinken von Lauf zu Lauf.")

    st.markdown("---")
    st.subheader("Wo ist es am dringendsten?")
    st.caption("Klick auf einen Balken filtert die anderen Ansichten. Unten erscheinen die konkreten Probleme.")
    hide_low = st.toggle("Niedrige Befunde ausblenden", value=True, key="ceo_hide_low")
    base = [f for f in f_all if not (hide_low and f.severity == "niedrig")]
    sel = st.session_state.setdefault("ceo_sel", {"Region": None, "System": None, "Ursache": None})
    last = st.session_state.setdefault("ceo_last_click", {})

    def sub(skip: str):
        out = base
        if skip != "Region" and sel["Region"]:
            out = [f for f in out if (f.region or "Nicht zugeordnet") == sel["Region"]]
        if skip != "System" and sel["System"]:
            out = [f for f in out if f.system == sel["System"]]
        if skip != "Ursache" and sel["Ursache"]:
            out = [f for f in out if _label(f.category) == sel["Ursache"]]
        return out

    def counts(fs, keyfn):
        c = Counter((keyfn(f), f.severity) for f in fs)
        return pd.DataFrame([{"k": k, "Schweregrad": s, "Anzahl": n} for (k, s), n in c.items()])

    cols = st.columns(3)
    dims = [("Region", lambda f: f.region or "Nicht zugeordnet"),
            ("System", lambda f: f.system),
            ("Ursache", lambda f: _label(f.category))]
    for col, (dim, fn) in zip(cols, dims):
        with col:
            st.markdown(f"**{dim}**")
            df = counts(sub(dim), fn).rename(columns={"k": dim})
            if df.empty:
                st.caption("Keine Befunde.")
                continue
            order = df.groupby(dim)["Anzahl"].sum().sort_values(ascending=False).head(8).index.tolist()
            df = df[df[dim].isin(order)]
            clicked = _clickable_bar(df, dim, key=f"ceo_chart_{dim}")
            if clicked and last.get(dim) != clicked:
                last[dim] = clicked
                sel[dim] = clicked
                st.rerun()
    active = {k: v for k, v in sel.items() if v}
    if active:
        bc = st.columns([6, 1])
        bc[0].markdown("**Auswahl:** " + " → ".join(f"`{k}: {v}`" for k, v in active.items()))
        if bc[1].button("Zurücksetzen", key="ceo_reset"):
            st.session_state.ceo_sel = {"Region": None, "System": None, "Ursache": None}
            st.session_state.ceo_last_click = {}
            for d in ("Region", "System", "Ursache"):
                st.session_state.pop(f"ceo_chart_{d}", None)
            st.rerun()
    shown = sub("")
    st.markdown(f"**{'Konkrete Probleme' if active else 'Die dringendsten Probleme'}** ({len(shown)} Befunde)")
    rows = [{"Priorität": f"{f.priority_label} ({f.priority_score:.0f})", "System": f.system,
             "Region": f.region or "", "Befund": f.message, "Wo": f"{f.sheet} Z{f.row}",
             "Verantwortlich": f.responsibility} for f in sorted(shown, key=lambda x: -x.priority_score)[:15]]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    b1, b2, b3 = st.columns(3)
    if b1.button("Alle in der Befundliste öffnen", key="ceo_open_f"):
        flt = {}
        if sel["Region"]: flt["Region"] = [sel["Region"]]
        if sel["System"]: flt["System"] = [sel["System"]]
        ctx.goto_findings(flt)
    if b2.button("Geschäftliche Auswirkungen ansehen", key="ceo_open_fin"):
        ctx.goto_page("Geschäftliche Auswirkungen")
    if b3.button("Fehler-Stammbaum ansehen", key="ceo_open_tree"):
        ctx.goto_page("Fehler-Stammbaum")


# ------------------------------------------------------------ Head of MDM --
def _mdm(ctx: Ctx) -> None:
    fs = ctx.findings
    done = {fid for fid, s in st.session_state.get("finding_status", {}).items() if s == "Behoben"}
    open_n = sum(1 for f in fs if f.finding_id not in done)
    c1, c2, c3, c4 = st.columns(4)
    ctx.kpi(c1, "Gesamt-Score", f"{ctx.overall.score}")
    ctx.kpi(c2, "Geprüfte Datensätze", f"{ctx.overall.total_records:,}".replace(",", "."))
    ctx.kpi(c3, "Offene Maßnahmen", f"{open_n:,}".replace(",", "."), "prio-m",
            help_text="Befunde, die nicht als behoben markiert sind.")
    ctx.kpi(c4, "Aktive Regeln", f"{ctx.result.rule_count}",
            help_text=f"davon {len(ctx.result.custom_stats)} Benutzerregeln mit Treffern/Prüfung.")

    st.subheader("Fehler nach System und Qualitätsdimension")
    mat = Counter((f.system, f.dimension) for f in fs if f.severity != "niedrig")
    if mat:
        df = pd.DataFrame([{"System": s, "Dimension": d, "Befunde": n} for (s, d), n in mat.items()])
        pv = df.pivot(index="System", columns="Dimension", values="Befunde").fillna(0)
        fig = px.imshow(pv, text_auto=True, color_continuous_scale="Reds", aspect="auto")
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Gezählt werden Befunde mit Schweregrad hoch und mittel.")

    cl, cr = st.columns(2)
    with cl:
        st.subheader("Fehler nach Datenobjekt")
        obj = Counter((f"{f.system} · {f.sheet}") for f in fs if f.severity == "hoch")
        st.dataframe(pd.DataFrame([{"Datenobjekt": k, "Kritische Befunde": v} for k, v in obj.most_common(12)]),
                     use_container_width=True, hide_index=True)
    with cr:
        st.subheader("Führende Systeme")
        lead = ctx.cfg.leading_systems
        st.dataframe(pd.DataFrame([{"Datenbereich": k.replace("_", " "), "Führendes System": v.replace("_", " ")}
                                   for k, v in lead.items()]), use_container_width=True, hide_index=True)
        open_dec = [k for k, v in lead.items() if v.startswith("Governance")]
        if open_dec:
            st.warning("Governance-Entscheidung offen: " + ", ".join(k.replace("_", " ") for k in open_dec))

    st.subheader("Ursachen und Folgefehler")
    groups = cause_groups(fs)
    for g in groups[:5]:
        st.markdown(f"- **{g.record_id}** · {len(g.members)} zusammenhängende Befunde in {', '.join(g.systems)} · "
                    f"Primär: {g.primary.rule_name}")
    st.subheader("Priorisierung")
    recs = build_recommendations(fs)
    for r in recs[:4]:
        st.markdown(f"- **{r.title}** - {r.detail}")
    b1, b2, b3 = st.columns(3)
    if b1.button("Regeln verwalten", key="mdm_rules"):
        ctx.goto_page("Regeln")
    if b2.button("Fehler-Stammbaum", key="mdm_tree"):
        ctx.goto_page("Fehler-Stammbaum")
    if b3.button("Befundliste", key="mdm_f"):
        ctx.goto_findings({})


# ----------------------------------------------------------- Domain Expert --
def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Befunde")
    return buf.getvalue()


def _domain(ctx: Ctx) -> None:
    names = ["Alle Fachbereiche"] + list(ctx.areas)
    default = st.session_state.get("area", names[1] if len(names) > 1 else names[0])
    pick = st.selectbox("Mein Fachbereich", names, index=names.index(default) if default in names else 0,
                        key="area_select")
    st.session_state.area = pick
    if pick == "Alle Fachbereiche":
        fs = ctx.findings
        st.caption("Gesamtsicht für Datenqualitäts-Expert:innen. Wähle einen Fachbereich für die Detailansicht.")
    else:
        a = ctx.areas[pick]
        fs = findings_for_area(ctx.findings, a)
        st.markdown(f"**{a.title}**  \n> „{a.voice}“")
        st.caption("Die Zuordnung Fachbereich → Daten steht in config/roles.yaml und ist anpassbar.")
    products = {f.record_id for f in fs if f.record_id and f.record_id.isdigit() and len(f.record_id) == 10}
    c1, c2, c3, c4 = st.columns(4)
    ctx.kpi(c1, "Befunde", f"{len(fs)}")
    ctx.kpi(c2, "Davon kritisch", f"{sum(1 for f in fs if f.severity == 'hoch')}", "prio-h")
    ctx.kpi(c3, "Betroffene Datensätze", f"{affected_record_count(fs)}")
    ctx.kpi(c4, "Betroffene Produkte", f"{len(products)}", help_text="Eindeutige Materialnummern.")
    if not fs:
        st.success("Für diesen Fachbereich gibt es aktuell keine Befunde.")
        return

    st.subheader("Was ist falsch und was ist zu tun?")
    groups: dict[str, list] = {}
    for f in fs:
        groups.setdefault(f.rule_id, []).append(f)
    ordered = sorted(groups.values(), key=lambda g: (-sum(x.severity == "hoch" for x in g), -len(g)))
    rows = []
    for g in ordered[:25]:
        f0 = max(g, key=lambda x: x.priority_score)
        rows.append({"Schwere": f0.severity, "Problem": f0.rule_name, "Anzahl": len(g), "Feld": f0.field_name,
                     "Beispiel": f0.message[:110], "Korrekturvorschlag": f0.correction_suggestion or "Fachlich prüfen",
                     "Art": f0.correction_type.replace("_", " ")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Probleme prüfen")
    sev = st.multiselect("Schweregrad", ["hoch", "mittel", "niedrig"], default=["hoch", "mittel"], key="dx_sev")
    shown = [f for f in sorted(fs, key=lambda x: -x.priority_score) if f.severity in sev]
    if shown:
        idx = st.selectbox("Befund", range(min(len(shown), 200)), key="dx_pick",
                           format_func=lambda i: f"[{shown[i].priority_label}] {shown[i].sheet} Z{shown[i].row}: {shown[i].message[:90]}")
        f = shown[idx]
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(f"**Wo:** {f.file} → {f.sheet}, Zeile {f.row}, Feld `{f.field_name}`")
            st.markdown(f"**Wert:** `{f.value}`")
            st.markdown(f"**Warum ein Problem:** {f.explanation or f.message}")
            st.markdown(f"**Mögliche Ursache:** {f.cause or '-'}")
        with d2:
            st.markdown(f"**Auswirkung:** {f.business_impact or '-'}")
            st.markdown(f"**Korrekturvorschlag:** {f.correction_suggestion or 'Fachlich prüfen'}")
            cur = st.session_state.finding_status.get(f.finding_id, f.status)
            opts = ["Offen", "In_Bearbeitung", "Abgelehnt", "Behoben"]
            new = st.selectbox("Status", opts, index=opts.index(cur) if cur in opts else 0, key=f"dx_status_{f.finding_id}")
            if new != cur:
                st.session_state.finding_status[f.finding_id] = new
                if new == "Behoben":
                    st.session_state.resolved_ids.add(f.finding_id)
                else:
                    st.session_state.resolved_ids.discard(f.finding_id)
            st.caption("Der Status gilt für diese Sitzung. Es werden keine Quelldaten verändert.")
    df = findings_to_dataframe(shown or fs)
    e1, e2 = st.columns(2)
    e1.download_button("Befunde als CSV exportieren", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="befunde_fachbereich.csv", mime="text/csv", key="dx_csv")
    e2.download_button("Befunde als Excel exportieren", _xlsx_bytes(df), file_name="befunde_fachbereich.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dx_xlsx")


# ------------------------------------------------------------- Governance --
def _governance(ctx: Ctx) -> None:
    st.subheader("Welches System ist wofür maßgeblich?")
    lead = ctx.cfg.leading_systems
    st.dataframe(pd.DataFrame([{"Datenbereich": k.replace("_", " "), "Führendes System": v.replace("_", " "),
                                "Status": "Entscheidung offen" if v.startswith("Governance") else "festgelegt"}
                               for k, v in lead.items()]), use_container_width=True, hide_index=True)
    open_dec = [k for k, v in lead.items() if v.startswith("Governance")]
    if open_dec:
        st.warning("Offene Governance-Entscheidungen: " + ", ".join(k.replace("_", " ") for k in open_dec)
                   + ". Dort gibt es Abweichungen, weil kein System als maßgeblich festgelegt ist.")
    st.subheader("Wie hängen die Daten zusammen?")
    st.dataframe(pd.DataFrame([
        {"Von": "SAP MATNR", "Nach": "Salesforce Product2.ATN_SAP_Materialnummer__c, HubSpot atn_sap_materialnummer",
         "Art": "gleicher Schlüssel"},
        {"Von": "Salesforce Product2.Id", "Nach": "PricebookEntry.Product2Id, Asset.Product2Id", "Art": "Fremdschlüssel"},
        {"Von": "Salesforce Asset.Id", "Nach": "WorkOrder.AssetId", "Art": "Fremdschlüssel"},
        {"Von": "Salesforce Account.Id", "Nach": "Contact.AccountId, Asset.AccountId, WorkOrder.AccountId", "Art": "Fremdschlüssel"},
        {"Von": "HubSpot Products.hs_object_id", "Nach": "Price Book Items.hs_associated_product_id", "Art": "Fremdschlüssel"},
    ]), use_container_width=True, hide_index=True)
    st.subheader("Wer verantwortet was?")
    cnt = Counter(f.responsibility or "Unzugeordnet" for f in ctx.findings)
    resp = ctx.cfg.responsibilities
    rows = [{"Fehlerkategorie": k.replace("_", " "), "Verantwortlich": v,
             "Befunde": sum(1 for f in ctx.findings if f.category == k)} for k, v in resp.items()]
    st.dataframe(pd.DataFrame(rows).sort_values("Befunde", ascending=False), use_container_width=True, hide_index=True)
    st.caption("Quelle: config/governance.yaml. Das sind Vorschläge der Konfiguration, keine bestätigten Rollen im Unternehmen.")
    b1, b2 = st.columns(2)
    if b1.button("Fehler-Stammbaum öffnen", key="gov_tree"):
        ctx.goto_page("Fehler-Stammbaum")
    if b2.button("Ursachenanalyse", key="gov_cause"):
        ctx.goto_page("Ursachenanalyse")


# ---------------------------------------------------------------- Head of AI --
def _ai(ctx: Ctx) -> None:
    pkg = ctx.pkg
    files = {s.source_file for s in pkg.sheets.values()}
    records = sum(len(s.df) for s in pkg.sheets.values())
    n_custom = sum(1 for r in ctx.rules_info if r["source"] == "Benutzer" and r["enabled"])
    st.subheader("So entsteht die Befundliste")
    c = st.columns(5)
    for col, (label, val) in zip(c, [("Dateien", len(files)), ("Tabellenblätter", len(pkg.sheets)),
                                     ("Datensätze", f"{records:,}".replace(",", ".")),
                                     ("Aktive Regeln", ctx.result.rule_count), ("Befunde", len(ctx.findings))]):
        ctx.kpi(col, label, str(val))
    st.markdown(
        "**Ablauf:** Excel einlesen → Kopfzeile erkennen → Felder normalisieren → jede aktive Regel prüft jede Zeile → "
        "Befund mit Datei, Blatt, Zeile, Feld → Land/Region und Verantwortlicher zuordnen → Priorität berechnen → Score.")
    st.subheader("Wo wird KI eingesetzt, wo bewusst nicht?")
    st.dataframe(pd.DataFrame([
        {"Baustein": "Prüfregeln", "Technik": "deterministisch (Regeln, Muster, Vergleiche)",
         "Warum": "Jeder Befund ist reproduzierbar und erklärbar."},
        {"Baustein": "Schweregrad und Score", "Technik": "Gewichte in config/weights.yaml",
         "Warum": "Bewusst nicht KI-gesteuert: Das Management muss die Bewertung nachvollziehen und ändern können."},
        {"Baustein": "Regelvorschläge", "Technik": "Statistik auf den Daten (Muster, Perzentile)",
         "Warum": "Vorschläge werden nie automatisch aktiv, ein Mensch bestätigt."},
        {"Baustein": "DQ-Assistent", "Technik": "regelbasiert, ohne externen Dienst",
         "Warum": "Antwortet nur aus Daten, Regeln und Befunden. Keine Cloud, keine Kosten."},
        {"Baustein": "Sprachmodell", "Technik": "nicht eingesetzt",
         "Warum": "Ein lokales Modell könnte Fragen freier verstehen; Antworten bleiben an die Befunde gebunden."},
    ]), use_container_width=True, hide_index=True)
    st.caption(f"Benutzerregeln aktiv: {n_custom}. Das Tool arbeitet mit beliebigen Spalten; Regeln werden über die Oberfläche ergänzt.")
    st.subheader("Befund bis zur Quellzeile zurückverfolgen")
    if ctx.findings:
        top = sorted(ctx.findings, key=lambda f: -f.priority_score)[:100]
        i = st.selectbox("Befund", range(len(top)), key="ai_trace",
                         format_func=lambda i: f"{top[i].rule_name} · {top[i].sheet} Z{top[i].row}")
        f = top[i]
        sheet = next((s for s in pkg.sheets.values() if s.source_file == f.file and s.sheet_name == f.sheet), None)
        st.markdown(f"**Regel:** `{f.rule_id}` {f.rule_name}  \n**Befund:** {f.message}  \n"
                    f"**Quelle:** {f.file} → {f.sheet} → Excel-Zeile {f.row}, Feld `{f.field_name}`")
        if sheet is not None:
            idx = f.row - sheet.header_row - 2
            if 0 <= idx < len(sheet.df):
                st.markdown("**Originalzeile aus der Excel-Datei:**")
                st.dataframe(sheet.df.iloc[[idx]].astype(str), use_container_width=True, hide_index=True)
    b1, b2 = st.columns(2)
    if b1.button("Regelvorschläge ansehen", key="ai_sugg"):
        ctx.goto_page("Regeln")
    if b2.button("DQ-Assistent testen", key="ai_chat"):
        ctx.goto_page("DQ-Assistent")
