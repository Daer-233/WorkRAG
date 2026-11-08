@echo off
setlocal
cd /d "%~dp0"
title Work Knowledge Assistant - Stop

set "NOPAUSE="
for %%A in (%*) do if /I "%%~A"=="--no-pause" set "NOPAUSE=1"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [error] Python environment missing: %PYTHON%
    echo         Create it with: python -m venv .venv
    if not defined NOPAUSE pause
    exit /b 1
)

"%PYTHON%" "%~dp0deployment\stop_all.py" %*
set "KNOWLEDGE_EXIT_CODE=%ERRORLEVEL%"

echo.
if not defined NOPAUSE pause
exit /b %KNOWLEDGE_EXIT_CODE%
