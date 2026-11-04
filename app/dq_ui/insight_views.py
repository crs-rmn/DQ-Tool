"""Euro-Risiko, Fehler-Stammbaum und DQ-Assistent."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from atn_dq.chatbot import DQAssistant
from atn_dq.financial import NOT_CALCULABLE, total_calculated
from atn_dq.lineage import LAYERS, build_lineage, downstream, matnrs_with_findings, root_nodes

from .ctx import Ctx
from .rules_view import build_rules_info
from atn_dq.custom_rules import load_custom_rules

SEV_NODE = {"hoch": "#b31b2a", "mittel": "#e8a33a", "niedrig": "#7aa97f", None: "#9aa9bd"}


# ---------------------------------------------------------------- Finanzen --
def financial_block(ctx: Ctx, compact: bool = False) -> None:
    total, n_calc = total_calculated(ctx.impacts)
    if not compact:
        c1, c2, c3 = st.columns(3)
        ctx.kpi(c1, "Belastbar berechnetes Risiko",
                f"≥ {total:,.0f} €".replace(",", ".") if total is not None else "n/a",
                help_text=f"Summe aus {n_calc} berechenbaren Positionen. Verschiedene Risikoarten, keine Prognose, kein Schaden."
                if total is not None else NOT_CALCULABLE)
        ctx.kpi(c2, "Positionen berechenbar", f"{n_calc} von {len(ctx.impacts)}")
        ctx.kpi(c3, "Nicht berechenbar", f"{len(ctx.impacts) - n_calc}",
                help_text="Hier fehlen Daten. Es wird bewusst kein Betrag geschätzt.")
        st.markdown(" ")
    for it in ctx.impacts:
        icon = {"berechnet": "🟢", "teilweise": "🟡"}.get(it.status, "⚪")
        amount = it.amount_label
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            h1.markdown(f"**{icon} {it.title}**  \n<small>{it.cause}</small>", unsafe_allow_html=True)
            h2.markdown(f"<div style='text-align:right;font-size:1.3rem;font-weight:700'>{amount}</div>"
                        f"<div style='text-align:right'><small>Status: {it.status} · {it.records} Datensätze</small></div>",
                        unsafe_allow_html=True)
            if not compact:
                st.markdown(f"**Berechnungsgrundlage:** {it.basis}")
                st.markdown("**Verwendete Daten:** " + "; ".join(it.data_used))
                st.markdown(f"**Unsicherheit:** {it.uncertainty}")
                if it.details is not None and len(it.details):
                    with st.expander(f"Betroffene Datensätze ({len(it.details)})"):
                        st.dataframe(it.details, use_container_width=True, hide_index=True)


def render_financial(ctx: Ctx) -> None:
    st.title("Geschäftliche Auswirkungen")
    st.markdown('<p class="subtitle">Was kosten schlechte Daten? Nur dort ein Betrag, wo die Daten ihn tragen.</p>',
                unsafe_allow_html=True)
    st.info("Alle Beträge sind **Risikospannen aus euren Daten**, keine entstandenen Schäden. "
            "Wo Mengen, Werte oder Sätze fehlen, steht „Finanzieller Einfluss nicht zuverlässig berechenbar“.")
    financial_block(ctx)
    rows = [{"Position": i.title, "Betrag (EUR)": i.amount_eur} for i in ctx.impacts if i.amount_eur]
    if rows:
        fig = px.bar(pd.DataFrame(rows), x="Betrag (EUR)", y="Position", orientation="h")
        fig.update_layout(height=200 + 30 * len(rows), margin=dict(l=0, r=10, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------- Stammbaum --
def _layout(lin):
    pos, per_layer = {}, {}
    for n in sorted(lin.nodes.values(), key=lambda n: (n.layer, n.system, n.sheet, n.row)):
        per_layer.setdefault(n.layer, []).append(n)
    for layer, ns in per_layer.items():
        for i, n in enumerate(ns):
            pos[n.node_id] = (layer, -(i - (len(ns) - 1) / 2))
    return pos


def render_lineage(ctx: Ctx) -> None:
    st.title("Fehler-Stammbaum")
    st.markdown('<p class="subtitle">Wie wirkt ein Datenfehler über SAP, Salesforce, HubSpot und Service hinweg?</p>',
                unsafe_allow_html=True)
    cand = matnrs_with_findings(ctx.findings)
    if not cand:
        st.info("Keine Produkt-Befunde mit Materialnummer vorhanden.")
        return
    names = {}
    fert = ctx.pkg.get("SAP_FERT")
    if fert is not None:
        names = {str(r["MATNR"]).replace(".0", ""): str(r.get("MAKTX", "")) for _, r in fert.df.iterrows()}
    lookup = dict(cand)
    default = st.session_state.get("lin_matnr")
    ids = [m for m, _ in cand]
    sel = st.selectbox("Produkt (Materialnummer)", ids, index=ids.index(default) if default in ids else 0,
                       format_func=lambda m: f"{m} · {names.get(m, '')} · {lookup[m]} Befunde", key="lin_select")
    st.session_state.lin_matnr = sel
    lin = build_lineage(ctx.pkg, ctx.findings, sel)
    pos = _layout(lin)

    ex, ey = [], []
    for e in lin.edges:
        if e.src in pos and e.dst in pos:
            ex += [pos[e.src][0], pos[e.dst][0], None]
            ey += [pos[e.src][1], pos[e.dst][1], None]
    nodes = list(lin.nodes.values())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="#9aa9bd", width=1.5), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(
        x=[pos[n.node_id][0] for n in nodes], y=[pos[n.node_id][1] for n in nodes], mode="markers+text",
        text=[n.label.replace("\n", "<br>") for n in nodes], textposition="bottom center", textfont=dict(size=12),
        customdata=[n.node_id for n in nodes],
        marker=dict(size=[30 if n.findings else 20 for n in nodes], color=[SEV_NODE[n.severity] for n in nodes],
                    line=dict(width=[3 if n.node_id == st.session_state.get("lin_node") else 1 for n in nodes], color="#1f2a37")),
        hovertext=[f"{n.system} · {n.sheet} · Zeile {n.row}<br>{len(n.findings)} Befund(e)" for n in nodes],
        hoverinfo="text", showlegend=False))
    for i, name in enumerate(LAYERS):
        fig.add_annotation(x=i, y=1.07, yref="paper", text=f"<b>{name}</b>", showarrow=False)
        if not any(n.layer == i for n in nodes):
            fig.add_annotation(x=i, y=0, text="keine verbundenen<br>Datensätze", showarrow=False,
                               font=dict(color="#9aa9bd", size=12))
    fig.update_xaxes(visible=False, range=[-0.5, 3.5])
    fig.update_yaxes(visible=False)
    fig.update_layout(height=max(420, 90 * max(len([n for n in nodes if n.layer == l]) for l in range(4)) + 120),
                      margin=dict(l=0, r=0, t=40, b=0), clickmode="event+select")
    ev = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", key=f"lin_chart_{sel}")
    pts = []
    try:
        pts = ev["selection"]["points"]
    except Exception:  # noqa: BLE001
        pts = []
    if pts:
        cd = pts[0].get("customdata")
        cd = cd[0] if isinstance(cd, list) and cd else cd
        if cd in lin.nodes and st.session_state.get("lin_node") != cd:
            st.session_state.lin_node = cd
            st.rerun()
    st.caption("🔴 kritisch · 🟠 mittel · 🟢 niedrig · ⚪ ohne Befund. **Linien = nachgewiesene Beziehung** "
               "(gleicher Schlüssel bzw. Fremdschlüssel in den Daten). Klick auf einen Punkt zeigt Details.")
    if lin.truncated:
        st.caption("Zur Übersicht gekürzt: " + ", ".join(f"+{v} weitere {k}" for k, v in lin.truncated.items())
                   + " (die mit den meisten Befunden bleiben sichtbar).")

    roots = root_nodes(lin)
    node_ids = list(lin.nodes)
    cur = st.session_state.get("lin_node")
    if cur not in lin.nodes:
        cur = roots[0].node_id if roots else node_ids[0]
    pick = st.selectbox("Knoten im Detail (oder im Diagramm anklicken)", node_ids,
                        index=node_ids.index(cur), key=f"lin_pick_{sel}",
                        format_func=lambda i: f"{lin.nodes[i].system} · {lin.nodes[i].sheet} Z{lin.nodes[i].row} "
                                              f"({len(lin.nodes[i].findings)} Befunde)")
    st.session_state.lin_node = pick
    node = lin.nodes[pick]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Ursprünglicher Fehler")
        if roots:
            st.write("Frühester Befund in der Kette (mögliche Ursache): "
                     + ", ".join(f"**{r.system}/{r.sheet} Z{r.row}**" for r in roots))
            for r in roots:
                for f in r.findings[:3]:
                    st.markdown(f"- {f.rule_name}: {f.message}")
        else:
            st.write("Kein Befund in dieser Kette.")
        st.markdown("#### Gewählter Datensatz")
        st.markdown(f"**{node.system} · {node.sheet} · Excel-Zeile {node.row}**")
        if node.findings:
            st.dataframe(pd.DataFrame([{"Schwere": f.severity, "Regel": f.rule_name, "Feld": f.field_name,
                                        "Wert": str(f.value), "Befund": f.message} for f in node.findings]),
                         use_container_width=True, hide_index=True)
        else:
            st.caption("Dieser Datensatz hat keinen Befund.")
    with c2:
        st.markdown("#### Betroffene Systeme und Datensätze")
        down = downstream(lin, node.node_id)
        affected = [d for d in down if d.findings]
        st.write(f"Nachgelagert verbunden: **{len(down)} Datensätze**, davon **{len(affected)} mit eigenen Befunden**.")
        if down:
            st.dataframe(pd.DataFrame([{"System": d.system, "Objekt": d.sheet, "Zeile": d.row,
                                        "Befunde": len(d.findings)} for d in down]),
                         use_container_width=True, hide_index=True, height=180)
        st.markdown("#### Begründung der Verbindung")
        ev_edges = [e for e in lin.edges if e.src == node.node_id or e.dst == node.node_id]
        if ev_edges:
            for e in ev_edges[:8]:
                other = lin.nodes[e.dst if e.src == node.node_id else e.src]
                st.markdown(f"- ✅ **nachgewiesen** mit {other.system}/{other.sheet} Z{other.row}: {e.evidence}")
        else:
            st.caption("Keine Verbindung in den Daten.")
    st.markdown("#### Mögliche Folgefehler")
    st.markdown("**Nachgewiesen (eigener Befund auf verbundenem Datensatz):**")
    shown = False
    for d in affected[:8]:
        shown = True
        st.markdown(f"- {d.system}/{d.sheet} Z{d.row}: " + "; ".join(f.message[:90] for f in d.findings[:2]))
    if not shown:
        st.caption("Keine nachgelagerten Datensätze mit Befunden.")
    st.markdown("**Vermutet (Text aus der Befundbeschreibung, in den Daten nicht belegt):**")
    if lin.assumed:
        for txt, src in lin.assumed[:6]:
            st.markdown(f"- *{txt}* - aus „{src}“")
    else:
        st.caption("Keine vermuteten Auswirkungen hinterlegt.")
    st.caption("Es werden nur Beziehungen gezeichnet, die in den Daten tatsächlich vorkommen. "
               "Vermutungen stehen getrennt und gelten nicht als Tatsache.")


# --------------------------------------------------------------- Assistent --
SAMPLES = [
    "Welche Fehler betreffen Salesforce?",
    "Ist ein Produktpreis von 1.000.000 € plausibel?",
    "Welche Produkte haben ungewöhnlich hohe Preise?",
    "Was sind die kritischsten Befunde?",
    "Welche Regeln sind aktiv?",
]


def render_assistant(ctx: Ctx) -> None:
    st.title("DQ-Assistent")
    st.markdown('<p class="subtitle">Fragen zu Daten, Regeln und Befunden - Antworten nur aus euren echten Daten.</p>',
                unsafe_allow_html=True)
    st.caption("Regelbasierter Prototyp: kein externer KI-Dienst, keine Kosten. Der Assistent ändert niemals Daten "
               "und sagt, wenn eine fachliche Prüfung nötig ist. Tipp: Materialnummern wie 1000000020 oder Produktcodes wie AFR-190 nennen.")
    info = build_rules_info(ctx.config_dir, ctx.result, load_custom_rules(ctx.config_dir))
    bot = DQAssistant(ctx.pkg, ctx.findings, ctx.cfg, info, ctx.overall, ctx.regions)
    hist = st.session_state.setdefault("chat", [])
    clicked = None
    for row in (SAMPLES[:3], SAMPLES[3:]):
        for c, s in zip(st.columns(3), row):
            if c.button(s, key=f"sample_{s}", use_container_width=True):
                clicked = s
    for i, m in enumerate(hist):
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m.get("evidence"):
                with st.expander(f"Belege ({len(m['evidence'])})"):
                    st.dataframe(pd.DataFrame(m["evidence"]), use_container_width=True, hide_index=True)
            if m.get("filters"):
                if st.button("In der Befundliste öffnen", key=f"chat_open_{i}"):
                    ctx.goto_findings(m["filters"])
    q = st.chat_input("Frage stellen, z. B. „Warum ist 1000000020 kritisch?“") or clicked
    if q:
        a = bot.answer(q)
        hist.append({"role": "user", "text": q})
        hist.append({"role": "assistant", "text": a.text, "evidence": a.evidence, "filters": a.filters})
        st.rerun()
    if hist and st.button("Verlauf löschen", key="chat_clear"):
        st.session_state.chat = []
        st.rerun()
