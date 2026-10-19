@echo off
title AutoFlow Assistant
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo Application exited with an error.
    pause
)
