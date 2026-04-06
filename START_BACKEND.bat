@echo off
echo Installing Python dependencies...
pip install fastapi uvicorn psycopg2-binary
echo.
echo Starting FinScope API on http://localhost:8000
echo.
cd backend
uvicorn main:app --reload --port 8000
