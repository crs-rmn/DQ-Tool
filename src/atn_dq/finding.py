"""Datenstruktur für einen einzelnen Qualitäts-Befund."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib


# Konstanten für Schweregrad - diese werden sowohl intern als auch im Export verwendet
SEVERITY_HIGH = "hoch"
SEVERITY_MEDIUM = "mittel"
SEVERITY_LOW = "niedrig"

VALID_SEVERITIES = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)

# Standard-Qualitätsdimensionen
DIM_COMPLETENESS = "Vollstaendigkeit"
DIM_VALIDITY = "Validitaet"
DIM_UNIQUENESS = "Eindeutigkeit"
DIM_CONSISTENCY = "Konsistenz"
DIM_REFERENCE = "Referenz"
DIM_TEMPORAL = "Zeitliche_Plausibilitaet"
DIM_ANOMALY = "Anomalie"


@dataclass
class Finding:
    """Ein einzelner Befund mit allen Export-Pflichtfeldern."""

    rule_id: str                        # z. B. "SAP_MATNR_UNIQUE"
    rule_name: str                      # Menschenlesbare Beschreibung
    category: str                       # z. B. "Vollstaendigkeit_SAP"
    dimension: str                      # Qualitätsdimension (siehe Konstanten)
    system: str                         # SAP, Salesforce, HubSpot
    file: str                           # Dateiname
    sheet: str                          # Blattname
    row: int                            # Excel-Zeile (1-basiert)
    field_name: str                     # Betroffenes Feld
    value: Any                          # Originalwert
    message: str                        # Kurzbeschreibung des Problems
    severity: str                       # hoch | mittel | niedrig
    explanation: str = ""               # Verständliche Erklärung
    business_impact: str = ""           # Geschäftliche Auswirkung
    cause: str = ""                     # Mögliche Ursache
    follow_on: list[str] = field(default_factory=list)  # Folgefehler
    record_id: str | None = None        # Primärschlüssel des betroffenen Datensatzes
    country: str | None = None          # Land (für Score pro Markt)
    region: str | None = None           # Region
    responsibility: str = ""            # Vorgeschlagener Fachbereich
    correction_suggestion: str = ""     # Korrekturvorschlag
    correction_type: str = "Vorschlag"  # Sichere_Korrektur | Vorschlag | Manuelle_Pruefung
    status: str = "Offen"               # Offen | In_Bearbeitung | Abgelehnt | Behoben
    priority_score: float = 0.0         # 0-100
    priority_label: str = ""            # Hoch | Mittel | Niedrig
    group_id: str | None = None         # Zusammengehörige Befunde (Ursache -> Folgen)
    tags: list[str] = field(default_factory=list)
    confidence: str = "sicher"          # sicher | wahrscheinlich | unsicher

    @property
    def finding_id(self) -> str:
        key = f"{self.rule_id}|{self.file}|{self.sheet}|{self.row}|{self.field_name}|{self.record_id}"
        return "ATN-" + hashlib.sha1(key.encode()).hexdigest()[:10].upper()

    def to_export_row(self) -> dict[str, Any]:
        """Export-Zeile mit Pflichtspalten gemäß Hackathon-Briefing."""
        follow_txt = "; ".join(self.follow_on) if self.follow_on else ""
        return {
            # Pflichtspalten laut Briefing
            "Datei":       self.file,
            "Blatt":       self.sheet,
            "Zeile":       self.row,
            "Feld":        self.field_name,
            "Befund":      self.message,
            "Schweregrad": self.severity,
            # Erweiterte Spalten
            "Befund-ID":            self.finding_id,
            "System":               self.system,
            "Regel":                self.rule_name,
            "Fehlerkategorie":      self.category,
            "Qualitätsdimension":   self.dimension,
            "Prioritätsscore":      round(self.priority_score, 1),
            "Priorität":            self.priority_label,
            "Betroffener Datensatz": self.record_id or "",
            "Originalwert":         "" if self.value is None else str(self.value),
            "Erklärung":            self.explanation,
            "Geschäftliche Auswirkung": self.business_impact,
            "Ursache":              self.cause,
            "Folgefehler":          follow_txt,
            "Land":                 self.country or "",
            "Region":               self.region or "",
            "Verantwortlicher":     self.responsibility,
            "Korrekturvorschlag":   self.correction_suggestion,
            "Korrekturart":         self.correction_type,
            "Status":               self.status,
            "Konfidenz":            self.confidence,
            "Befundgruppe":         self.group_id or "",
        }
