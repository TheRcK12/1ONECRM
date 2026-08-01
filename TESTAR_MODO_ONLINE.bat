@echo off
setlocal
cd /d "%~dp0"
title ONE CRM - Teste do modo online
where py >nul 2>&1
if not errorlevel 1 (
  py -3.11 tests\online_mode_test.py
) else (
  python tests\online_mode_test.py
)
echo.
pause
