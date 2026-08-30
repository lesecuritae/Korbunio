@echo off
chcp 65001 >nul
setlocal
title KorbKlar einrichten
cd /d "%~dp0.."

echo.
echo   KorbKlar wird eingerichtet. Beim ersten Mal dauert das ein paar Minuten.
echo.

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo   Python wurde nicht gefunden.
    echo.
    echo   Bitte Python 3.12 oder neuer installieren, zum Beispiel so:
    echo       winget install Python.Python.3.13
    echo   oder von https://www.python.org/downloads/windows/
    echo   Im Setup den Haken bei "Add python.exe to PATH" setzen.
    echo.
    pause
    exit /b 1
)

echo   [1/3] Virtuelle Umgebung anlegen ...
%PY% -m venv .venv
if errorlevel 1 goto failed

echo   [2/3] Abhängigkeiten installieren ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install . --quiet
if errorlevel 1 goto failed

echo   [3/3] Verknüpfung auf dem Desktop anlegen ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1" -Root "%CD%"
if errorlevel 1 goto failed

echo.
echo   Fertig. Auf dem Desktop liegt jetzt "KorbKlar".
echo   Ein Doppelklick startet das Programm und öffnet den Browser.
echo.
pause
exit /b 0

:failed
echo.
echo   Die Einrichtung ist fehlgeschlagen. Bitte die Meldungen oben lesen.
echo.
pause
exit /b 1
