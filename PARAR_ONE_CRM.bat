@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "server.pid" (
  echo O arquivo server.pid nao existe. O ONE CRM provavelmente ja esta parado.
  pause
  exit /b 0
)
set /p ONE_PID=<server.pid
if "%ONE_PID%"=="" (
  echo PID invalido.
  pause
  exit /b 1
)
echo Encerrando o ONE CRM - PID %ONE_PID%...
taskkill /PID %ONE_PID% /T >nul 2>&1
if errorlevel 1 (
  echo Nao foi possivel localizar o processo. Removendo PID antigo.
) else (
  echo ONE CRM encerrado.
)
del /q server.pid >nul 2>&1
pause
