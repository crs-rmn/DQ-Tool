"""Regelbasierter Data-Quality-Assistent (ohne KI-Dienst, ohne API-Kosten).

Der Assistent erkennt vorbereitete Fragearten und antwortet **ausschließlich** aus
den geladenen Daten, den Regeln und den Befunden. Er ändert nie Daten.

Plausibilitätsstufen:
- ``im üblichen Bereich``
- ``auffällig``            ungewöhnlich im Vergleich, aber nicht widerlegt
- ``unplausibel``          widerspricht Daten oder bekannten Mustern (z. B. Faktor 10/100)
- ``nachweislich falsch``  verletzt eine harte Regel (Preis ≤ 0, keine Zahl)
Reicht die Information nicht, steht dort: *fachliche Prüfung erforderlich*.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from .config import Config
from .finding import Finding
from .loader import DataPackage
from .normalize import is_missing, norm_currency, norm_matnr, norm_price, strip_str

HELP = (
    "Ich beantworte Fragen aus euren geladenen Daten, den Regeln und den Befunden. Beispiele:\n\n"
    "- *Warum ist 1000000020 kritisch?*\n"
    "- *Welche Regel verletzt die Materialnummer 1000000002?*\n"
    "- *Ist ein Produktpreis von 1.000.000 € plausibel?*\n"
    "- *Welche Produkte haben ungewöhnlich hohe Preise?*\n"
    "- *Welche Fehler betreffen Salesforce?* (auch SAP / HubSpot)\n"
    "- *Welche Regeln sind aktiv?*\n"
    "- *Wie ist der Score in DACH?* / *Was sind die kritischsten Befunde?*"
)


@dataclass
class ChatAnswer:
    text: str
    evidence: list[dict[str, Any]] = field(default_factory=list)   # belegende Befunde
    filters: dict[str, list[str]] | None = None                    # Sprung in die Befundliste
    kind: str = "info"


def _fmt_eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def parse_amount(text: str) -> float | None:
    t = text.lower().replace("€", " eur ")
    m = re.search(r"(-?)\s*(\d[\d\.\,\s]*\d|\d)\s*(mio|millionen|million|mrd|k|tsd)?", t)
    if not m:
        return None
    neg, raw, mult = m.group(1) == "-", m.group(2).replace(" ", ""), m.group(3)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):      # 1.000.000 / 47.290 = Tausenderpunkte
        raw = raw.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", raw):      # 1,000,000
        raw = raw.replace(",", "")
    v = norm_price(raw)
    if v is None:
        return None
    if mult in ("mio", "million", "millionen"):
        v *= 1_000_000
    elif mult in ("k", "tsd"):
        v *= 1_000
    elif mult == "mrd":
        v *= 1_000_000_000
    return -v if neg else v


def _ev(f: Finding) -> dict[str, Any]:
    return {
        "Befund-ID": f.finding_id, "Priorität": f"{f.priority_label} ({f.priority_score:.0f})",
        "Schweregrad": f.severity, "Regel": f.rule_name, "System": f.system,
        "Blatt": f.sheet, "Zeile": f.row, "Feld": f.field_name, "Befund": f.message,
    }


class DQAssistant:
    def __init__(self, pkg: DataPackage, findings: list[Finding], cfg: Config,
                 rules_info: list[dict[str, Any]], overall=None, regions=None):
        self.pkg, self.findings, self.cfg = pkg, findings, cfg
        self.rules_info = rules_info          # [{id,name,category,dimension,severity,enabled,source}]
        self.overall, self.regions = overall, regions
        self._by_record: dict[str, list[Finding]] = {}
        for f in findings:
            if f.record_id:
                self._by_record.setdefault(f.record_id, []).append(f)
        self._prices = self._collect_prices()

    # ------------------------------------------------------------- Daten --
    def _collect_prices(self) -> list[dict[str, Any]]:
        out = []
        hs, sf, pbe = self.pkg.get("HS_Products"), self.pkg.get("SF_Product2"), self.pkg.get("SF_PricebookEntry")
        if hs is not None:
            for _, r in hs.df.iterrows():
                p, m = norm_price(r.get("price")), norm_matnr(r.get("atn_sap_materialnummer"))
                if p and p > 0:
                    out.append({"price": p, "matnr": m, "name": strip_str(r.get("name")), "src": "HubSpot"})
        if sf is not None and pbe is not None:
            pid = {strip_str(r.get("Id")): (norm_matnr(r.get("ATN_SAP_Materialnummer__c")), strip_str(r.get("Name")))
                   for _, r in sf.df.iterrows()}
            for _, r in pbe.df.iterrows():
                p = norm_price(r.get("UnitPrice"))
                m, n = pid.get(strip_str(r.get("Product2Id")), (None, None))
                if p and p > 0 and norm_currency(r.get("CurrencyIsoCode")) == "EUR":
                    out.append({"price": p, "matnr": m, "name": n, "src": "Salesforce"})
        return out

    def _matkl(self) -> dict[str, str]:
        m = {}
        fert = self.pkg.get("SAP_FERT")
        if fert is not None:
            for _, r in fert.df.iterrows():
                k = norm_matnr(r.get("MATNR"))
                if k:
                    m[k] = strip_str(r.get("MATKL")) or ""
        return m

    def _names(self) -> dict[str, str]:
        out = {}
        fert = self.pkg.get("SAP_FERT")
        if fert is not None:
            for _, r in fert.df.iterrows():
                k = norm_matnr(r.get("MATNR"))
                if k:
                    out[k] = strip_str(r.get("MAKTX")) or ""
        return out

    # -------------------------------------------------------------- Router --
    def answer(self, question: str) -> ChatAnswer:
        q = question.strip()
        low = q.lower()
        if not q:
            return ChatAnswer(HELP)
        ids = self._extract_ids(q)
        if ("plausib" in low or "realistisch" in low or "stimmt" in low) and (parse_amount(q) is not None) \
                and ("preis" in low or "€" in q or "eur" in low):
            return self.price_plausibility(q, ids)
        if re.search(r"(ungewöhnlich|ungewoehnlich|auffällig|auffaellig|sehr|extrem)?\s*hoh\w*\s+preis|teuerst|preisausrei", low):
            return self.high_prices()
        if ids and ("warum" in low or "kritisch" in low or "regel" in low or "verletz" in low or "befund" in low
                    or "problem" in low or "fehler" in low):
            return self.explain_entity(ids, why=("warum" in low or "kritisch" in low))
        if "regel" in low and any(w in low for w in ("aktiv", "welche", "wie viele", "liste", "gibt es")) \
                and not ids and not any(s in low for s in ("salesforce", "hubspot", "sap")):
            return self.rules_overview()
        sysname = self._system_in(low)
        if sysname and any(w in low for w in ("fehler", "befund", "problem", "betreff", "kritisch")):
            return self.system_findings(sysname)
        if "score" in low or "qualität" in low or "qualitaet" in low:
            return self.score_answer(low)
        if "kritisch" in low or "dringend" in low or "wichtig" in low or "schlimm" in low:
            return self.top_critical()
        if ids:
            return self.explain_entity(ids, why=False)
        # Produktname/-code ohne ID
        cands = self._match_product_text(q)
        if cands:
            return self.explain_entity(cands, why=("warum" in low or "kritisch" in low))
        return ChatAnswer("Diese Frage kann ich mit den vorhandenen Daten und Regeln nicht sicher beantworten, "
                          "ohne etwas zu erfinden.\n\n" + HELP, kind="unbekannt")

    # ----------------------------------------------------------- Helfer --
    @staticmethod
    def _system_in(low: str) -> str | None:
        for key, name in (("salesforce", "Salesforce"), ("hubspot", "HubSpot"), ("sap", "SAP")):
            if re.search(rf"\b{key}\b", low):
                return name
        return None

    def _extract_ids(self, q: str) -> list[str]:
        ids = re.findall(r"\b\d{10}\b", q)
        ids += re.findall(r"\b(?:001|003|02i|0WO|01t|01u|01s)[A-Za-z0-9]{12,15}\b", q)
        ids += [x.upper() for x in re.findall(r"\bWO-\d{6}\b", q, flags=re.I)]
        ids += re.findall(r"\b\d{11}\b", q)
        ids += [x.upper() for x in re.findall(r"\bATN-\d{6}\b", q, flags=re.I)]
        return list(dict.fromkeys(ids))

    def _match_product_text(self, q: str) -> list[str]:
        toks = re.findall(r"\b[A-Za-z]{2,4}-\d{3}\b", q)
        if not toks:
            return []
        names = self._names()
        out = [m for m, n in names.items() if any(t.lower() in n.lower() for t in toks)]
        return out[:5]

    # ------------------------------------------------------ Antworten --
    def explain_entity(self, ids: list[str], why: bool) -> ChatAnswer:
        parts, ev, found_any = [], [], False
        names = self._names()
        for i in ids[:3]:
            fs = list(self._by_record.get(i, []))
            if i.upper().startswith("ATN-"):   # SKU -> MATNR
                fs += [f for f in self.findings if str(f.value or "").upper() == i.upper()]
            label = names.get(i, "")
            if not fs:
                known = self._exists(i)
                parts.append(f"**{i}** {('· ' + label) if label else ''}: " +
                             ("Keine Befunde in den aktuellen Regeln. Das heißt nicht, dass alles korrekt ist, "
                              "nur dass keine aktive Regel anschlägt." if known else
                              "Diese Kennung kommt in den geladenen Daten nicht vor."))
                continue
            found_any = True
            fs.sort(key=lambda f: -f.priority_score)
            sev = Counter(f.severity for f in fs)
            systems = sorted({f.system for f in fs})
            head = (f"**{i}** {('· ' + label) if label else ''} hat **{len(fs)} Befund(e)** "
                    f"({sev.get('hoch', 0)} hoch, {sev.get('mittel', 0)} mittel, {sev.get('niedrig', 0)} niedrig) "
                    f"in {', '.join(systems)}.")
            parts.append(head)
            if why:
                top = fs[:3]
                parts.append("**Warum kritisch?** Die Priorität setzt sich aus Schweregrad, geschäftlicher "
                             "Auswirkung, Anteil betroffener Datensätze und Folgefehlern zusammen (siehe weights.yaml). "
                             "Die wichtigsten Gründe:")
                for f in top:
                    parts.append(f"- *{f.rule_name}* ({f.priority_label}, {f.priority_score:.0f}): {f.message}"
                                 + (f" → {f.business_impact}" if f.business_impact else ""))
            else:
                parts.append("**Verletzte Regeln:**")
                for rid, grp in _group(fs).items():
                    parts.append(f"- `{rid}` {grp[0].rule_name}: {len(grp)}×, z. B. {grp[0].message}")
            ev += [_ev(f) for f in fs[:15]]
        text = "\n\n".join(parts)
        if found_any:
            text += "\n\n*Quelle: Befundliste dieses Laufs. Ob ein Wert fachlich falsch ist, entscheidet der Fachbereich.*"
        return ChatAnswer(text, ev, kind="entity")

    def _exists(self, ident: str) -> bool:
        for s in self.pkg.sheets.values():
            for col in s.df.columns:
                if col in ("Id", "MATNR", "hs_object_id", "WorkOrderNumber", "ATN_SAP_Materialnummer__c",
                           "atn_sap_materialnummer", "hs_sku", "StockKeepingUnit"):
                    if (s.df[col].map(lambda v: strip_str(v) or "").map(
                            lambda v: v[:-2] if v.endswith(".0") else v) == ident).any():
                        return True
        return False

    def price_plausibility(self, q: str, ids: list[str]) -> ChatAnswer:
        amount = parse_amount(q)
        prices = sorted(p["price"] for p in self._prices)
        if amount is None or not prices:
            return ChatAnswer("Dafür fehlen Betrag oder Vergleichspreise. Fachliche Prüfung erforderlich.")
        n = len(prices)
        pct = lambda x: prices[min(n - 1, max(0, int(round(x * (n - 1)))))]  # noqa: E731
        p5, p50, p95, mx = pct(.05), median(prices), pct(.95), prices[-1]
        higher = sum(1 for p in prices if p > amount)
        lines = [f"**Betrag:** {_fmt_eur(amount)}",
                 f"**Vergleichsbasis:** {n} Preise aus HubSpot und Salesforce (Median {_fmt_eur(p50)}, "
                 f"90 %-Bereich {_fmt_eur(p5)} – {_fmt_eur(p95)}, Maximum {_fmt_eur(mx)})."]
        level, reasons = "im üblichen Bereich", []
        if amount <= 0:
            level = "nachweislich falsch"
            reasons.append("Ein Preis ≤ 0 verletzt die Preisregel (Preis muss > 0 sein).")
        else:
            if amount > p95:
                level = "auffällig"
                reasons.append(f"Er liegt über dem 95. Perzentil; {higher} von {n} bekannten Preisen sind höher.")
            if amount > mx:
                reasons.append(f"Er liegt über dem höchsten bekannten Preis ({_fmt_eur(mx)}) um Faktor {amount / mx:.1f}.")
            if amount < p5:
                level = "auffällig"
                reasons.append("Er liegt unter dem 5. Perzentil der bekannten Preise.")
            # Produktbezug
            prod_ids = [i for i in ids if len(i) == 10] or self._match_product_text(q)
            if prod_ids:
                pm = prod_ids[0]
                same = [p["price"] for p in self._prices if p["matnr"] == pm]
                nm = self._names().get(pm, pm)
                if same:
                    ref = median(same)
                    ratio = amount / ref
                    lines.append(f"**Produkt {pm} ({nm}):** bekannte Preise {', '.join(_fmt_eur(x) for x in sorted(set(same)))}.")
                    if any(abs(ratio - k) / k < 0.02 or abs(1 / ratio - k) / k < 0.02 for k in (10, 100, 1000)):
                        level = "unplausibel"
                        reasons.append(f"Der Betrag ist genau das {ratio:g}-Fache des bekannten Preises - typisch für "
                                       "einen Dezimal-/Einheitenfehler.")
                    elif ratio > 3 or ratio < 1 / 3:
                        level = "unplausibel" if level != "nachweislich falsch" else level
                        reasons.append(f"Er weicht um Faktor {max(ratio, 1 / ratio):.1f} vom bekannten Preis dieses Produkts ab.")
                    else:
                        level = "im üblichen Bereich" if level == "im üblichen Bereich" else level
                        reasons.append(f"Er liegt im Rahmen des bekannten Preises ({ratio:.2f}×).")
        lines.append(f"\n**Einstufung: {level}**")
        lines += [f"- {r}" for r in reasons] or ["- Der Betrag liegt im Bereich der bekannten Preise."]
        if level in ("auffällig", "unplausibel"):
            lines.append("\n**Nicht entscheidbar aus den Daten:** Ein ungewöhnlicher Preis kann bei Sonderausführungen, "
                         "Maschinenpaketen oder Mengenpreisen korrekt sein. **Fachliche Prüfung erforderlich** "
                         "(Produkt, Menge/Einheit, Angebotsunterlage). Als *falsch* gilt ein Wert hier erst, "
                         "wenn er eine harte Regel verletzt oder einem belegten Wert widerspricht.")
        elif level == "im üblichen Bereich":
            lines.append("\nDas ist keine Bestätigung der Richtigkeit, nur ein Vergleich mit den vorhandenen Preisen.")
        return ChatAnswer("\n\n".join(lines), kind="plausibilitaet")

    def high_prices(self) -> ChatAnswer:
        matkl, names = self._matkl(), self._names()
        by_group: dict[str, list[float]] = {}
        for p in self._prices:
            if p["matnr"]:
                by_group.setdefault(matkl.get(p["matnr"], "?"), []).append(p["price"])
        rows = []
        for p in self._prices:
            if not p["matnr"]:
                continue
            g = matkl.get(p["matnr"], "?")
            grp = by_group.get(g, [])
            if len(grp) >= 8:
                base, scope = median(grp), f"Warengruppe {g}"
            else:
                allp = [x["price"] for x in self._prices]
                base, scope = median(allp), "alle Produkte"
            if base > 0 and p["price"] / base >= 3:
                rows.append({"MATNR": p["matnr"], "Produkt": names.get(p["matnr"], p["name"] or ""),
                             "Quelle": p["src"], "Preis (EUR)": p["price"], "Vergleich": scope,
                             "Median Vergleich (EUR)": round(base), "Faktor": round(p["price"] / base, 1)})
        rows.sort(key=lambda r: -r["Faktor"])
        if not rows:
            return ChatAnswer("Keine Preise liegen mehr als 3× über dem Median ihrer Vergleichsgruppe.")
        text = (f"**{len(rows)} Preiseinträge** liegen mindestens 3× über dem Median ihrer Warengruppe "
                "(bzw. aller Produkte, wenn die Gruppe zu klein ist). Das sind **auffällige** Werte, "
                "keine bewiesenen Fehler: Produkte unterscheiden sich stark im Preis. Fachliche Prüfung erforderlich.")
        return ChatAnswer(text, rows[:25], kind="hohe_preise")

    def system_findings(self, system: str) -> ChatAnswer:
        fs = [f for f in self.findings if f.system == system]
        if not fs:
            return ChatAnswer(f"Für {system} liegen in diesem Lauf keine Befunde vor.")
        sev = Counter(f.severity for f in fs)
        top_rules = Counter((f.rule_id, f.rule_name) for f in fs).most_common(5)
        lines = [f"**{system}: {len(fs)} Befunde** ({sev.get('hoch', 0)} hoch, {sev.get('mittel', 0)} mittel, "
                 f"{sev.get('niedrig', 0)} niedrig).", "", "Häufigste Regeln:"]
        lines += [f"- {n} (`{rid}`): {c}×" for (rid, n), c in top_rules]
        return ChatAnswer("\n".join(lines), [_ev(f) for f in sorted(fs, key=lambda f: -f.priority_score)[:15]],
                          filters={"System": [system]}, kind="system")

    def rules_overview(self) -> ChatAnswer:
        act = [r for r in self.rules_info if r["enabled"]]
        cust = [r for r in act if r["source"] == "Benutzer"]
        cnt = Counter(f.rule_id for f in self.findings)
        lines = [f"**{len(act)} aktive Regeln** von {len(self.rules_info)} (davon {len(cust)} Benutzerregeln)."]
        for r in sorted(act, key=lambda r: -cnt.get(r["id"], 0))[:10]:
            lines.append(f"- `{r['id']}` {r['name']} - {cnt.get(r['id'], 0)} Befunde")
        lines.append("\nDie vollständige Liste mit Prüfumfang steht auf der Seite *Regeln*.")
        return ChatAnswer("\n".join(lines))

    def score_answer(self, low: str) -> ChatAnswer:
        if self.regions:
            for r in self.regions:
                if r.region.lower() in low:
                    if not r.sufficient_data:
                        return ChatAnswer(f"Für {r.region} gibt es zu wenig Datensätze ({r.records_estimated}) für einen belastbaren Score.")
                    return ChatAnswer(f"**{r.region}: Score {r.score}** bei ca. {r.records_estimated} Datensätzen "
                                      f"({r.findings_high} hoch, {r.findings_medium} mittel, {r.findings_low} niedrig).")
        if self.overall is not None:
            valid = sorted([r for r in (self.regions or []) if r.sufficient_data], key=lambda r: r.score)
            txt = f"**Gesamt-Score: {self.overall.score}** bei {self.overall.total_records:,} Datensätzen.".replace(",", ".")
            if valid:
                txt += f" Niedrigster Regionsscore: **{valid[0].region} ({valid[0].score})**."
            return ChatAnswer(txt)
        return ChatAnswer("Kein Score verfügbar.")

    def top_critical(self) -> ChatAnswer:
        top = sorted(self.findings, key=lambda f: -f.priority_score)[:5]
        lines = ["**Die 5 kritischsten Befunde nach Prioritätsscore:**"]
        for f in top:
            lines.append(f"- [{f.priority_score:.0f}] {f.system}/{f.sheet} Z{f.row} · {f.rule_name}: {f.message}")
        return ChatAnswer("\n".join(lines), [_ev(f) for f in top], kind="top")


def _group(fs: list[Finding]) -> dict[str, list[Finding]]:
    out: dict[str, list[Finding]] = {}
    for f in fs:
        out.setdefault(f.rule_id, []).append(f)
    return out
