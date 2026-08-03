@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title ONE CRM - Testes
color 0A
set "PY_CMD="
py -3.11 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1 && set "PY_CMD=py -3.11"
if not defined PY_CMD py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
  echo Python 3.10 ou superior nao encontrado.
  pause
  exit /b 1
)
echo Executando testes isolados. O banco real nao sera alterado.
echo.
%PY_CMD% tests\smoke_test.py
if errorlevel 1 (set "RC=1" & goto :resultado)
%PY_CMD% tests\ai_providers_test.py
set "RC=%ERRORLEVEL%"
:resultado
echo.
if "%RC%"=="0" (echo TODOS OS TESTES PASSARAM.) else (echo ALGUM TESTE FALHOU. Codigo: %RC%)
pause
exit /b %RC%
