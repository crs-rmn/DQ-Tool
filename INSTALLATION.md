# Installations- und Startanleitung — AgroTechNova Data Quality Copilot

*Für Fachabteilungen. Keine Programmierkenntnisse nötig. Dauer: einmalig ca. 10 Minuten.*

---

## Was Sie brauchen

- Einen Windows- oder Mac-Rechner
- Die vier Excel-Dateien aus den Systemen (SAP, Salesforce Produktdaten, Salesforce Service, HubSpot)
- Internet nur **einmalig** für die Installation. Danach läuft alles lokal — keine Daten verlassen Ihren Rechner.

---

## Schritt 1 — Python installieren (nur beim allerersten Mal)

Das Tool braucht „Python" (eine kostenlose Grundsoftware).

1. Öffnen Sie **https://www.python.org/downloads/**
2. Klicken Sie auf den großen gelben Knopf **„Download Python 3.1x"**.
3. Installationsdatei öffnen.
   - **Windows:** Ganz unten im Fenster zuerst **„Add python.exe to PATH"** anhaken, dann **„Install Now"**.
   - **Mac:** Einfach durchklicken („Fortfahren" → „Installieren").
4. Fertig. Dieser Schritt entfällt bei jedem weiteren Start.

---

## Schritt 2 — Das Tool holen

Sie haben den Projektordner `DQ-Tool` entweder schon auf dem Rechner, oder Sie laden ihn von GitHub:

- **Fertiger Ordner:** Nutzen Sie den Ordner, den die IT / Ihr Team Ihnen gegeben hat.
- **Von GitHub:** Seite **https://github.com/crs-rmn/DQ-Tool** öffnen → grüner Knopf **„Code" → „Download ZIP"** → ZIP entpacken.

Legen Sie den Ordner an einen Ort, den Sie wiederfinden (z. B. Desktop).

---

## Schritt 3 — Die Excel-Dateien bereitstellen

Sie haben **zwei Möglichkeiten** — beide funktionieren:

**A) In den Ordner legen (für regelmäßige Nutzung)**
Kopieren Sie die vier Excel-Dateien in den Unterordner `data/input/` im Projektordner.
> Die Dateinamen müssen das System erkennen lassen: `…SAP…` oder `…MARC…`, `…Produktdaten_Salesforce…`, `…Service_Salesforce…`, `…HubSpot…`.

**B) Später im Tool hochziehen (für einmalige Prüfung)**
Ordner leer lassen und die Dateien nach dem Start einfach per Maus in die Upload-Fläche in der linken Leiste ziehen.

---

## Schritt 4 — Starten

- **Mac:** Im Projektordner die Datei **`start_mac.command`** doppelklicken.
  - Erscheint „kann nicht geöffnet werden": Rechtsklick auf die Datei → **„Öffnen"** → **„Öffnen"** bestätigen (nur beim ersten Mal).
- **Windows:** Die Datei **`start_windows.bat`** doppelklicken.

Beim ersten Start richtet sich das Tool selbst ein (lädt einmalig die Bausteine herunter, ca. 1–2 Minuten). Danach öffnet sich automatisch Ihr Browser mit der Anwendung unter **http://localhost:8501**.

> **Großdaten-Hinweis:** Bei den vollständigen Unternehmensdaten (mehrere hunderttausend Zeilen) dauert die **erste** Analyse ca. 1,5 Minuten. Danach ist alles zwischengespeichert und läuft schnell. **Tipp für Präsentationen:** Das Tool einmal vor dem Termin starten, damit die Analyse schon „warm" ist.

---

## Schritt 5 — Arbeiten mit dem Tool

Links in der Leiste wählen Sie den Bereich:

- **Mein Dashboard / Übersicht** — Wie gut sind unsere Daten, wo ist es am dringendsten?
- **Befunde** — Die Fehlerliste mit Filter, Suche und Detail-Erklärung je Fehler.
- **Geschäftliche Auswirkungen** — Wo Daten einen Euro-Betrag hergeben, was nur ein Risiko ist.
- **Länder & Regionen / Fachbereiche** — Wo und wer ist betroffen.
- **Korrekturvorschläge** — Was lässt sich wie beheben.

### Fehlerliste abgeben (CSV / Excel)
Bereich **Befunde** → Knopf **„CSV exportieren"** bzw. **„Excel exportieren"**.
Die Datei enthält je Fehler eine Zeile mit den geforderten Spalten
**Datei, Blatt, Zeile, Feld, Befund, Schweregrad** (hoch/mittel/niedrig) und weiteren Zusatzspalten.

---

## Beenden

Im schwarzen Terminal-Fenster **`Strg + C`** (Windows) bzw. **`Ctrl + C`** (Mac) drücken,
oder das Fenster schließen.

---

## Wenn etwas klemmt

| Problem | Lösung |
| --- | --- |
| Browser öffnet nicht | Im Browser selbst **http://localhost:8501** eingeben. |
| „python wird nicht gefunden" (Windows) | Python neu installieren und dabei **„Add to PATH"** anhaken. |
| Mac blockiert `start_mac.command` | Rechtsklick → „Öffnen" → „Öffnen". |
| Keine Befunde / falsches System | Dateinamen prüfen (siehe Schritt 3) — das System wird am Namen erkannt. |
| Analyse sehr langsam | Normal bei der ersten Großdaten-Analyse. Einmal warten, danach ist es schnell. |

---

## Datenschutz

Alle Berechnungen laufen ausschließlich auf Ihrem Rechner. Es werden keine Daten
an externe Dienste gesendet, kein Schlüssel oder Konto ist nötig. Die Original-Excel-Dateien
werden nie verändert — Korrekturen fließen nur in Export-Dateien.
