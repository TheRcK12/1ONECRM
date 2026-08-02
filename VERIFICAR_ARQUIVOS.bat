@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo Verificando pacote ONE CRM 1.7.1...
findstr /c:"APP_VERSION = \"1.7.1-beta.1\"" one_crm_server.py >nul || goto erro
findstr /c:"def api_role_create" one_crm_server.py >nul || goto erro
findstr /c:"id=\"new-role\"" static\app.js >nul || goto erro
findstr /c:"/api/roles" static\app.js >nul || goto erro
echo.
echo OK: arquivos corretos para commit.
pause
exit /b 0
:erro
echo.
echo ERRO: pacote incompleto ou arquivo incorreto.
pause
exit /b 1
