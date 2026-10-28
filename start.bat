@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start "" pythonw main.py
) else (
    start "" python main.py
)
exit
