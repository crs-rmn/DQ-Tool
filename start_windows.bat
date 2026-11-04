@echo off
REM AgroTechNova Data Quality Copilot - Startskript für Windows.
REM Doppelklick genügt.

cd /d "%~dp0"

echo.
echo ====================================================================
echo   AgroTechNova Data Quality Copilot
echo   Datenvertrauen. Transparenz. Bessere Entscheidungen.
echo ====================================================================
echo.

REM --- Python-Prüfung ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [Fehler] Python ist nicht installiert oder nicht im PATH.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Virtuelle Umgebung ---
if not exist ".venv\" (
    echo Erstelle virtuelle Python-Umgebung (.venv)...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM --- Abhängigkeiten ---
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installiere Abhaengigkeiten (einmalig, dauert einen Moment)...
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
)

REM --- Datenprüfung ---
if not exist "data\input\*.xlsx" (
    echo.
    echo [Hinweis] Keine Excel-Dateien in data\input\ gefunden.
    echo Bitte die vier Excel-Dateien dorthin kopieren und neu starten.
    echo.
    pause
    exit /b 1
)

echo.
echo Starte Anwendung unter http://localhost:8501
echo (Browser oeffnet sich automatisch; mit CTRL+C beenden.)
echo.

streamlit run app\streamlit_app.py --server.port=8501
pause
