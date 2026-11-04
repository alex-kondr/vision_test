@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" main.py
    exit
)
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" main.py
    exit
)

where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start "" pythonw main.py
) else (
    start "" python main.py
)
exit
