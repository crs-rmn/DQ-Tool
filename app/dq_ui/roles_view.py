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


# ------------------------------------------------ CEO: Themen statt Einzelbefunde --
THEMES = [  # (Präfix der Kategorie, Themenname, Erklärung für das Management)
    ("Referenz", "Kaputte Verknüpfungen zwischen Datensätzen",
     "Aufträge, Anlagen, Kontakte oder Preislisten zeigen auf Datensätze, die es nicht (mehr) gibt."),
    ("Eindeutigkeit", "Doppelte Datensätze und Schlüssel",
     "Dieselbe Materialnummer oder Seriennummer kommt mehrfach vor. Auswertungen und Bestellungen werden unsicher."),
    ("Konsistenz_Preis", "Preise widersprechen sich zwischen Systemen",
     "Derselbe Artikel hat in Salesforce und HubSpot unterschiedliche Preise."),
    ("Validitaet_Preis", "Ungültige oder unplausible Preise",
     "Preise sind leer, negativ oder liegen unter den Herstellkosten."),
    ("Konsistenz_Produkt", "Produktstammdaten passen nicht zusammen",
     "Namen oder Eigenschaften desselben Produkts unterscheiden sich zwischen den Systemen."),
    ("Validitaet_Datum", "Unplausible Datumsangaben",
     "Termine liegen in falscher Reihenfolge oder außerhalb des sinnvollen Zeitraums."),
    ("Vollstaendigkeit", "Fehlende Pflichtangaben",
     "Pflichtfelder sind leer, dadurch sind Datensätze nicht nutzbar."),
    ("Validitaet_Status", "Ungültige Statuswerte",
     "Status- oder Auswahlfelder enthalten Werte, die nicht erlaubt sind."),
    ("Benutzerregel", "Eigene Regeln (z. B. Zoll, Herkunft, Branche)",
     "Verstöße gegen Regeln, die das Team selbst angelegt hat."),
    ("Anomalie", "Auffällige Ausreißer", "Werte weichen stark vom üblichen Bereich ab."),
]


def _theme_of(f) -> tuple[str, str]:
    for prefix, name, expl in THEMES:
        if f.category.startswith(prefix):
            return name, expl
    return "Sonstige Probleme", "Weitere Regelverstöße."


def build_themes(findings, max_themes: int = 10) -> list[dict]:
    """Fasst kritische Befunde zu wenigen Themen zusammen (Rang: Summe der Prioritätswerte)."""
    from atn_dq.insights import unique_affected_records
    buckets: dict[str, list] = {}
    expl: dict[str, str] = {}
    for f in findings:
        name, ex = _theme_of(f)
        buckets.setdefault(name, []).append(f)
        expl[name] = ex
    themes = []
    for name, fs in buckets.items():
        resp = Counter(f.responsibility for f in fs if f.responsibility).most_common(1)
        themes.append({
            "name": name, "explain": expl[name], "findings": fs, "count": len(fs),
            "records": len(unique_affected_records(fs)),
            "systems": [k for k, _ in Counter(f.system for f in fs).most_common()],
            "rank": sum(f.priority_score for f in fs),
            "owner": resp[0][0] if resp else "",
            "example": max(fs, key=lambda x: x.priority_score).message,
        })
    themes.sort(key=lambda t: -t["rank"])
    if len(themes) > max_themes:      # Rest zu einem Sammelthema
        rest = themes[max_themes - 1:]
        fs = [f for t in rest for f in t["findings"]]
        themes = themes[:max_themes - 1] + [{
            "name": "Weitere Themen", "explain": "Kleinere Themen: " + ", ".join(t["name"] for t in rest),
            "findings": fs, "count": len(fs), "records": len(unique_affected_records(fs)),
            "systems": [k for k, _ in Counter(f.system for f in fs).most_common()],
            "rank": 0, "owner": "", "example": max(fs, key=lambda x: x.priority_score).message}]
    return themes


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _ceo_themes(ctx: Ctx, sel: dict) -> None:
    crit = [f for f in ctx.findings if f.severity == "hoch"]
    themes = build_themes(crit)
    st.subheader("Die wichtigsten Themen")
    st.caption(f"{_fmt(len(crit))} kritische Befunde, zusammengefasst zu {len(themes)} Themen. "
               "Rang = Anzahl × Dringlichkeit. Die drei wichtigsten sind hervorgehoben.")
    top, rest = themes[:3], themes[3:]
    for col, t in zip(st.columns(len(top)), top):
        with col, st.container(border=True):
            st.markdown(f"**🔴 {t['name']}**")
            st.markdown(f"<span style='font-size:1.7rem;font-weight:700;color:#b31b2a'>{_fmt(t['records'])}</span> "
                        f"betroffene Datensätze", unsafe_allow_html=True)
            st.caption(f"{_fmt(t['count'])} Befunde · {', '.join(t['systems'])}")
            st.write(t["explain"])
            if t["owner"]:
                st.caption(f"Zuständig: {t['owner']}")
            if st.button("Probleme ansehen", key=f"theme_{t['name']}", use_container_width=True):
                sel["Thema"] = t["name"]
                st.session_state.ceo_sel = sel
                st.rerun()
    if rest:
        with st.expander(f"Weitere Themen ({len(rest)})", expanded=False):
            for t in rest:
                c = st.columns([5, 2, 2])
                c[0].markdown(f"**{t['name']}**  \n<small>{t['explain']}</small>", unsafe_allow_html=True)
                c[1].markdown(f"{_fmt(t['records'])} Datensätze  \n<small>{', '.join(t['systems'])}</small>",
                              unsafe_allow_html=True)
                if c[2].button("Ansehen", key=f"theme_{t['name']}"):
                    sel["Thema"] = t["name"]
                    st.session_state.ceo_sel = sel
                    st.rerun()
    return themes


def _theme_facts(t: dict) -> dict:
    """Echte Kennzahlen je Thema, abgeleitet aus den Befunden."""
    fs = t["findings"]
    objs = Counter(f"{f.system} · {f.sheet}" for f in fs).most_common(2)
    corr = Counter(f.correction_suggestion for f in fs if f.correction_suggestion).most_common(1)
    fld = Counter(f.field_name for f in fs if f.field_name).most_common(1)
    return {"objects": ", ".join(o for o, _ in objs), "rules": len({f.rule_id for f in fs}),
            "rule": Counter(f.rule_name for f in fs).most_common(1)[0][0],
            "correction": corr[0][0] if corr else "", "field": fld[0][0] if fld else ""}


def _rule_table(fs, limit: int = 10) -> None:
    """Kompakte Tabelle: ein Eintrag je Regel statt tausender Einzelbefunde."""
    groups: dict[str, list] = {}
    for f in fs:
        groups.setdefault(f.rule_id, []).append(f)
    rows = []
    for g in sorted(groups.values(), key=lambda g: -len(g))[:limit]:
        f0 = max(g, key=lambda x: x.priority_score)
        rows.append({"Problem": f0.rule_name, "Anzahl": len(g), "Feld": f0.field_name,
                     "Beispiel": f0.message[:110], "Korrekturvorschlag": f0.correction_suggestion or "Fachlich prüfen"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if len(groups) > limit:
        st.caption(f"{len(groups) - limit} weitere Regeln. Vollständige Liste in der Befundliste.")


def _theme_cards(ctx: Ctx, findings, key: str, lines, title: str = "Die wichtigsten Themen",
                 selectable: bool = True):
    """Themen-Karten (3 hervorgehoben). Liefert das gewählte Thema (dict) oder None."""
    themes = build_themes(findings)
    state = f"{key}_theme"
    st.subheader(title)
    if not themes:
        st.success("Keine kritischen Themen.")
        return None
    st.caption(f"{_fmt(len(findings))} Befunde, zusammengefasst zu {len(themes)} Themen. "
               "Rang = Anzahl × Dringlichkeit. Die drei wichtigsten sind hervorgehoben.")
    top, rest = themes[:3], themes[3:]

    def pick(t):
        st.session_state[state] = t["name"]
        st.rerun()

    for col, t in zip(st.columns(len(top)), top):
        with col, st.container(border=True):
            st.markdown(f"**🔴 {t['name']}**")
            st.markdown(f"<span style='font-size:1.7rem;font-weight:700;color:#b31b2a'>{_fmt(t['records'])}</span> "
                        f"betroffene Datensätze", unsafe_allow_html=True)
            st.caption(f"{_fmt(t['count'])} Befunde · {', '.join(t['systems'])}")
            st.write(t["explain"])
            for ln in lines(t, _theme_facts(t)):
                st.caption(ln)
            if selectable and st.button("Details ansehen", key=f"{key}_pick_{t['name']}", use_container_width=True):
                pick(t)
    if rest:
        with st.expander(f"Weitere Themen ({len(rest)})", expanded=False):
            for t in rest:
                c = st.columns([5, 2, 2])
                c[0].markdown(f"**{t['name']}**  \n<small>{t['explain']}</small>", unsafe_allow_html=True)
                c[1].markdown(f"{_fmt(t['records'])} Datensätze  \n<small>{', '.join(t['systems'])}</small>",
                              unsafe_allow_html=True)
                if selectable and c[2].button("Ansehen", key=f"{key}_pick_{t['name']}"):
                    pick(t)
    chosen = next((t for t in themes if t["name"] == st.session_state.get(state)), None)
    if chosen and selectable:
        bc = st.columns([6, 1])
        bc[0].markdown(f"**Gewähltes Thema:** {chosen['name']}")
        if bc[1].button("Zurücksetzen", key=f"{key}_reset"):
            st.session_state.pop(state, None)
            st.rerun()
        return chosen
    return None


def _ceo(ctx: Ctx) -> None:
    f_all = ctx.findings
    valid = sorted([r for r in ctx.regions if r.sufficient_data], key=lambda r: r.score)
    total, n_calc = total_calculated(ctx.impacts)

    c1, c2, c3, c4 = st.columns(4)
    ctx.kpi(c1, "Gesamt-Score (0-100)", f"{ctx.overall.score}", help_text="Gewichtete Datenqualität.")
    n_themes = len(build_themes([f for f in f_all if f.severity == "hoch"]))
    ctx.kpi(c2, "Kritische Themen", f"{n_themes}", "prio-h",
            help_text=f"{_fmt(ctx.overall.findings_high)} kritische Befunde, zu Themen zusammengefasst.")
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
    sel = st.session_state.setdefault("ceo_sel", {"Region": None, "System": None, "Ursache": None})
    sel.setdefault("Thema", None)
    _ceo_themes(ctx, sel)
    st.markdown("---")
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
    st.subheader("Details nach Region, System und Ursache")
    st.caption("Klick auf einen Balken filtert die anderen Ansichten. Unten erscheinen die konkreten Probleme.")
    hide_low = st.toggle("Niedrige Befunde ausblenden", value=True, key="ceo_hide_low")
    base = [f for f in f_all if not (hide_low and f.severity == "niedrig")]
    last = st.session_state.setdefault("ceo_last_click", {})

    def sub(skip: str):
        out = base
        if skip != "Region" and sel["Region"]:
            out = [f for f in out if (f.region or "Nicht zugeordnet") == sel["Region"]]
        if skip != "System" and sel["System"]:
            out = [f for f in out if f.system == sel["System"]]
        if skip != "Ursache" and sel["Ursache"]:
            out = [f for f in out if _label(f.category) == sel["Ursache"]]
        if sel.get("Thema"):
            out = [f for f in out if _theme_of(f)[0] == sel["Thema"]
                   or (sel["Thema"] == "Weitere Themen" and f.severity == "hoch")]
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
            st.session_state.ceo_sel = {"Region": None, "System": None, "Ursache": None, "Thema": None}
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

    chosen = _theme_cards(
        ctx, [f for f in fs if f.severity == "hoch"], "mdm",
        lambda t, x: [f"Datenobjekte: {x['objects']}", f"Maßnahme: {x['correction'] or 'fachlich prüfen'}"])
    if chosen:
        _rule_table(chosen["findings"])
        if st.button("Dieses Thema in der Befundliste öffnen", key="mdm_theme_open"):
            ctx.goto_findings({"System": chosen["systems"]})

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

    crit = [f for f in fs if f.severity == "hoch"] or [f for f in fs if f.severity == "mittel"] or fs
    chosen = _theme_cards(
        ctx, crit, "dx",
        lambda t, x: [f"Betroffenes Feld: {x['field'] or '-'}", f"Korrektur: {x['correction'] or 'fachlich prüfen'}"],
        title="Was ist falsch und was ist zu tun?")
    shown = chosen["findings"] if chosen else []
    if chosen:
        _rule_table(shown, limit=15)
        st.subheader("Einzelnes Problem prüfen")
        top = sorted(shown, key=lambda x: -x.priority_score)[:50]
        idx = st.selectbox("Beispiel (die 50 dringendsten)", range(len(top)), key="dx_pick",
                           format_func=lambda i: f"[{top[i].priority_label}] {top[i].sheet} Z{top[i].row}: {top[i].message[:90]}")
        f = top[idx]
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
    else:
        st.caption("Wähle ein Thema, um die konkreten Probleme, Korrekturvorschläge und den Export zu sehen.")
    df = findings_to_dataframe(shown or fs)
    st.caption("Export: " + ("gewähltes Thema" if shown else "alle Befunde dieses Fachbereichs"))
    e1, e2 = st.columns(2)
    e1.download_button("Befunde als CSV exportieren", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="befunde_fachbereich.csv", mime="text/csv", key="dx_csv")
    e2.download_button("Befunde als Excel exportieren", _xlsx_bytes(df), file_name="befunde_fachbereich.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dx_xlsx")


# ------------------------------------------------------------- Governance --
def _governance(ctx: Ctx) -> None:
    gov_fs = [f for f in ctx.findings if f.severity == "hoch"]

    def gov_lines(t, x):
        cross = "systemübergreifend, Governance-Entscheidung nötig" if len(t["systems"]) > 1 else "innerhalb eines Systems"
        return [f"Zuständig laut Konfiguration: {t['owner'] or 'nicht zugeordnet'}", f"Reichweite: {cross}"]

    chosen = _theme_cards(ctx, gov_fs, "gov", gov_lines, title="Themen mit Klärungsbedarf")
    if chosen:
        _rule_table(chosen["findings"], limit=8)
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
    chosen = _theme_cards(
        ctx, [f for f in ctx.findings if f.severity == "hoch"], "ai",
        lambda t, x: [f"Geprüft durch {x['rules']} Regel(n), häufigste: {x['rule']}",
                      f"Nachvollziehbar bis zur Excel-Zeile"],
        title="Wo findet das Tool die meisten kritischen Probleme?")
    st.subheader("Befund bis zur Quellzeile zurückverfolgen")
    if not chosen:
        st.caption("Wähle oben ein Thema, dann kannst du einen Befund bis zur Originalzeile zurückverfolgen.")
    if chosen:
        top = sorted(chosen["findings"], key=lambda f: -f.priority_score)[:50]
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
