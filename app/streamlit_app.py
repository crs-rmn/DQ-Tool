"""AgroTechNova Data Quality Copilot - Streamlit Dashboard.

Startet mit::

    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import plotly.express as px
import streamlit as st

from atn_dq.config import load_config
from atn_dq.engine import run_analysis
from atn_dq.export import export_csv, export_xlsx, findings_to_dataframe
from atn_dq.history import HistoryDB
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
from atn_dq.loader import load_package
from atn_dq.score import overall_score, region_scores
from atn_dq.rules import registry
from atn_dq.custom_rules import apply_builtin_state, load_custom_rules
from atn_dq.financial import compute_impacts
from atn_dq.roles import load_roles
from dq_ui import insight_views, roles_view, rules_view
from dq_ui.ctx import Ctx


# -------------------------------------------------------------------- Setup --
st.set_page_config(
    page_title="AgroTechNova Data Quality Copilot",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px;}
.main h1 {margin-bottom: 0;}
.subtitle {color: #556677; margin-top: -0.4rem; margin-bottom: 1.5rem;}
.kpi {background: #f7f9fb; border: 1px solid #e3e8ef; border-radius: 10px;
      padding: 1rem 1.2rem; height: 100%;}
.kpi .label {color:#5b6b7f !important; font-size:.85rem; margin:0; font-weight:500;}
.kpi .value {color:#1f2a37; font-size:1.9rem; font-weight:700; margin:.2rem 0 0 0;}
.prio-h {color:#b31b2a;}
.prio-m {color:#b56c00;}
.prio-l {color:#226e35;}
.finding-card {background: white; border: 1px solid #e3e8ef; border-radius: 8px;
               padding: .7rem 1rem; margin-bottom: .4rem;}
.rec-card {background: #ffffff; border:1px solid #e3e8ef; border-left: 5px solid #1a4e82;
           border-radius:8px; padding: .9rem 1.1rem; margin-bottom:.6rem;}
.rec-card.high {border-left-color:#c0392b;}
.rec-card.mid  {border-left-color:#e67e22;}
.rec-card .title {font-weight:700; font-size:1.02rem; margin:0 0 .2rem 0;}
.rec-card .detail {color:#556677; font-size:.9rem; margin:0;}
.badge {display:inline-block; padding: .1rem .55rem; border-radius: 999px;
        font-size: .75rem; font-weight: 600; margin-right: .3rem;}
.badge-h {background:#fde3e6; color:#9b1b2a;}
.badge-m {background:#fdeccc; color:#8a5100;}
.badge-l {background:#dff1e2; color:#1f5d2f;}
.badge-sys {background:#e6ecf4; color:#20406c;}
.help-text {color:#5b6b7f; font-size:.82rem; margin-top:-.4rem; margin-bottom:.5rem;}
.demo-banner {background:#fff8e1; border:1px solid #f1c40f; border-radius:8px;
              padding:.6rem .9rem; margin-bottom:1rem;}
.demo-step {background:#eef3f8; border-left:4px solid #1a4e82; padding:.4rem .8rem;
            border-radius:6px; margin:.2rem 0;}
</style>
    """,
    unsafe_allow_html=True,
)

INPUT_DIR = ROOT / "data" / "input"
CONFIG_DIR = ROOT / "config"
HISTORY_DB = ROOT / "data" / "history.sqlite"


# -------------------------------------------------------------- Cached loaders --
@st.cache_data(show_spinner=False)
def _load_cfg(cfg_dir: str):
    return load_config(cfg_dir)


@st.cache_data(show_spinner=False)
def _load_pkg(input_dir: str, upload_signature: tuple = ()):
    # ``upload_signature`` dient nur als Cache-Key:
    # (name, size, hash) pro Upload-Datei. Die tatsächlichen Bytes holen
    # wir frisch aus st.session_state, damit der Cache nicht aufgebläht wird.
    extras = []
    if upload_signature:
        uploads = st.session_state.get("uploaded_files_bytes") or {}
        for name, _size, _digest in upload_signature:
            if name in uploads:
                extras.append((name, uploads[name]))
    return load_package(input_dir, extra_bytes=extras or None, require_any=True)


@st.cache_resource(show_spinner=False)
def _history() -> HistoryDB:
    return HistoryDB(HISTORY_DB)


def _upload_signature() -> tuple:
    """Kompakte, hashbare Signatur der aktuellen Uploads für den Cache."""
    uploads = st.session_state.get("uploaded_files_bytes") or {}
    import hashlib
    return tuple(
        (name, len(data), hashlib.sha1(data).hexdigest()[:10])
        for name, data in sorted(uploads.items())
    )


def _run_analysis(cfg_dir: str, input_dir: str):
    cfg = _load_cfg(cfg_dir)
    pkg = _load_pkg(input_dir, _upload_signature())
    apply_builtin_state(cfg_dir, registry)          # dauerhaft gespeicherte Ein/Aus-Zustände
    result = run_analysis(pkg, cfg, custom_rules=load_custom_rules(cfg_dir))
    overall = overall_score(result.findings, pkg, cfg)
    regions = region_scores(result.findings, pkg, cfg)
    return cfg, pkg, result, overall, regions


# --- Session state (Korrektur-Flow, Filter-Push aus Startseite) --------------
if "resolved_ids" not in st.session_state:
    st.session_state.resolved_ids = set()
if "finding_status" not in st.session_state:
    st.session_state.finding_status = {}  # finding_id -> Status
if "jump_filter" not in st.session_state:
    st.session_state.jump_filter = {}
if "nav_target" not in st.session_state:
    st.session_state.nav_target = None
if "uploaded_files_bytes" not in st.session_state:
    # dict: original filename -> bytes (nur in Session)
    st.session_state.uploaded_files_bytes = {}


# ---------------------------------------------------------------- Navigation --
PAGES = [
    "Mein Dashboard",
    "Übersicht",
    "Befunde",
    "Ursachenanalyse",
    "Geschäftliche Auswirkungen",
    "Fehler-Stammbaum",
    "DQ-Assistent",
    "Länder & Regionen",
    "Fachbereiche",
    "Datenquellen",
    "Korrekturvorschläge",
    "Vorher / Nachher",
    "Regeln",
    "Verlauf",
    "Einstellungen",
    "Demo-Ablauf",
]

with st.sidebar:
    st.markdown("### 🌾 AgroTechNova")
    st.markdown("**Data Quality Copilot**")
    st.caption("Datenvertrauen. Transparenz. Bessere Entscheidungen.")
    role_slot = st.container()   # Rollen-Button, wird nach der Analyse gefüllt
    st.divider()
    # falls eine andere Seite die Navigation umschalten will
    default_idx = 0
    if st.session_state.nav_target in PAGES:
        default_idx = PAGES.index(st.session_state.nav_target)
        st.session_state.nav_target = None
    page = st.radio("Bereich", PAGES, index=default_idx, label_visibility="collapsed")
    st.divider()
    # --- Datenquelle & Upload --------------------------------------------
    st.markdown("**Datenquelle**")
    folder_files = sorted(
        p.name for p in INPUT_DIR.glob("*.xlsx") if not p.name.startswith("~$")
    ) if INPUT_DIR.exists() else []
    st.caption(f"Ordner: `{INPUT_DIR.relative_to(ROOT)}` · {len(folder_files)} Datei(en)")
    if folder_files:
        with st.expander("Dateien im Ordner", expanded=False):
            for f in folder_files:
                st.caption(f"• {f}")

    st.markdown("**Dateien hochladen** (Drag & Drop)")
    uploads = st.file_uploader(
        "Excel-Dateien hierher ziehen",
        type=["xlsx"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help=("Dateien werden sofort in die Analyse aufgenommen. "
              "Optional können sie dauerhaft in den Ordner data/input/ gespeichert werden."),
    )
    # alle aktuellen Uploads in den Session-State übernehmen
    if uploads:
        current_names = set()
        for up in uploads:
            current_names.add(up.name)
            st.session_state.uploaded_files_bytes[up.name] = up.getvalue()
        # Dateien, die der Nutzer aus dem Uploader entfernt hat, auch aus der Session entfernen
        for stale in list(st.session_state.uploaded_files_bytes):
            if stale not in current_names:
                del st.session_state.uploaded_files_bytes[stale]

    session_uploads = st.session_state.uploaded_files_bytes
    if session_uploads:
        st.caption(f"Für diese Sitzung geladen: **{len(session_uploads)} Datei(en)**")
        persist = st.checkbox(
            "Auch dauerhaft in data/input/ speichern",
            value=False,
            help="Nur nötig, wenn die Datei auch bei zukünftigen Starts automatisch verwendet werden soll.",
        )
        c_apply, c_clear = st.columns(2)
        if c_apply.button("Analyse starten", type="primary", use_container_width=True):
            if persist:
                INPUT_DIR.mkdir(parents=True, exist_ok=True)
                for name, data in session_uploads.items():
                    (INPUT_DIR / name).write_bytes(data)
                # danach Uploads aus Session leeren (sie sind jetzt im Ordner)
                st.session_state.uploaded_files_bytes = {}
                st.success(f"{len(session_uploads)} Datei(en) in data/input/ gespeichert.")
            st.cache_data.clear()
            st.rerun()
        if c_clear.button("Upload leeren", use_container_width=True):
            st.session_state.uploaded_files_bytes = {}
            st.cache_data.clear()
            st.rerun()
    else:
        if st.button("Analyse neu ausführen", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    st.divider()
    st.caption(f"Version {__import__('atn_dq').__version__}")


# ----------------------------------------------------------------- Run engine --
try:
    cfg, pkg, result, overall, regions = _run_analysis(str(CONFIG_DIR), str(INPUT_DIR))
except ValueError as exc:
    # Freundlicher Hinweis, wenn weder Ordner noch Upload Daten liefern
    st.title("Willkommen beim AgroTechNova Data Quality Copilot")
    st.info(
        "Es wurden noch keine Excel-Dateien geladen.\n\n"
        "**Zwei Wege, Dateien bereitzustellen:**\n\n"
        "1. **Drag & Drop in der Seitenleiste** - Dateien hier in die Upload-Zone ziehen "
        "und auf *Analyse starten* klicken.\n"
        "2. **In den Ordner kopieren** - Dateien direkt in "
        f"`{INPUT_DIR.relative_to(ROOT)}` legen und links auf *Analyse neu ausführen* klicken."
    )
    st.caption(str(exc))
    st.stop()
except Exception as exc:
    st.error(f"Fehler bei der Analyse: {exc}")
    st.stop()

findings = result.findings
affected_count = affected_record_count(findings)


def _badge(label: str) -> str:
    c = {"hoch": "badge-h", "mittel": "badge-m", "niedrig": "badge-l"}.get(label.lower(), "badge-l")
    return f'<span class="badge {c}">{label}</span>'


def kpi(col, label: str, value: str, extra_class: str = "", help_text: str | None = None):
    col.markdown(
        f'<div class="kpi"><p class="label">{label}</p>'
        f'<p class="value {extra_class}">{value}</p></div>',
        unsafe_allow_html=True,
    )
    if help_text:
        col.caption(help_text)


def _go_to_befunde(filters: dict):
    st.session_state.jump_filter = filters
    st.session_state.nav_target = "Befunde"
    st.rerun()


def _go_page(name: str):
    st.session_state.nav_target = name
    st.rerun()


_roles, _areas = load_roles(CONFIG_DIR)
_custom_rules = load_custom_rules(CONFIG_DIR)
ctx = Ctx(
    cfg=cfg, pkg=pkg, result=result, findings=findings, overall=overall, regions=regions,
    impacts=compute_impacts(pkg, findings), roles=_roles, areas=_areas, config_dir=CONFIG_DIR,
    history=_history(), kpi=kpi, badge=_badge, goto_findings=_go_to_befunde, goto_page=_go_page,
    rules_info=rules_view.build_rules_info(CONFIG_DIR, result, _custom_rules),
)
with role_slot:
    roles_view.role_selector(ctx)


# =============================================================================
#                              ÜBERSICHT
# =============================================================================
if page == "Mein Dashboard":
    roles_view.render(ctx)

elif page == "Geschäftliche Auswirkungen":
    insight_views.render_financial(ctx)

elif page == "Fehler-Stammbaum":
    insight_views.render_lineage(ctx)

elif page == "DQ-Assistent":
    insight_views.render_assistant(ctx)

elif page == "Übersicht":
    st.title("Übersicht Datenqualität")
    st.markdown(
        '<p class="subtitle">So steht AgroTechNova heute - wo ist es am dringendsten?</p>',
        unsafe_allow_html=True,
    )

    # KPI-Reihe 1: Umfang
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Gesamt-Score (0-100)", f"{overall.score}",
        help_text="Gewichtete Qualität über alle Dimensionen.")
    kpi(c2, "Geprüfte Datensätze", f"{overall.total_records:,}".replace(",", "."),
        help_text="Zeilen in allen eingelesenen Tabellen.")
    kpi(c3, "Betroffene Datensätze", f"{affected_count:,}".replace(",", "."),
        help_text="Eindeutige Datensätze mit mindestens einem Befund.")
    kpi(c4, "Ausgeführte Regeln", f"{result.rule_count}",
        help_text="Aktive Prüfregeln in diesem Lauf.")

    st.markdown(" ")
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Befunde gesamt", f"{len(findings):,}".replace(",", "."))
    kpi(c2, "Hoch", f"{overall.findings_high}", "prio-h")
    kpi(c3, "Mittel", f"{overall.findings_medium}", "prio-m")
    kpi(c4, "Niedrig", f"{overall.findings_low}", "prio-l")

    st.caption(
        "Hinweis: Ein Datensatz kann mehrere Befunde haben. "
        f"**{len(findings):,} Befunde** verteilen sich auf **{affected_count:,} eindeutige Datensätze** "
        f"(= {(affected_count / max(overall.total_records, 1)) * 100:.1f} % aller geprüften Datensätze)."
        .replace(",", ".")
    )

    st.markdown("---")

    st.subheader("Geschäftliche Auswirkungen")
    st.markdown('<p class="help-text">Nur belastbar berechnete Beträge. Wo Daten fehlen, steht das ausdrücklich da.</p>',
                unsafe_allow_html=True)
    insight_views.financial_block(ctx, compact=True)
    if st.button("Berechnungsgrundlage und Unsicherheit ansehen →", key="ov_fin"):
        _go_page("Geschäftliche Auswirkungen")

    st.markdown("---")

    # === Was sollte als Nächstes erledigt werden? ===
    st.subheader("Was sollte als Nächstes erledigt werden?")
    st.markdown(
        '<p class="help-text">Konkrete Handlungsempfehlungen auf Basis Ihrer realen Daten. '
        'Klick öffnet die passende Befundliste.</p>',
        unsafe_allow_html=True,
    )
    recs = build_recommendations(findings)
    if not recs:
        st.success("Keine Handlungsempfehlungen - die Daten sind in gutem Zustand.")
    for idx, r in enumerate(recs):
        css = "high" if r.count >= 20 else ("mid" if r.count >= 5 else "")
        c_card, c_btn = st.columns([5, 1])
        with c_card:
            st.markdown(
                f'<div class="rec-card {css}">'
                f'<p class="title">{r.title}</p>'
                f'<p class="detail">{r.detail}</p>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with c_btn:
            if st.button("Öffnen →", key=f"rec_open_{idx}", use_container_width=True):
                filters = {}
                if r.filter_category:
                    filters["Fehlerkategorie"] = [r.filter_category]
                if r.filter_system:
                    filters["System"] = [r.filter_system]
                if r.filter_priority:
                    filters["Priorität"] = [r.filter_priority]
                if r.filter_region:
                    filters["Region"] = [r.filter_region]
                _go_to_befunde(filters)

    st.markdown("---")

    # === Dimensionen & Priorität ===
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Qualitäts-Score je Dimension")
        dim_help = {
            "Vollstaendigkeit": "Sind alle wichtigen Angaben vorhanden?",
            "Validitaet":       "Entsprechen die Werte den zulässigen Regeln und Formaten?",
            "Eindeutigkeit":    "Gibt es doppelt vorhandene Datensätze?",
            "Konsistenz":       "Stimmen zusammengehörige Angaben systemübergreifend überein?",
            "Referenz":         "Zeigen Verweise auf existierende Datensätze?",
        }
        dims_df = pd.DataFrame({
            "Dimension": list(overall.by_dimension.keys()),
            "Score": list(overall.by_dimension.values()),
            "Beschreibung": [dim_help.get(d, "") for d in overall.by_dimension.keys()],
        })
        fig = px.bar(
            dims_df, x="Score", y="Dimension", orientation="h",
            range_x=[0, 110], color="Score",
            color_continuous_scale=["#b31b2a", "#e8a33a", "#2b8a3e"],
            text=dims_df["Score"].round(1),
            hover_data={"Beschreibung": True, "Score": ":.1f"},
        )
        fig.update_layout(height=320, coloraxis_showscale=False,
                          margin=dict(l=0, r=10, t=10, b=0))
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("Was bedeuten die Dimensionen?"):
            for dim, desc in dim_help.items():
                st.write(f"**{dim}** — {desc}")
            st.caption(
                "Score pro Dimension = 100 − (gewichtete Befund-Last / geprüfte Datensätze) × 100. "
                "Jeder Befund trägt mit seinem Schweregrad bei (hoch=1,0 · mittel=0,4 · niedrig=0,1). "
                "Gewichte in `config/weights.yaml` konfigurierbar."
            )

    with right:
        st.subheader("Verteilung nach Priorität")
        prio_df = pd.DataFrame(
            {"Priorität": ["Hoch", "Mittel", "Niedrig"],
             "Anzahl": [sum(1 for f in findings if f.priority_label == "Hoch"),
                        sum(1 for f in findings if f.priority_label == "Mittel"),
                        sum(1 for f in findings if f.priority_label == "Niedrig")]}
        )
        fig = px.pie(prio_df, names="Priorität", values="Anzahl",
                     color="Priorität",
                     color_discrete_map={"Hoch": "#c0392b",
                                         "Mittel": "#e67e22",
                                         "Niedrig": "#27ae60"},
                     hole=0.55)
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Qualität je Markt / Region")
    rows = []
    for r in regions:
        rows.append({
            "Region": r.region,
            "Score": None if not r.sufficient_data else r.score,
            "Hoch": r.findings_high,
            "Mittel": r.findings_medium,
            "Niedrig": r.findings_low,
            "Datensatzbasis": r.records_estimated,
            "Status": "Ausreichend" if r.sufficient_data else "Keine ausreichende Datenbasis",
        })
    region_df = pd.DataFrame(rows).sort_values(by="Score", ascending=True, na_position="last")

    def _ampel(score):
        if score is None or pd.isna(score):
            return "⚪ nicht geprüft"
        if score >= 80:
            return "🟢 gut"
        if score >= 60:
            return "🟡 verbesserungsbedürftig"
        return "🔴 kritisch"
    region_df.insert(1, "Ampel", region_df["Score"].apply(_ampel))

    st.dataframe(
        region_df, use_container_width=True, hide_index=True,
        column_config={
            "Score": st.column_config.NumberColumn("Score", format="%.1f", min_value=0, max_value=100),
            "Datensatzbasis": st.column_config.NumberColumn("Datensatzbasis", format="%d"),
        },
    )

    st.subheader("Top 5 dringendste Befunde")
    top5 = findings[:5]
    for f in top5:
        pclass = {"Hoch": "badge-h", "Mittel": "badge-m", "Niedrig": "badge-l"}.get(f.priority_label, "badge-l")
        st.markdown(
            f'<div class="finding-card">'
            f'<span class="badge {pclass}">{f.priority_label} · {f.priority_score:.0f}</span>'
            f'{_badge(f.severity)}'
            f'<span class="badge badge-sys">{f.system}</span>'
            f'<strong>{f.rule_name}</strong><br>'
            f'<small style="color:#556677">{f.file} · {f.sheet} · Zeile {f.row}'
            f'{" · " + f.record_id if f.record_id else ""}</small><br>'
            f'{f.message}'
            f'</div>',
            unsafe_allow_html=True,
        )

# =============================================================================
#                              BEFUNDE
# =============================================================================
elif page == "Befunde":
    st.title("Befundliste")
    st.markdown(
        '<p class="subtitle">Jeder Befund mit Priorität, Herkunft, Begründung und Korrekturvorschlag.</p>',
        unsafe_allow_html=True,
    )

    df = findings_to_dataframe(findings)
    jump = st.session_state.jump_filter or {}
    with st.expander("Filter", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        prio_opts = ["Hoch", "Mittel", "Niedrig"]
        prio = f1.multiselect("Priorität", prio_opts, default=jump.get("Priorität") or prio_opts)
        system = f2.multiselect("System", sorted(df["System"].unique()) if len(df) else [],
                                default=jump.get("System") or [])
        dept = f3.multiselect("Verantwortlich", sorted(df["Verantwortlicher"].unique()) if len(df) else [],
                              default=jump.get("Verantwortlicher") or [])
        region = f4.multiselect("Region", sorted(df["Region"].unique()) if len(df) else [],
                                default=jump.get("Region") or [])
        f5, f6, f7 = st.columns(3)
        category = f5.multiselect("Fehlerkategorie", sorted(df["Fehlerkategorie"].unique()) if len(df) else [],
                                  default=jump.get("Fehlerkategorie") or [])
        severity = f6.multiselect("Schweregrad", ["hoch", "mittel", "niedrig"])
        search = f7.text_input("Textsuche")
    if jump:
        st.session_state.jump_filter = {}  # einmal verwendet

    view = df.copy()
    if prio:        view = view[view["Priorität"].isin(prio)]
    if system:      view = view[view["System"].isin(system)]
    if dept:        view = view[view["Verantwortlicher"].isin(dept)]
    if region:      view = view[view["Region"].isin(region)]
    if category:    view = view[view["Fehlerkategorie"].isin(category)]
    if severity:    view = view[view["Schweregrad"].isin(severity)]
    if search:
        s = search.lower()
        mask = view.astype(str).apply(lambda r: r.str.lower().str.contains(s).any(), axis=1)
        view = view[mask]

    unique_in_view = affected_record_count(
        [f for f in findings if f.finding_id in set(view["Befund-ID"])]
    ) if len(view) else 0
    st.caption(
        f"{len(view):,} von {len(df):,} Befunden sichtbar · ".replace(",", ".")
        + f"{unique_in_view:,} eindeutige Datensätze betroffen.".replace(",", ".")
    )

    compact_cols = ["Priorität", "Schweregrad", "System", "Datei", "Blatt", "Zeile",
                    "Feld", "Befund", "Verantwortlicher", "Region", "Befundgruppe"]
    st.dataframe(view[compact_cols], use_container_width=True, hide_index=True, height=380)

    st.markdown("### Detailansicht")
    if len(view) == 0:
        st.info("Keine Befunde für die aktuellen Filter.")
    else:
        choices = [
            f"[{row['Priorität']}] {row['Befund'][:90]}  —  {row['Datei']} / {row['Blatt']} Z{row['Zeile']}"
            for _, row in view.iterrows()
        ]
        choice_idx = st.selectbox("Befund auswählen", range(len(choices)),
                                  format_func=lambda i: choices[i])
        row = view.iloc[choice_idx]
        finding_obj = next((f for f in findings if f.finding_id == row["Befund-ID"]), None)

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown(f"#### {row['Regel']}")
            st.markdown(
                f"{_badge(row['Schweregrad'])}"
                f'<span class="badge badge-sys">Priorität {row["Priorität"]} · '
                f'{row["Prioritätsscore"]}</span>'
                f'<span class="badge badge-sys">{row["System"]}</span>'
                f'<span class="badge badge-sys">{row["Fehlerkategorie"]}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**Befund-ID:** `{row['Befund-ID']}`  ·  **Datensatz:** `{row['Betroffener Datensatz']}`")
            st.markdown("**Was ist das Problem?**")
            st.write(row["Befund"])
            st.markdown("**Warum ist das wichtig?**")
            st.write(row["Erklärung"] or "–")
            st.markdown("**Geschäftliche Auswirkung**")
            st.write(row["Geschäftliche Auswirkung"] or "–")
            st.markdown("**Ursache (mögliche)**")
            st.write(row["Ursache"] or "–")
            if row["Folgefehler"]:
                st.markdown("**Folgefehler**")
                for item in str(row["Folgefehler"]).split("; "):
                    st.write(f"- {item}")
            if finding_obj is not None:
                st.markdown("**Begründung der Priorität**")
                st.info(priority_reason(finding_obj, cfg))
        with c2:
            st.markdown("#### Herkunft")
            st.write(f"**Datei:** {row['Datei']}")
            st.write(f"**Blatt:** {row['Blatt']}")
            st.write(f"**Zeile:** {row['Zeile']}")
            st.write(f"**Feld:** {row['Feld']}")
            st.write(f"**Originalwert:** `{row['Originalwert']}`")
            st.write(f"**Region:** {row['Region'] or '–'}")
            st.divider()
            st.markdown("#### Korrektur")
            st.write(f"**Vorschlag:** {row['Korrekturvorschlag'] or '–'}")
            st.write(f"**Art:** {row['Korrekturart']}")
            st.write(f"**Konfidenz:** {row['Konfidenz']}")
            st.write(f"**Verantwortlich (Vorschlag):** {row['Verantwortlicher']}")
            cur_status = st.session_state.finding_status.get(
                row["Befund-ID"], row["Status"] or "Offen"
            )
            new_status = st.selectbox(
                "Status setzen",
                ["Offen", "In_Bearbeitung", "Bestaetigt", "Abgelehnt", "Behoben"],
                index=["Offen", "In_Bearbeitung", "Bestaetigt", "Abgelehnt", "Behoben"].index(cur_status)
                if cur_status in ["Offen", "In_Bearbeitung", "Bestaetigt", "Abgelehnt", "Behoben"] else 0,
                key=f"status_{row['Befund-ID']}",
            )
            st.session_state.finding_status[row["Befund-ID"]] = new_status

            if row["Befundgruppe"]:
                group = df[df["Befundgruppe"] == row["Befundgruppe"]]
                st.markdown(f"#### Zusammenhängende Befunde ({len(group)})")
                for _, g in group.iterrows():
                    st.caption(f"[{g['Priorität']}] {g['Befund'][:100]}")

    st.divider()
    ex1, ex2 = st.columns(2)
    if ex1.button("CSV exportieren", use_container_width=True):
        outp = ROOT / "data" / "exports" / "befunde.csv"
        export_csv(findings, outp)
        with open(outp, "rb") as fh:
            ex1.download_button("CSV herunterladen", fh.read(), file_name="befunde.csv",
                                mime="text/csv", use_container_width=True)
        ex1.success(f"Export: {outp}")
    if ex2.button("Excel exportieren", use_container_width=True):
        outp = ROOT / "data" / "exports" / "befunde.xlsx"
        export_xlsx(findings, outp)
        with open(outp, "rb") as fh:
            ex2.download_button("Excel herunterladen", fh.read(), file_name="befunde.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True)
        ex2.success(f"Export: {outp}")

# =============================================================================
#                              URSACHENANALYSE
# =============================================================================
elif page == "Ursachenanalyse":
    st.title("Ursachenanalyse")
    st.markdown(
        '<p class="subtitle">Wiederkehrende Muster und zusammenhängende Fehlergruppen - Hebel mit größter Wirkung.</p>',
        unsafe_allow_html=True,
    )
    st.info(
        "Diese Seite zeigt **statistische Auffälligkeiten** und **mögliche gemeinsame Ursachen**. "
        "Eine bestätigte Ursache braucht fachliche Prüfung - die Anwendung behauptet keine Schuld."
    )

    st.subheader("Fehlergruppen mit gemeinsamer Ursache")
    groups = cause_groups(findings)
    if not groups:
        st.info("Keine mehrfach betroffenen Datensätze gefunden.")
    for g in groups[:20]:
        with st.expander(
            f"🔗 Datensatz `{g.record_id or '(ohne ID)'}` - "
            f"{len(g.members)} zusammenhängende Befunde · Systeme: {', '.join(g.systems)} · "
            f"Max-Prio {g.max_priority_score:.0f}"
        ):
            st.markdown(f"**Primärer Befund:** {g.primary.rule_name} - {g.primary.message}")
            st.caption(g.primary.explanation or "")
            st.markdown("**Weitere zusammenhängende Befunde:**")
            for m in g.members[1:]:
                st.write(f"- [{m.priority_label} · {m.priority_score:.0f}] "
                         f"{m.system} / {m.sheet} Z{m.row} · {m.message}")

    st.markdown("---")
    st.subheader("Häufigste wiederkehrende Muster")
    st.markdown(
        '<p class="help-text">Pro Kombination (Fehlerkategorie · Feld). Deuten auf '
        'systematische Ursachen im Quellsystem hin.</p>',
        unsafe_allow_html=True,
    )
    patterns = recurring_patterns(findings)
    if not patterns:
        st.info("Keine wiederkehrenden Muster.")
    for p in patterns:
        st.markdown(
            f'<div class="rec-card">'
            f'<p class="title">{p.label} - {p.count} Befunde, {p.unique_records} eindeutige Datensätze</p>'
            f'<p class="detail"><em>Beispielregel:</em> {p.example_rule}<br>'
            f'<em>Mögliche Ursache:</em> {p.hint}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

# =============================================================================
#                              LÄNDER & REGIONEN
# =============================================================================
elif page == "Länder & Regionen":
    st.title("Qualität je Markt")
    st.markdown(
        '<p class="subtitle">Wo läuft es, wo klemmt es? Pro Region mit Drill-down.</p>',
        unsafe_allow_html=True,
    )

    rows = []
    for r in regions:
        rows.append({
            "Region": r.region,
            "Score": r.score if r.sufficient_data else None,
            "Hoch": r.findings_high,
            "Mittel": r.findings_medium,
            "Niedrig": r.findings_low,
            "Datensatzbasis": r.records_estimated,
            "Ausreichende Datenbasis": "Ja" if r.sufficient_data else "Nein",
        })
    rdf = pd.DataFrame(rows)

    plot_df = rdf.dropna(subset=["Score"]).sort_values("Score")
    if not plot_df.empty:
        fig = px.bar(plot_df, x="Score", y="Region", orientation="h",
                     range_x=[0, 110], color="Score",
                     color_continuous_scale=["#b31b2a", "#e8a33a", "#2b8a3e"],
                     text=plot_df["Score"].round(1))
        fig.update_layout(height=400, coloraxis_showscale=False, margin=dict(l=0, r=10, t=10, b=0))
        fig.update_traces(textposition="outside", cliponaxis=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Noch keine ausreichende Datenbasis pro Region.")

    st.subheader("Details je Region")
    st.dataframe(
        rdf, use_container_width=True, hide_index=True,
        column_config={"Score": st.column_config.NumberColumn("Score", format="%.1f")},
    )

    st.markdown("---")
    st.subheader("Region im Detail")
    region_pick = st.selectbox("Region auswählen", [r["Region"] for r in rows])
    region_findings = [f for f in findings if (f.region or "Nicht zugeordnet") == region_pick]
    st.caption(
        f"{len(region_findings)} Befunde · "
        f"{affected_record_count(region_findings)} eindeutige Datensätze · "
        f"{sum(1 for f in region_findings if f.severity == 'hoch')} hoch."
    )
    if region_findings:
        # Top-Fehler-Kategorien
        from collections import Counter
        cat = Counter(f.category for f in region_findings).most_common(5)
        field = Counter(f.field_name for f in region_findings).most_common(5)
        sys_cnt = Counter(f.system for f in region_findings).most_common()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Häufigste Fehlerkategorien**")
            for c, n in cat:
                st.write(f"- {c}: {n}")
        with c2:
            st.markdown("**Häufigste Felder**")
            for f_, n in field:
                st.write(f"- `{f_}`: {n}")
        with c3:
            st.markdown("**Betroffene Systeme**")
            for s, n in sys_cnt:
                st.write(f"- {s}: {n}")

        if st.button(f"→ Alle Befunde in {region_pick} in der Befundliste öffnen",
                     type="primary"):
            _go_to_befunde({"Region": [region_pick]})

        st.markdown("**Die 10 dringendsten Befunde dieser Region:**")
        for f in sorted(region_findings, key=lambda x: -x.priority_score)[:10]:
            st.markdown(
                f'<div class="finding-card">'
                f'<span class="badge badge-sys">{f.priority_label} · {f.priority_score:.0f}</span>'
                f'{_badge(f.severity)}'
                f'<span class="badge badge-sys">{f.system}</span>'
                f'<strong>{f.rule_name}</strong><br>'
                f'<small style="color:#556677">{f.sheet} · Zeile {f.row} · {f.record_id or ""}</small><br>'
                f'{f.message}'
                f'</div>',
                unsafe_allow_html=True,
            )

# =============================================================================
#                              FACHBEREICHE
# =============================================================================
elif page == "Fachbereiche":
    st.title("Fachbereiche")
    st.markdown(
        '<p class="subtitle">Wer sollte was zuerst anpacken?</p>',
        unsafe_allow_html=True,
    )
    st.info(
        "Verantwortlichkeiten sind **Vorschläge** auf Basis der Fehlerkategorie "
        "(siehe `config/governance.yaml`). Sie können im Einzelfall anders zugeordnet werden."
    )

    summaries = department_summary(findings)
    summary_df = pd.DataFrame([{
        "Fachbereich": s.department,
        "Hoch": s.high,
        "Mittel": s.medium,
        "Niedrig": s.low,
        "Befunde gesamt": s.total,
        "Eindeutige Datensätze": s.unique_records,
    } for s in summaries])
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    pick = st.selectbox("Fachbereich für Detailansicht",
                        [s.department for s in summaries])
    s = next(x for x in summaries if x.department == pick)
    dept_findings = [f for f in findings if (f.responsibility or "Unzugeordnet") == pick]

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Befunde gesamt", f"{s.total}")
    kpi(c2, "Hoch", f"{s.high}", "prio-h")
    kpi(c3, "Mittel", f"{s.medium}", "prio-m")
    kpi(c4, "Eindeutige Datensätze", f"{s.unique_records}")

    st.markdown("**Häufigste Fehlerkategorien dieses Fachbereichs:**")
    for c, n in s.top_categories:
        st.write(f"- {c}: {n}")

    st.markdown("**Top 10 dringendste Befunde:**")
    for f in sorted(dept_findings, key=lambda x: -x.priority_score)[:10]:
        st.markdown(
            f'<div class="finding-card">'
            f'<span class="badge badge-sys">{f.priority_label} · {f.priority_score:.0f}</span>'
            f'{_badge(f.severity)}'
            f'<span class="badge badge-sys">{f.system}</span>'
            f'<strong>{f.rule_name}</strong><br>'
            f'<small style="color:#556677">{f.sheet} · Zeile {f.row}</small><br>'
            f'{f.message}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if st.button(f"→ Alle Befunde für '{pick}' in der Befundliste öffnen", type="primary"):
        _go_to_befunde({"Verantwortlicher": [pick]})

    st.markdown("---")
    st.subheader("Fachbereichs-Export")
    if st.button("Befunde dieses Fachbereichs als Excel exportieren"):
        outp = ROOT / "data" / "exports" / f"befunde_{pick.replace('/', '_')}.xlsx"
        export_xlsx(dept_findings, outp)
        with open(outp, "rb") as fh:
            st.download_button("Excel herunterladen", fh.read(),
                               file_name=outp.name,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =============================================================================
#                              DATENQUELLEN
# =============================================================================
elif page == "Datenquellen":
    st.title("Datenquellen")
    st.markdown(
        '<p class="subtitle">Was wurde geladen und geprüft?</p>',
        unsafe_allow_html=True,
    )

    rows = []
    for key, sheet in pkg.sheets.items():
        fcount = sum(1 for f in findings if f.file == sheet.source_file and f.sheet == sheet.sheet_name)
        unique = affected_record_count(
            [f for f in findings if f.file == sheet.source_file and f.sheet == sheet.sheet_name]
        )
        status = "🟢 OK" if fcount == 0 else ("🔴 kritisch" if fcount > 50 else "🟡 Befunde")
        rows.append({
            "Status": status,
            "Schlüssel": key,
            "System": sheet.system,
            "Datei": sheet.source_file,
            "Blatt": sheet.sheet_name,
            "Zeilen": len(sheet.df),
            "Spalten": len(sheet.df.columns),
            "Befunde": fcount,
            "Betroffene Datensätze": unique,
        })
    sdf = pd.DataFrame(rows).sort_values(["System", "Blatt"])
    st.dataframe(sdf, use_container_width=True, hide_index=True)

    pick = st.selectbox("Rohdaten eines Blatts anschauen", list(pkg.sheets.keys()))
    if pick:
        sheet = pkg[pick]
        st.caption(f"{sheet.source_file} / {sheet.sheet_name} - erste 50 Zeilen")
        st.dataframe(sheet.df.head(50), use_container_width=True)

# =============================================================================
#                              KORREKTURVORSCHLÄGE
# =============================================================================
elif page == "Korrekturvorschläge":
    st.title("Korrekturvorschläge")
    st.markdown(
        '<p class="subtitle">Was kann sofort korrigiert werden, was braucht fachliche Prüfung?</p>',
        unsafe_allow_html=True,
    )
    st.info(
        "**A** = Sichere Korrektur (z. B. Normierung von 'Aktiv' → 'ACTIVE'). "
        "**B** = Vorschlag mit Bestätigung (z. B. mögliche Dublette). "
        "**C** = Manuelle Prüfung erforderlich. "
        "Das Tool verändert NIE die Originaldaten - Korrekturen fließen in einen separaten Export."
    )

    df = findings_to_dataframe(findings)
    cat_map = {
        "Sichere_Korrektur": "A - Sichere Korrektur",
        "Vorschlag":          "B - Vorschlag (bestätigen)",
        "Manuelle_Pruefung":  "C - Manuelle Prüfung",
    }
    counts = {cat_map[k]: int((df["Korrekturart"] == k).sum()) for k in cat_map}
    c1, c2, c3 = st.columns(3)
    kpi(c1, "A - Sichere Korrektur",      f"{counts['A - Sichere Korrektur']}", "prio-l")
    kpi(c2, "B - Vorschlag (bestätigen)", f"{counts['B - Vorschlag (bestätigen)']}", "prio-m")
    kpi(c3, "C - Manuelle Prüfung",       f"{counts['C - Manuelle Prüfung']}", "prio-h")

    tabs = st.tabs(list(cat_map.values()))
    for tab, art in zip(tabs, cat_map.keys()):
        with tab:
            sub = df[df["Korrekturart"] == art].copy()
            st.caption(f"{len(sub)} Befunde in dieser Gruppe.")
            if len(sub) == 0:
                continue
            # Multi-Select für "als behoben markieren" (Simulation)
            st.markdown(
                "**Zur Vorher/Nachher-Simulation markieren** - verändert keine Originaldaten, "
                "nur die Vorher/Nachher-Ansicht."
            )
            visible_ids = sub["Befund-ID"].tolist()
            current = st.session_state.resolved_ids
            to_resolve = st.multiselect(
                "Diese Befunde als 'behoben' annehmen",
                visible_ids,
                default=[i for i in visible_ids if i in current],
                key=f"resolve_{art}",
                format_func=lambda i: next((f["Befund"][:80] for _, f in sub.iterrows() if f["Befund-ID"] == i), i),
            )
            # Union aktualisieren
            st.session_state.resolved_ids = (current - set(visible_ids)) | set(to_resolve)
            st.dataframe(
                sub[["Priorität", "System", "Datei", "Blatt", "Zeile", "Feld",
                     "Originalwert", "Korrekturvorschlag", "Verantwortlicher", "Konfidenz"]],
                use_container_width=True, hide_index=True,
            )

    st.divider()
    st.subheader("Korrektur-Export (Arbeitskopie)")
    st.caption(
        "Eine Liste aller Korrekturvorschläge für Fachbereiche - Originaldaten bleiben unangetastet."
    )
    if st.button("Korrekturliste als Excel exportieren", type="primary"):
        suggestions = [f for f in findings if f.correction_suggestion]
        outp = ROOT / "data" / "exports" / "korrekturvorschlaege.xlsx"
        export_xlsx(suggestions, outp)
        with open(outp, "rb") as fh:
            st.download_button("Excel herunterladen", fh.read(),
                               file_name="korrekturvorschlaege.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =============================================================================
#                              VORHER / NACHHER
# =============================================================================
elif page == "Vorher / Nachher":
    st.title("Vorher / Nachher - Simulation")
    st.markdown(
        '<p class="subtitle">Was würde sich ändern, wenn die markierten Befunde behoben wären?</p>',
        unsafe_allow_html=True,
    )
    st.info(
        "Diese Simulation **verändert keine Originaldaten**. "
        "Ein Verbesserungswert wird nur ausgewiesen, wenn Sie Befunde zum 'Behoben'-Status markiert haben "
        "(auf der Seite **Korrekturvorschläge**)."
    )

    resolved_ids = st.session_state.resolved_ids
    after = simulate_resolution(findings, resolved_ids)
    after_overall = overall_score(after, pkg, cfg)

    c1, c2, c3 = st.columns(3)
    kpi(c1, "Vorher: Gesamt-Score", f"{overall.score}")
    kpi(c2, "Nachher: Gesamt-Score", f"{after_overall.score}",
        "prio-l" if after_overall.score > overall.score else "")
    diff = after_overall.score - overall.score
    kpi(c3, "Verbesserung", f"{diff:+.1f}", "prio-l" if diff > 0 else "")

    st.markdown(" ")
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Vorher: Befunde Hoch", f"{overall.findings_high}", "prio-h")
    kpi(c2, "Nachher: Befunde Hoch", f"{after_overall.findings_high}", "prio-h")
    kpi(c3, "Davon simuliert behoben",
        f"{len([f for f in findings if f.severity == 'hoch' and f.finding_id in resolved_ids])}")

    st.markdown(" ")
    st.subheader("Score pro Dimension - Vorher vs. Nachher")
    df_dim = pd.DataFrame({
        "Dimension": list(overall.by_dimension.keys()),
        "Vorher":    [overall.by_dimension[d] for d in overall.by_dimension],
        "Nachher":   [after_overall.by_dimension.get(d, 100.0) for d in overall.by_dimension],
    })
    long = df_dim.melt(id_vars="Dimension", var_name="Zustand", value_name="Score")
    fig = px.bar(long, x="Score", y="Dimension", color="Zustand", barmode="group",
                 range_x=[0, 110],
                 color_discrete_map={"Vorher": "#b56c00", "Nachher": "#1f6a2e"})
    fig.update_layout(height=320, margin=dict(l=0, r=10, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.caption(
        "Hinweis: 'Nachher' zeigt den Score, **als ob** die markierten Befunde behoben wären. "
        "Ein tatsächliches 'behoben' kann die Anwendung nicht bestätigen, solange die Quelldaten "
        "nicht erneut analysiert wurden."
    )
    st.markdown(f"**{len(resolved_ids)} Befunde** sind aktuell als simuliert-behoben markiert.")
    if resolved_ids:
        if st.button("Alle Simulations-Markierungen zurücksetzen"):
            st.session_state.resolved_ids = set()
            st.rerun()

# =============================================================================
#                              REGELN
# =============================================================================
elif page == "Regeln":
    rules_view.render(ctx)

# =============================================================================
#                              VERLAUF
# =============================================================================
elif page == "Verlauf":
    st.title("Analyse-Historie")
    st.markdown(
        '<p class="subtitle">Nachvollziehbare Entwicklung der Datenqualität.</p>',
        unsafe_allow_html=True,
    )
    hist = _history()

    col_save, _ = st.columns([1, 3])
    with col_save:
        notes = st.text_input("Notiz für diesen Lauf (optional)")
        if st.button("Aktuellen Lauf speichern", type="primary"):
            run_id = hist.save_run(
                findings=findings,
                total_records=overall.total_records,
                rule_count=result.rule_count,
                overall_score=overall.score,
                notes=notes,
            )
            st.success(f"Lauf #{run_id} gespeichert.")

    runs = hist.list_runs()
    if not runs:
        st.info("Noch keine Läufe gespeichert.")
    else:
        rdf = pd.DataFrame([{
            "Run-ID": r.run_id,
            "Zeitpunkt": r.run_time,
            "Score": r.overall_score,
            "Hoch": r.findings_high,
            "Mittel": r.findings_medium,
            "Niedrig": r.findings_low,
            "Datensätze": r.total_records,
            "Regeln": r.rule_count,
            "Notiz": r.notes or "",
        } for r in runs])
        st.dataframe(rdf, use_container_width=True, hide_index=True)

        if len(runs) >= 2:
            st.subheader("Vergleich zweier Läufe")
            ids = [r.run_id for r in runs]
            c1, c2 = st.columns(2)
            old = c1.selectbox("Alter Lauf", ids, index=min(1, len(ids)-1))
            new = c2.selectbox("Neuer Lauf", ids, index=0)
            diff = hist.diff(old, new)
            c3, c4, c5 = st.columns(3)
            kpi(c3, "Neu hinzugekommen", f"{len(diff['new'])}", "prio-h")
            kpi(c4, "Noch offen", f"{len(diff['still_open'])}", "prio-m")
            kpi(c5, "Nicht mehr gefunden", f"{len(diff['resolved_or_unseen'])}", "prio-l")
            st.caption(
                "'Nicht mehr gefunden' ≠ 'Behoben'. Es kann auch bedeuten, dass sich die "
                "Datenstruktur geändert hat."
            )

# =============================================================================
#                              EINSTELLUNGEN
# =============================================================================
elif page == "Einstellungen":
    st.title("Governance & Gewichtung")
    st.markdown(
        '<p class="subtitle">Alle Parameter transparent - konfigurierbar in `config/`.</p>',
        unsafe_allow_html=True,
    )

    st.subheader("Führende Systeme (Governance)")
    ls = cfg.leading_systems
    ls_df = pd.DataFrame([{"Datenbereich": k, "Führendes System": v} for k, v in ls.items()])
    st.dataframe(ls_df, use_container_width=True, hide_index=True)
    st.caption(
        "Einträge mit 'Governance_Entscheidung_erforderlich' sind Vorschläge und benötigen "
        "eine fachliche Festlegung durch das Data-Governance-Team."
    )

    st.subheader("Priority-Gewichtung")
    st.json(cfg.priority_weights)

    st.subheader("Quality-Score Gewichtung")
    st.json(cfg.quality_score_cfg)

    st.subheader("Business-Impact je Kategorie")
    bi_df = pd.DataFrame([{"Kategorie": k, "Impact (0-10)": v}
                          for k, v in cfg.business_impact.items()])
    st.dataframe(bi_df, use_container_width=True, hide_index=True)

    st.subheader("Verantwortlichkeiten")
    rp_df = pd.DataFrame([{"Kategorie": k, "Vorgeschlagener Fachbereich": v}
                          for k, v in cfg.responsibilities.items()])
    st.dataframe(rp_df, use_container_width=True, hide_index=True)

# =============================================================================
#                              DEMO-ABLAUF
# =============================================================================
elif page == "Demo-Ablauf":
    st.title("Demo-Ablauf (für die Jury)")
    st.markdown(
        '<p class="subtitle">Ein geführter 8-Schritte-Durchlauf für die Präsentation.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="demo-banner">Diese Seite zeigt den empfohlenen Ablauf. Alle Zahlen stammen '
        'aus den tatsächlichen Excel-Dateien - keine Mock-Daten.</div>',
        unsafe_allow_html=True,
    )

    steps = [
        ("Schritt 1 - Startseite", "Übersicht",
         f"Zeigen: Gesamt-Score {overall.score}, {affected_count:,} eindeutig betroffene Datensätze, "
         f"{overall.findings_high} hochpriorisierte Befunde. "
         "Auf 'Was sollte als Nächstes erledigt werden?' zeigen."
         .replace(",", ".")),
        ("Schritt 2 - Preis-Konflikte öffnen", "Befunde",
         "Per Klick aus Handlungsempfehlung: Filter 'Konsistenz_Preis'. "
         "Erster Befund: Preis-Differenz HubSpot ↔ Salesforce, Differenz bis 629 000 %."),
        ("Schritt 3 - Priorität begründen", "Befunde",
         "In der Detailansicht: 'Begründung der Priorität' zeigt den nachvollziehbaren Grund - "
         "nicht Blackbox."),
        ("Schritt 4 - Ursachenanalyse", "Ursachenanalyse",
         "Fehlergruppen pro Datensatz zeigen Ursache + Folgen zusammen - keine doppelten Listen."),
        ("Schritt 5 - Markt-Drilldown", "Länder & Regionen",
         "Benelux als schwächster Markt, Klick zeigt Fehlerkategorien und die 10 dringendsten Befunde."),
        ("Schritt 6 - Fachbereichs-Ansicht", "Fachbereiche",
         "Vertrieb und Service bekommen jeweils eine eigene Übersicht inkl. Export."),
        ("Schritt 7 - Vorher/Nachher", "Vorher / Nachher",
         "Korrekturvorschläge als 'behoben' markieren (Seite Korrekturvorschläge) → Score-Verbesserung simulieren."),
        ("Schritt 8 - Export", "Befunde",
         "Jury-konforme CSV/Excel mit Pflichtspalten Datei/Blatt/Zeile/Feld/Befund/Schweregrad."),
    ]
    for title, target, desc in steps:
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f'<div class="demo-step"><strong>{title}</strong><br>{desc}</div>',
                        unsafe_allow_html=True)
        with c2:
            if st.button("→ Öffnen", key=f"demo_{title}", use_container_width=True):
                st.session_state.nav_target = target
                st.rerun()

    st.markdown("---")
    st.markdown(
        "**Zeitbudget für den Pitch (10 Min inkl. 2 Min Q&A):**\n\n"
        "- 2 Min Problem in Zahlen (Schritte 1-2)\n"
        "- 4 Min Live-Demo (Schritte 3-7)\n"
        "- 2 Min Nutzen + Alltagstauglichkeit (Fachbereiche, Export)\n"
        "- 2 Min Q&A"
    )
