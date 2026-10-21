@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Logpresso agent starting... (close this window to stop the server)
py -m streamlit run app.py
pause
