@echo off
setlocal EnableDelayedExpansion

echo === BLEDeck Windows Build ===
echo.

REM ── Check PyInstaller ─────────────────────────────────────────────────────
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found.
    echo         Run: pip install -r requirements-build.txt
    exit /b 1
)

REM ── Clean previous artifacts ───────────────────────────────────────────────
if exist build (
    echo Cleaning build\...
    rmdir /s /q build
)
if exist dist\BLEDeck (
    echo Cleaning dist\BLEDeck\...
    rmdir /s /q dist\BLEDeck
)

REM ── Build ─────────────────────────────────────────────────────────────────
echo Building...
pyinstaller bledeck.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check output above.
    exit /b 1
)

REM ── Report ────────────────────────────────────────────────────────────────
echo.
echo === Build complete ===
echo.
echo   Output folder : dist\BLEDeck\
echo   Executable    : dist\BLEDeck\BLEDeck.exe
echo.
echo Move the entire dist\BLEDeck\ folder to any machine and run BLEDeck.exe.
echo profiles.json will be created there on first run.
echo.
