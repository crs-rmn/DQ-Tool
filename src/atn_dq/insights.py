"""Zusätzliche Auswertungen für die Benutzeroberfläche.

- Eindeutig betroffene Datensätze (nicht gleich Anzahl Befunde)
- Handlungsempfehlungen für die Startseite
- Menschlich lesbare Begründung pro Priorität
- Fehlergruppen (Ursache -> Folgen) für die Ursachenanalyse
- Fachbereichs-Zusammenfassung
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .config import Config
from .finding import Finding


# ------------------------------------------------- Betroffene Datensätze --
def unique_affected_records(findings: Iterable[Finding]) -> set[tuple[str, str, str]]:
    """Menge eindeutig betroffener Datensätze (System, Datei, Record-ID).

    Wenn kein ``record_id`` existiert, nutzen wir (Datei, Blatt, Zeile) als
    Ersatzschlüssel, damit mehrere Befunde auf derselben Zeile nur einmal
    zählen.
    """
    seen: set[tuple[str, str, str]] = set()
    for f in findings:
        if f.record_id:
            seen.add((f.system, f.file, f.record_id))
        else:
            seen.add((f.system, f.file, f"{f.sheet}#{f.row}"))
    return seen


def affected_record_count(findings: Iterable[Finding]) -> int:
    return len(unique_affected_records(findings))


# ------------------------------------------------- Priority-Begründung --
PRIORITY_REASONS = {
    "Konsistenz_Preis": (
        "Preise sind geschäftskritisch: Unterschiedliche Werte zwischen Systemen "
        "führen direkt zu falschen Angeboten und Vertrauensverlust bei Kunden."
    ),
    "Konsistenz_Produkt": (
        "Produktinformationen müssen systemübergreifend konsistent sein, "
        "sonst arbeiten Vertrieb, Marketing und Service mit unterschiedlichen Fakten."
    ),
    "Referenz": (
        "Fehlende oder falsche Referenzen verursachen Folgefehler in Service, "
        "Abrechnung und Reporting - der Einzelfehler zieht viele Probleme nach sich."
    ),
    "Eindeutigkeit": (
        "Doppelte Schlüssel brechen Zuordnungen in allen nachgelagerten Prozessen - "
        "von Lager bis Service."
    ),
    "Vollstaendigkeit_SAP": (
        "SAP ist das führende System für Materialstammdaten. Fehlende Pflichtfelder "
        "blockieren den Abgleich mit CRM und Marketing."
    ),
    "Vollstaendigkeit_SF_Service": (
        "Fehlende Service-Pflichtfelder führen zu Leerfahrten und falscher Einsatzplanung."
    ),
    "Validitaet_Preis": (
        "Unplausible Preise können Angebote verfälschen und werden selten manuell "
        "erkannt - deshalb hohe Priorität."
    ),
    "Validitaet_Datum": (
        "Unplausible Datumswerte verzerren Reports und Wartungspläne."
    ),
}


def priority_reason(finding: Finding, cfg: Config) -> str:
    """Erzeugt einen verständlichen Satz, warum diese Priorität vergeben wurde."""
    severity = finding.severity
    impact = cfg.business_impact.get(finding.category, 5)
    deps = len(finding.follow_on) + (1 if finding.group_id else 0)
    parts: list[str] = []

    base = PRIORITY_REASONS.get(finding.category)
    if base:
        parts.append(base)

    if severity == "hoch":
        parts.append("Der Schweregrad ist hoch, weil ein Pflichtfeld, ein Schlüssel oder ein geschäftskritischer Wert betroffen ist.")
    elif severity == "mittel":
        parts.append("Der Schweregrad ist mittel - der Fehler behindert Prozesse, blockiert sie aber nicht vollständig.")
    else:
        parts.append("Der Schweregrad ist niedrig - meist eine kosmetische oder leicht korrigierbare Abweichung.")

    parts.append(f"Geschäftliche Bedeutung des Feldes: {impact}/10.")
    if deps:
        parts.append(f"Es sind {deps} abhängige Folgefehler oder zusammenhängende Befunde erkennbar - dadurch steigt die Dringlichkeit.")
    else:
        parts.append("Es wurden keine zusätzlichen Folgefehler erkannt.")

    if finding.priority_label == "Hoch":
        parts.append("Priorität 'Hoch': Sollte in den nächsten Tagen bearbeitet werden.")
    elif finding.priority_label == "Mittel":
        parts.append("Priorität 'Mittel': Sollte im Rahmen des nächsten Qualitätssprints bearbeitet werden.")
    else:
        parts.append("Priorität 'Niedrig': Kann im Rahmen regulärer Pflegeroutinen bearbeitet werden.")
    return " ".join(parts)


# ------------------------------------------------- Handlungsempfehlungen --
@dataclass
class Recommendation:
    title: str
    detail: str
    count: int
    filter_category: str | None = None
    filter_system: str | None = None
    filter_priority: str | None = None
    filter_region: str | None = None


def build_recommendations(findings: list[Finding]) -> list[Recommendation]:
    """Baut bis zu fünf konkrete Handlungsempfehlungen auf Basis der echten Befunde."""
    recs: list[Recommendation] = []
    if not findings:
        return recs

    cat_count = Counter(f.category for f in findings if f.priority_label == "Hoch")
    sys_count = Counter(f.system for f in findings if f.priority_label == "Hoch")
    region_count = Counter(
        f.region for f in findings
        if f.priority_label in ("Hoch", "Mittel") and f.region and f.region != "Nicht zugeordnet"
    )

    # 1. Preis-Konflikte HubSpot <-> Salesforce
    price_cross = [f for f in findings if f.rule_id == "CONS_PRICE_CROSS"]
    if price_cross:
        recs.append(Recommendation(
            title=f"{len(price_cross)} Preis-Differenzen zwischen HubSpot und Salesforce prüfen",
            detail=(
                "Für dieselbe Materialnummer gibt es im Standard-Preisbuch unterschiedliche Preise. "
                "Direkte Auswirkung auf Angebote und Online-Katalog."
            ),
            count=len(price_cross),
            filter_category="Konsistenz_Preis",
            filter_priority="Hoch",
        ))

    # 2. Produkte ohne SAP-Materialnummer
    missing_matnr = [f for f in findings if f.rule_id.startswith("CONS_MATNR_")]
    if missing_matnr:
        recs.append(Recommendation(
            title=f"{len(missing_matnr)} CRM-Produkte ohne gültige SAP-Materialnummer",
            detail=(
                "SAP ist laut Governance führendes System. Ohne Materialnummer-Verknüpfung "
                "können Preis-, Status- und Katalog-Sync nicht funktionieren."
            ),
            count=len(missing_matnr),
            filter_category="Konsistenz_Produkt",
        ))

    # 3. Service: falsche Kundenzuordnung
    wo_mismatch = [f for f in findings if f.rule_id == "REF_WO_ACC_MISMATCH"]
    if wo_mismatch:
        recs.append(Recommendation(
            title=f"{len(wo_mismatch)} Wartungsaufträge mit falscher Kundenzuordnung",
            detail=(
                "Der WorkOrder-Kunde weicht vom Asset-Kunden ab. Risiko: Rechnungen gehen an "
                "falsche Kunden, Techniker fahren zu falschen Einsatzorten."
            ),
            count=len(wo_mismatch),
            filter_category="Referenz",
        ))

    # 4. SAP-Material ausgelaufen, CRM noch aktiv
    status_cross = [f for f in findings if f.rule_id in ("CONS_STATUS_HS", "CONS_STATUS_SF")]
    if status_cross:
        recs.append(Recommendation(
            title=f"{len(status_cross)} ausgelaufene Produkte werden in HubSpot/Salesforce noch aktiv geführt",
            detail=(
                "Kampagnen und Angebote laufen für Produkte weiter, die laut SAP zur Löschung "
                "vorgemerkt oder im Auslauf sind."
            ),
            count=len(status_cross),
            filter_category="Konsistenz_Produkt",
        ))

    # 5. Schwächster Markt
    if region_count:
        region, n = region_count.most_common(1)[0]
        recs.append(Recommendation(
            title=f"Datenqualität in Region '{region}' am schwächsten ({n} relevante Befunde)",
            detail=(
                f"'{region}' konzentriert die meisten hoch- und mittelpriorisierten Befunde. "
                "Hier würde eine Qualitäts-Welle den größten Hebel haben."
            ),
            count=n,
            filter_region=region,
        ))

    # Ergänzen falls Liste zu kurz
    if len(recs) < 5:
        for cat, n in cat_count.most_common():
            if any(r.filter_category == cat for r in recs):
                continue
            recs.append(Recommendation(
                title=f"{n} hochpriorisierte Befunde in Kategorie '{cat}'",
                detail=(
                    "Mehrere kritische Befunde dieser Kategorie - sinnvoll in einem Zug zu bearbeiten."
                ),
                count=n,
                filter_category=cat,
            ))
            if len(recs) >= 5:
                break

    return recs[:5]


# ------------------------------------------------- Fehler-/Ursachen-Gruppen --
@dataclass
class CauseGroup:
    group_id: str
    record_id: str
    primary: Finding
    members: list[Finding]

    @property
    def systems(self) -> list[str]:
        return sorted({f.system for f in self.members})

    @property
    def max_priority_score(self) -> float:
        return max((f.priority_score for f in self.members), default=0.0)


def cause_groups(findings: list[Finding]) -> list[CauseGroup]:
    """Fasst alle Befunde mit derselben group_id zu einer Ursache-Gruppe zusammen.

    Als "Primär-Finding" gilt das mit dem höchsten Prioritätsscore.
    """
    buckets: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.group_id:
            buckets[f.group_id].append(f)
    out: list[CauseGroup] = []
    for gid, members in buckets.items():
        members_sorted = sorted(members, key=lambda f: -f.priority_score)
        primary = members_sorted[0]
        out.append(CauseGroup(
            group_id=gid,
            record_id=primary.record_id or "",
            primary=primary,
            members=members_sorted,
        ))
    out.sort(key=lambda g: -g.max_priority_score)
    return out


# ------------------------------------------------- Wiederkehrende Muster --
@dataclass
class RecurringPattern:
    label: str
    count: int
    unique_records: int
    example_rule: str
    hint: str


def recurring_patterns(findings: list[Finding], top: int = 10) -> list[RecurringPattern]:
    """Häufigste (Kategorie, Feld)-Kombinationen - potenzielle gemeinsame Ursachen."""
    bucket: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        bucket[(f.category, f.field_name)].append(f)
    patterns: list[RecurringPattern] = []
    for (category, field), fs in bucket.items():
        if len(fs) < 3:
            continue
        unique = len(unique_affected_records(fs))
        patterns.append(RecurringPattern(
            label=f"{category} · Feld '{field}'",
            count=len(fs),
            unique_records=unique,
            example_rule=fs[0].rule_name,
            hint=_hint_for_pattern(category, field, fs),
        ))
    patterns.sort(key=lambda p: -p.count)
    return patterns[:top]


def _hint_for_pattern(category: str, field: str, fs: list[Finding]) -> str:
    if category == "Validitaet_Status":
        return "Vermutlich fehlende Eingabe-Validierung oder nicht gepflegte Werteliste im Quellsystem."
    if category == "Validitaet_Datum":
        return "Vermutlich Erfassungsformat-Problem (z. B. deutsches vs. ISO-Datum) oder Tippfehler im Jahr."
    if category == "Konsistenz_Preis":
        return "Preisführerschaft nicht festgelegt oder Sync-Prozess zwischen Systemen defekt."
    if category == "Konsistenz_Produkt":
        return "Produktname-/Status-Sync zwischen SAP und CRM funktioniert nicht."
    if category == "Referenz":
        return "Vermutlich historisch gelöschte Datensätze oder falsches manuelles Mapping."
    if category == "Eindeutigkeit":
        return "Vermutlich fehlende Deduplizierung beim Import oder zweifache Anlage."
    return "Statistische Auffälligkeit - fachliche Prüfung der häufigsten Ursache empfohlen."


# ------------------------------------------------- Fachbereichs-Zusammenfassung --
@dataclass
class DepartmentSummary:
    department: str
    total: int
    high: int
    medium: int
    low: int
    unique_records: int
    top_categories: list[tuple[str, int]]


def department_summary(findings: list[Finding]) -> list[DepartmentSummary]:
    by_dept: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_dept[f.responsibility or "Unzugeordnet"].append(f)
    out: list[DepartmentSummary] = []
    for dept, fs in by_dept.items():
        sev = Counter(f.severity for f in fs)
        cats = Counter(f.category for f in fs).most_common(3)
        out.append(DepartmentSummary(
            department=dept,
            total=len(fs),
            high=sev.get("hoch", 0),
            medium=sev.get("mittel", 0),
            low=sev.get("niedrig", 0),
            unique_records=len(unique_affected_records(fs)),
            top_categories=cats,
        ))
    out.sort(key=lambda s: -s.high)
    return out


# ------------------------------------------------- Simulation Vorher/Nachher --
def simulate_resolution(findings: list[Finding], resolve_ids: set[str]) -> list[Finding]:
    """Gibt die verbleibenden Befunde zurück, wenn ``resolve_ids`` als 'behoben' markiert würden.

    Reine Vorher/Nachher-Simulation. Verändert die Originaldaten NICHT.
    """
    return [f for f in findings if f.finding_id not in resolve_ids]
