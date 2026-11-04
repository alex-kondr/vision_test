@echo off
setlocal enabledelayedexpansion
title AutoFlow Assistant — Запуск
cd /d "%~dp0"

cls
echo.
echo  ==============================================================
echo     ⚡ AutoFlow Assistant  [AI Vision ^& Smart Automation]
echo  ==============================================================
echo.
echo   [>] Ініціалізація компонентів та візуального інтерфейсу...

rem Очищення мітки готовності
if exist "logs\.ready" del /q "logs\.ready" 2>nul
if not exist "logs" mkdir "logs" 2>nul

rem Пошук інтерпретатора Python
set "PY_BIN="
if exist ".venv\Scripts\pythonw.exe" set "PY_BIN=.venv\Scripts\pythonw.exe"
if not defined PY_BIN (
    if exist "venv\Scripts\pythonw.exe" set "PY_BIN=venv\Scripts\pythonw.exe"
)
if not defined PY_BIN (
    where pythonw >nul 2>nul
    if !ERRORLEVEL! EQU 0 set "PY_BIN=pythonw"
)
if not defined PY_BIN (
    where python >nul 2>nul
    if !ERRORLEVEL! EQU 0 set "PY_BIN=python"
)

if not defined PY_BIN (
    echo.
    echo   [ПОМИЛКА] Python не знайдено в системі!
    echo   Будь ласка, встановіть Python або активуйте віртуальне середовище.
    echo.
    pause
    exit /b 1
)

rem Запуск Python у фоновому режимі з анімованим Splash Screen
start "" "!PY_BIN!" main.py

rem Очікування готовності віконного інтерфейсу
set /a idx=0

:wait_loop
if exist "logs\.ready" goto ready

ping -n 1 -w 200 127.0.0.1 >nul 2>&1
set /a idx+=1

if !idx! geq 50 goto timeout_done
goto wait_loop

:ready
echo   [OK] Застосунок успішно запущено! Вікно активовано.
ping -n 1 -w 800 127.0.0.1 >nul 2>&1
exit

:timeout_done
if exist "logs\crash.log" (
    echo.
    echo   [УВАГА] Під час запуску виникла помилка. Перевірте logs\crash.log:
    type "logs\crash.log"
    echo.
    pause
    exit /b 1
)
exit
