@echo off
REM Unified test runner — runs Python (windows_app + simulator) AND firmware
REM native unit tests. Each suite's exit code is reported; the script exits
REM with 0 only if every suite passes.

setlocal enabledelayedexpansion

cd /d "%~dp0"
set "PY_RC=0"
set "PIO_RC=0"

echo === Python tests (windows_app + simulator) ===
python -m pytest windows_app\tests\ simulator\tests\ -q
set "PY_RC=%ERRORLEVEL%"

echo.
echo === Firmware native tests (Unity) ===
where pio >nul 2>&1
if errorlevel 1 (
    echo SKIP: PlatformIO CLI 'pio' not on PATH — install with 'pip install platformio'
    set "PIO_RC=0"
) else (
    pio test -e native -d firmware
    set "PIO_RC=!ERRORLEVEL!"
)

echo.
echo === Summary ===
echo Python   : exit code %PY_RC%
echo Firmware : exit code %PIO_RC%

if not "%PY_RC%"=="0" exit /b %PY_RC%
exit /b %PIO_RC%
