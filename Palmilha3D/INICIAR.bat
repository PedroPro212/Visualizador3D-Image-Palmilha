@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto erro
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto erro
.venv\Scripts\python.exe app.py
if errorlevel 1 goto erro
exit /b 0
:erro
echo Instale Python 3.11 ou superior com Tkinter e o Python Launcher.
echo A primeira execucao precisa de internet para instalar NumPy e Pillow.
pause
