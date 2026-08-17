@echo off
setlocal enabledelayedexpansion
title Backroom Arcade

echo.
echo  ==========================================
echo   BACKROOM ARCADE  ^|  Python Backend
echo  ==========================================
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo.
    echo  Download from https://www.python.org/downloads/
    echo  Check "Add Python to PATH" during install.
    echo.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Python %PYVER% detected.

:: ── Virtual environment ───────────────────────────────────────────────────────
if not exist "venv\" (
    echo  [SETUP] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 ( echo  [ERROR] venv creation failed. & pause & exit /b 1 )
    echo  [OK] Virtual environment created.
)
call venv\Scripts\activate.bat

:: ── Dependencies ──────────────────────────────────────────────────────────────
echo  [SETUP] Checking Python dependencies...
pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 ( echo  [ERROR] pip install failed. & pause & exit /b 1 )
echo  [OK] Dependencies ready.

:: ── Data directories ──────────────────────────────────────────────────────────
if not exist "static\uploads\games\" mkdir static\uploads\games

:: ── Load .env ─────────────────────────────────────────────────────────────────
if exist ".env" (
    echo  [OK] Loading .env...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" if not "%%a"=="" set "%%a=%%b"
    )
)

:: ── Defaults ──────────────────────────────────────────────────────────────────
if not defined SESSION_SECRET (
    set "SESSION_SECRET=dev-%DATE%-%TIME%"
    echo  [WARN] SESSION_SECRET not set. Using a temporary value.
    echo         Set a real one in .env before going public.
)
if not defined DEFAULT_ADMIN_PASSWORD set DEFAULT_ADMIN_PASSWORD=ChangeMe123!
if not defined PORT set PORT=3000

:: ── Print info ────────────────────────────────────────────────────────────────
echo.
echo  ==========================================
echo   Arcade:        http://localhost:%PORT%
echo   Eaglercraft:   NOT running (arcade-only mode)
echo.
echo   To also run the Eaglercraft server, use:
echo     docker compose up
echo  ==========================================
echo.
echo  NOTE: The Eaglercraft server requires Docker.
echo  The arcade itself runs fine without it.
echo  Games, chat, and admin panel are all available.
echo.

:: ── Open browser ─────────────────────────────────────────────────────────────
start "" cmd /c "timeout /t 2 >nul && start http://localhost:%PORT%"

:: ── Start Flask ───────────────────────────────────────────────────────────────
python app.py

echo.
echo  [INFO] Server stopped.
pause
endlocal
