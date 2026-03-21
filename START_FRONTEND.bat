@echo off
echo Installing Node dependencies (first run takes a few minutes)...
cd frontend
npm install
echo.
echo Starting FinScope UI on http://localhost:3000
echo.
npm start
