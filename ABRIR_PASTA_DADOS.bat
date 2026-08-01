@echo off
setlocal
if defined LOCALAPPDATA (
  if exist "%LOCALAPPDATA%\ONE_CRM\one_crm.db" (
    start "" "%LOCALAPPDATA%\ONE_CRM"
  ) else if exist "%LOCALAPPDATA%\ANNIE_X\annie_x.db" (
    start "" "%LOCALAPPDATA%\ANNIE_X"
  ) else (
    if not exist "%LOCALAPPDATA%\ONE_CRM" mkdir "%LOCALAPPDATA%\ONE_CRM"
    start "" "%LOCALAPPDATA%\ONE_CRM"
  )
) else (
  start "" "%~dp0data"
)
