@echo off
echo Installing Python dependencies...
pip install fastapi uvicorn psycopg2-binary
echo.
echo Starting Alpha Move AI API on http://localhost:8000
echo.
cd backend
uvicorn main:app --reload --port 8000
