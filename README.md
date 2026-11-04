# AgroTechNova Data Quality Copilot

> Datenvertrauen. Transparenz. Bessere Entscheidungen.

Ein lokal ausführbares Data-Quality-Tool für die Hackathon-Challenge **"Mission Datenvertrauen"**. Das Tool liest Produkt-, Service- und Preisdaten aus SAP, Salesforce und HubSpot ein, prüft sie mit über 20 Regeln, priorisiert Befunde nach geschäftlicher Dringlichkeit, zeigt einen Qualitäts-Score je Markt und liefert einen jury-konformen CSV-/Excel-Export.

![Übersicht](docs/screenshot-dashboard.png)

---

## 1. Voraussetzungen

- **Python 3.11 oder neuer** (getestet mit 3.14)
- Betriebssystem: macOS, Linux oder Windows
- ~200 MB freier Festplattenplatz (für Abhängigkeiten)
- Keine Internetverbindung nötig, kein API-Schlüssel nötig

## 2. Installation (macOS)

Terminal im Projektordner öffnen und ausführen:

```bash
./start_mac.command
```

Das Skript legt eine virtuelle Python-Umgebung an, installiert die Abhängigkeiten und startet die Anwendung im Browser (http://localhost:8501).

### Manuell

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## 3. Installation (Windows)

```cmd
start_windows.bat
```

### Manuell (Windows)

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app\streamlit_app.py
```

## 4. Projektstruktur

```
agrotechnova-dq-copilot/
├── app/
│   └── streamlit_app.py       # UI (Streamlit)
├── config/
│   ├── governance.yaml        # Führende Systeme, Pflichtfelder, zulässige Werte
│   └── weights.yaml           # Score- und Prioritätsgewichte
├── data/
│   ├── input/                 # Die vier Excel-Dateien
│   ├── exports/               # Generierte Befundlisten
│   └── history.sqlite         # Analyse-Historie
├── scripts/
│   ├── inspect_data.py        # Diagnose der Excel-Dateien
│   └── smoke_test.py          # Engine-Smoketest
├── src/atn_dq/
│   ├── loader.py              # Excel einlesen, Spalten erkennen
│   ├── normalize.py           # Land/Währung/Preis/Datum normalisieren
│   ├── finding.py             # Datenstruktur für einen Befund
│   ├── config.py              # Governance-Konfiguration laden
│   ├── rules/                 # Regel-Module (completeness, validity, …)
│   ├── engine.py              # Regel-Orchestrator inkl. Region & Gruppierung
│   ├── priority.py            # Score pro Befund
│   ├── score.py               # Gesamt- und Regions-Score
│   ├── export.py              # CSV- und Excel-Export
│   └── history.py             # SQLite-Historie
├── tests/                     # pytest-Suite
├── requirements.txt
├── start_mac.command
├── start_windows.bat
└── README.md
```

## 5. Dateien bereitstellen - zwei Wege

Mitarbeiter haben **zwei gleichwertige Optionen**, ihre Excel-Dateien in die Analyse zu bringen:

### A) Drag & Drop direkt in der App (empfohlen für einmalige Prüfung)

In der Seitenleiste gibt es den Bereich **"Dateien hochladen (Drag & Drop)"**. Dateien dort hineinziehen → sie werden sofort in die Analyse aufgenommen. Optional kann die Checkbox *"Auch dauerhaft in data/input/ speichern"* aktiviert werden, dann landen die Dateien zusätzlich im Projektordner und stehen bei zukünftigen Starts automatisch zur Verfügung.

### B) Direkt in den Ordner kopieren (für regelmäßige Analysen)

Dateien in `data/input/` legen (auch über den Finder oder per `cp`), dann links auf **"Analyse neu ausführen"** klicken.

Beide Wege lassen sich **kombinieren**: Ordner-Dateien und Upload-Dateien werden für die Analyse zusammengeführt. Die App zeigt in der Seitenleiste jederzeit, wie viele Dateien aus dem Ordner und wie viele per Upload geladen wurden.

## 6. Ablauf der Analyse

Beim Start bzw. beim Klick auf "Analyse (neu) ausführen" passiert folgendes automatisch:

1. **Daten einlesen** – `data/input/*.xlsx` + hochgeladene Dateien werden geladen. Die Blätter *Uebersicht* und *Feldlegende* werden ignoriert, die eigentliche Kopfzeile wird je Blatt automatisch erkannt.
2. **Regeln ausführen** – 20+ Regeln aus `src/atn_dq/rules/` prüfen Vollständigkeit, Eindeutigkeit, Validität, Konsistenz, referentielle Integrität, zeitliche Plausibilität und Anomalien.
3. **Befunde anreichern** – jedes Finding bekommt Land/Region (aus Account/Asset/WorkOrder), vorgeschlagenen Fachbereich und eine Ursache-/Folge-Gruppe.
4. **Priorisierung** – transparenter Score 0–100, zusammengesetzt aus Schweregrad (40 %), Geschäftlicher Auswirkung (30 %), Anteil betroffener Datensätze (15 %) und Abhängigkeiten (15 %). Gewichte in `config/weights.yaml`.
5. **Qualitäts-Score** – pro Dimension (Vollständigkeit, Validität, …) und pro Region (DACH, Benelux, …) separat berechnet.
6. **Export & Historie** – CSV/Excel mit den Pflichtspalten laut Hackathon-Briefing sowie SQLite-Historie für den Lauf-zu-Lauf-Vergleich.

## 7. Seiten der Anwendung

| Seite | Was man dort findet |
| --- | --- |
| **Übersicht** | Gesamt-Score, KPIs für Befunde vs. eindeutig betroffene Datensätze, **Handlungsempfehlungen "Was zuerst?"** mit Klick-Durchstieg in die Befundliste, Dimensionen-Chart mit Erklärung, Markt-Ampel. |
| **Befunde** | Vollständige Befundliste mit Filtern. Detailansicht mit Was/Warum/Wo/Wie, **Begründung der Priorität in Klartext** und Status-Workflow. CSV-/Excel-Export mit Jury-Pflichtspalten. |
| **Ursachenanalyse** | Mehrere Befunde zu demselben Datensatz werden als Ursache-/Folge-Gruppe dargestellt. Zusätzlich: wiederkehrende Muster (Kategorie × Feld) mit Hinweis auf mögliche gemeinsame Ursache. |
| **Länder & Regionen** | Score und Befundverteilung pro Markt. **Drill-down** auf eine Region zeigt häufigste Kategorien, Felder, Systeme und die 10 dringendsten Befunde. |
| **Fachbereiche** | Pro Abteilung (Service, Vertrieb, Stammdatenmanagement, …): Anzahl Hoch/Mittel/Niedrig, eindeutige Datensätze, Top-10-Befunde und **eigener Excel-Export für den Fachbereich**. |
| **Datenquellen** | Übersicht aller geladenen Tabellen mit Status-Ampel, Rohdaten-Vorschau je Blatt. |
| **Korrekturvorschläge** | Drei Kategorien **A (sichere Korrektur)**, **B (Vorschlag, bestätigen)**, **C (manuelle Prüfung)**. Markieren einzelner Befunde als "simuliert behoben". Kein automatisches Ändern der Originaldaten. |
| **Vorher / Nachher** | Simulation: Wie würde sich der Score verändern, wenn die auf **Korrekturvorschläge** markierten Befunde behoben wären? Chart pro Dimension. Ehrlich, wenn nichts markiert ist. |
| **Regeln** | Alle 20+ Regeln dokumentiert mit Kategorie, Dimension und Beschreibung. |
| **Verlauf** | SQLite-Historie der Läufe inkl. Diff zweier Läufe (neu / noch offen / nicht mehr gefunden). |
| **Einstellungen** | Governance (führende Systeme, offene Entscheidungen), Score- und Prioritätsgewichtung, Business-Impact pro Kategorie, Verantwortlichkeiten – alles transparent sichtbar. |
| **Demo-Ablauf** | Geführter 8-Schritte-Durchgang für die Jury mit "Öffnen"-Button je Schritt. |

## 8. Pflichtspalten im Export (laut Briefing)

Der CSV-/Excel-Export liefert mindestens diese Spalten:

| Spalte | Beschreibung |
| --- | --- |
| Datei | Original-Dateiname (z. B. `AgroTechNova_Service_Salesforce_dirty.xlsx`) |
| Blatt | Original-Blattname |
| Zeile | 1-basierte Excel-Zeile |
| Feld | Betroffene(s) Feld(er) |
| Befund | Kurzbeschreibung |
| Schweregrad | `hoch` / `mittel` / `niedrig` |

Zusätzlich werden Priorität, Prioritätsscore, Region, Verantwortlicher, Korrekturvorschlag, Befundgruppe, Ursache und Folgefehler exportiert.

## 9. Qualitäts-Score – wie berechnet?

**Pro Dimension**: Score = 100 − (gewichtete Befund-Last / geprüfte Datensätze) × 100
Jeder Befund zählt mit seinem Schweregrad (hoch=1.0 · mittel=0.4 · niedrig=0.1).

**Gesamt-Score**: gewichteter Mittelwert über alle Dimensionen – Gewichte in `config/weights.yaml`.

**Regions-Score**: identisch, aber nur für Befunde mit Marktzuordnung. Regionen mit weniger als 5 Datensätzen werden mit *„Keine ausreichende Datenbasis"* ausgewiesen, nicht mit einem Fantasie-Score.

Der Score beschreibt die Qualität **innerhalb der tatsächlich ausgeführten Prüfungen**. Er ist kein absoluter Beweis.

## 10. Governance anpassen

Alle fachlichen Entscheidungen sind in `config/governance.yaml` versammelt. Fachbereiche können ohne Code-Änderung:

- Führende Systeme je Datenbereich festlegen
- Pflichtfelder pro Objekt erweitern
- Zulässige Wertelisten (Status, Mengeneinheit, Währung) anpassen
- Bekannte Alias-Korrekturen hinterlegen (z. B. `AKTIV → ACTIVE`)
- Verantwortliche Fachbereiche je Fehlerkategorie zuweisen

Gewichte für Priorität und Score liegen in `config/weights.yaml`.

Einträge mit `Governance_Entscheidung_erforderlich` sind **offene Fragen**, die die Fachabteilung klären muss. Die Anwendung erfindet keine Regeln.

## 11. Neue Regeln hinzufügen

Eine neue Regel ist eine Funktion mit Dekorator:

```python
from atn_dq.rules.base import registry
from atn_dq.finding import Finding, DIM_VALIDITY, SEVERITY_MEDIUM

@registry.register(
    rule_id="VALIDITY_EXAMPLE",
    name="Mein Prüfung",
    description="Was die Regel prüft.",
    category="Validitaet_Allgemein",
    dimension=DIM_VALIDITY,
)
def rule_example(pkg, cfg):
    sheet = pkg.get("HS_Products")
    for i, row in sheet.df.iterrows():
        if row["price"] == 0:
            yield Finding(..., severity=SEVERITY_MEDIUM, ...)
```

Die Regel taucht automatisch im UI unter *Regeln* auf.

## 12. Tests ausführen

```bash
pytest -q
```

Deckt Loader, Normalisierung, Engine, Export und Historie ab.

## 13. Fehlerbehebung

| Problem | Lösung |
| --- | --- |
| `ModuleNotFoundError: streamlit` | `source .venv/bin/activate` vergessen, oder `pip install -r requirements.txt` |
| `FileNotFoundError: data/input` | Excel-Dateien nach `data/input/` kopieren |
| App startet, aber keine Befunde | Dateinamen prüfen – Loader erkennt SAP/HubSpot/Salesforce anhand des Dateinamens |
| Port 8501 belegt | `streamlit run app/streamlit_app.py --server.port 8502` |

## 14. Datenschutz

- Alle Berechnungen laufen lokal.
- Es werden keine Daten an externe Dienste gesendet.
- Es werden keine API-Keys benötigt.
- Es gibt keine optionale KI-Integration, die ohne ausdrückliche Freigabe Daten versendet.

## 15. Erweiterung um neue Datenquellen

Neue Dateien in `data/input/` werden automatisch gefunden. Für neue Systeme:

1. In `src/atn_dq/loader.py` den Dateinamen-Erkenner (`_detect_subsystem`) erweitern.
2. Für jedes relevante Blatt einen Eintrag in `SHEET_KEY_MAP` ergänzen.
3. Bei neuen Objekttypen ggf. Pflichtfelder in `config/governance.yaml` hinterlegen.

Die Regeln bleiben unverändert – sie wirken automatisch auf die neuen Blätter, sobald diese registriert sind.

## 16. Lizenz & Mitwirkende

Entwickelt für die Hackathon-Challenge **Mission Datenvertrauen** (AgroTechNova).
Code steht dem Veranstalter zur freien Nachnutzung zur Verfügung.
