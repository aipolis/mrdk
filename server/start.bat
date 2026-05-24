@echo off
cd /d %~dp0
pip install -r requirements.txt -q
set PORT=8000
python app.py
