@echo off
setlocal
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% -m pip install -r "%~dp0requirements.txt" || (echo Не удалось установить зависимости & pause & exit /b 1)
%PY% "%~dp0aurora_music.py" || pause
