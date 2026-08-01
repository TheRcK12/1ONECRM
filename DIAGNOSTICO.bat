@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title ONE CRM - Diagnostico
color 0E

echo ================================================================
echo   ONE CRM - DIAGNOSTICO
echo ================================================================
echo Pasta atual: %CD%
echo.
echo [1] Python Launcher:
where py 2>nul
py -0p 2>nul

echo.
echo [2] Python no PATH:
where python 2>nul
python --version 2>nul

echo.
echo [3] Arquivos essenciais:
if exist "one_crm_server.py" (echo [OK] one_crm_server.py) else (echo [FALTA] one_crm_server.py)
if exist "static\index.html" (echo [OK] static\index.html) else (echo [FALTA] static\index.html)
if exist "static\app.js" (echo [OK] static\app.js) else (echo [FALTA] static\app.js)
if exist "static\app.css" (echo [OK] static\app.css) else (echo [FALTA] static\app.css)

echo.
echo [4] Porta 8000:
netstat -ano | findstr ":8000"
if errorlevel 1 echo [LIVRE] Nenhum processo detectado na porta 8000.

echo.
echo [5] Teste de sintaxe:
py -3.11 -m py_compile one_crm_server.py 2>nul
if not errorlevel 1 (
  echo [OK] Codigo Python valido com Python 3.11.
) else (
  py -3 -m py_compile one_crm_server.py 2>nul
  if not errorlevel 1 (echo [OK] Codigo Python valido.) else (echo [ERRO] Falha no teste de sintaxe.)
)

echo.
echo [6] Bancos de dados:
if defined LOCALAPPDATA (
  if exist "%LOCALAPPDATA%\ONE_CRM\one_crm.db" (
    for %%F in ("%LOCALAPPDATA%\ONE_CRM\one_crm.db") do echo [OK] %%~fF - %%~zF bytes
  ) else if exist "%LOCALAPPDATA%\ANNIE_X\annie_x.db" (
    for %%F in ("%LOCALAPPDATA%\ANNIE_X\annie_x.db") do echo [OK LEGADO] %%~fF - %%~zF bytes
  ) else (
    echo [INFO] O banco sera criado no primeiro inicio.
  )
) else (
  echo [INFO] Pasta local data sera utilizada.
)

echo.
echo [7] Ultimas linhas do log:
if exist "logs\one_crm.log" (
  powershell -NoProfile -Command "Get-Content -Path 'logs\one_crm.log' -Tail 20"
) else (
  echo [INFO] Ainda nao existe log.
)

echo.
echo ================================================================
pause
