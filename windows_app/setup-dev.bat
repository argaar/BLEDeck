@echo off
REM Developer setup for BLEDeck Windows app.
REM Installs runtime + test + build dependencies into the active environment.
REM Usage: from inside an activated venv, run setup-dev.bat

setlocal

cd /d "%~dp0"

echo Creating virtualenv...
python -m venv env

echo Activating it...
.\env\Script\activate

echo Installing runtime dependencies...
python -m pip install -r requirements.txt || goto :fail

echo.
echo Installing development dependencies (pytest, etc.)...
python -m pip install -r requirements-dev.txt || goto :fail

echo.
echo Installing build dependencies (PyInstaller)...
python -m pip install -r requirements-build.txt || goto :fail

echo.
echo Verifying setup by running the test suite...
python -m pytest tests\ -q || goto :fail

echo.
echo Setup complete. Run the app with: python main.py    or build with: build.bat
exit /b 0

:fail
echo.
echo ERROR: setup failed. Inspect the messages above.
exit /b 1
