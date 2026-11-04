#!/usr/bin/env bash
#
# AgroTechNova Data Quality Copilot - Startskript für macOS/Linux.
# Doppelklick (oder `./start_mac.command`) genügt.
#
set -e

cd "$(dirname "$0")"

echo ""
echo "===================================================================="
echo "  AgroTechNova Data Quality Copilot"
echo "  Datenvertrauen. Transparenz. Bessere Entscheidungen."
echo "===================================================================="
echo ""

# --- Python-Prüfung -----------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[Fehler] python3 ist nicht installiert."
    echo "Installieren über https://www.python.org/downloads/ oder 'brew install python3'."
    exit 1
fi

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "[Fehler] Python 3.11 oder neuer wird benötigt (gefunden: $PY_MAJOR.$PY_MINOR)."
    exit 1
fi

# --- Virtuelle Umgebung -------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "Erstelle virtuelle Python-Umgebung (.venv)..."
    python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# --- Abhängigkeiten -----------------------------------------------------
if ! python3 -c "import streamlit" >/dev/null 2>&1; then
    echo "Installiere Abhängigkeiten (einmalig, dauert einen Moment)..."
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
fi

# --- Datenprüfung -------------------------------------------------------
if [ ! -d "data/input" ] || [ -z "$(ls data/input/*.xlsx 2>/dev/null)" ]; then
    echo ""
    echo "[Hinweis] Keine Excel-Dateien in data/input/ gefunden."
    echo "Bitte die vier Excel-Dateien dorthin kopieren und das Skript neu starten."
    echo ""
    exit 1
fi

echo ""
echo "Starte Anwendung unter http://localhost:8501"
echo "(Browser öffnet sich automatisch; mit CTRL+C beenden.)"
echo ""

exec streamlit run app/streamlit_app.py --server.port=8501
