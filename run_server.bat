@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m uvicorn main:app --reload --env-file .env