@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PY_CMD="
py -3.11 -c "import tkinter" >nul 2>&1 && set "PY_CMD=py -3.11"
if not defined PY_CMD py -3 -c "import tkinter" >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD python -c "import tkinter" >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
  echo Python com Tkinter nao encontrado.
  pause
  exit /b 1
)
%PY_CMD% IMPORTAR_ANNIE_1_1.py
if errorlevel 1 pause
