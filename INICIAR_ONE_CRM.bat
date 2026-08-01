@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title ONE CRM - Servidor
color 0B

echo ================================================================
echo   ONE CRM - INICIALIZADOR
echo ================================================================
echo.
echo Pasta: %CD%
echo Procurando uma instalacao valida do Python...
echo.

set "PY_CMD="
py -3.11 -c "import sys; assert sys.version_info >= (3,10); print(sys.version.split()[0])" >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.11"

if not defined PY_CMD (
  py -3 -c "import sys; assert sys.version_info >= (3,10); print(sys.version.split()[0])" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3"
)

if not defined PY_CMD (
  python -c "import sys; assert sys.version_info >= (3,10); print(sys.version.split()[0])" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
  echo [ERRO] Python 3.10 ou superior nao foi encontrado.
  echo Instale o Python marcando a opcao "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo Python selecionado: %PY_CMD%
echo Nenhuma biblioteca externa precisa ser instalada.
echo.
echo Iniciando o servidor...
echo.

%PY_CMD% one_crm_server.py
set "ONE_EXIT=%ERRORLEVEL%"

echo.
echo ================================================================
if "%ONE_EXIT%"=="0" (
  echo ONE CRM encerrado normalmente.
) else (
  echo [ERRO] O ONE CRM terminou com o codigo %ONE_EXIT%.
  echo Consulte o arquivo logs\one_crm.log.
)
echo ================================================================
pause
exit /b %ONE_EXIT%
