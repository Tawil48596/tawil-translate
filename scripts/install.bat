@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[desktop]"
echo Installation complete. Run: .venv\Scripts\python.exe main.py --demo
endlocal

