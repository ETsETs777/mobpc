@echo off
chcp 65001 >nul
setlocal
title mobpc — агент
cd /d "%~dp0agent"

rem Кэш pip и временные файлы — внутри папки проекта, а не на системном диске.
set "PIP_CACHE_DIR=%~dp0.cache\pip"
set "TEMP=%~dp0.cache\tmp"
set "TMP=%~dp0.cache\tmp"
if not exist "%TEMP%" mkdir "%TEMP%"

if exist ".venv\Scripts\python.exe" goto :deps
echo [mobpc] Первый запуск: создаю окружение Python...
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m venv .venv) else (python -m venv .venv)
if not exist ".venv\Scripts\python.exe" goto :nopython

:deps
if exist ".venv\.deps-ok" goto :run
echo [mobpc] Устанавливаю зависимости, это займёт минуту...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :piperror
echo ok> ".venv\.deps-ok"

:run
echo [mobpc] Запускаю агент. Если Windows спросит про доступ к сети — разрешите для частных сетей.
".venv\Scripts\python.exe" main.py --open %*
echo.
echo [mobpc] Агент остановлен.
pause
exit /b 0

:nopython
echo [mobpc] Python не найден. Установите Python 3.10 или новее:
echo         winget install Python.Python.3.12
pause
exit /b 1

:piperror
echo [mobpc] Не удалось установить зависимости. Проверьте подключение к интернету.
pause
exit /b 1
