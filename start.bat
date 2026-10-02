@echo off
rem Starts Ledgerfolio on this PC: the blockchain node and the website, each in
rem its own window. Close a window (or press Ctrl+C in it) to stop that part.
rem MySQL must already be running: open Laragon and click "Start All".

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo The Python environment is missing. See README.md, "Install on a new PC".
  pause
  exit /b 1
)

start "Ledgerfolio blockchain node" cmd /k ".venv\Scripts\python.exe -m chain_node"
timeout /t 3 /nobreak >nul
start "Ledgerfolio website" cmd /k ".venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8000/"
