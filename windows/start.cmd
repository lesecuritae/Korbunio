@echo off
chcp 65001 >nul
setlocal
title KorbKlar
cd /d "%~dp0.."

if not defined SUPERMARKT_PORT set "SUPERMARKT_PORT=8000"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   KorbKlar ist noch nicht eingerichtet.
    echo   Bitte zuerst windows\install.cmd starten.
    echo.
    pause
    exit /b 1
)

echo.
echo   KorbKlar läuft gleich auf http://127.0.0.1:%SUPERMARKT_PORT%/
echo   Der Browser öffnet sich von selbst.
echo.
echo   Zum Beenden dieses Fenster schließen oder Strg+C drücken.
echo.

rem ping statt timeout: funktioniert auch ohne eigene Konsole.
start "" /b cmd /c "ping -n 5 127.0.0.1 >nul & start "" http://127.0.0.1:%SUPERMARKT_PORT%/"

".venv\Scripts\python.exe" -m uvicorn supermarkt.asgi:app --host 127.0.0.1 --port %SUPERMARKT_PORT%

echo.
echo   KorbKlar wurde beendet.
pause
