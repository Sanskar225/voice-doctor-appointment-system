# Launch both the Pipecat FastAPI backend and the React Vite dashboard
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Write-Host "No .env file found. Copy .env.example to .env and add ELEVENLABS_API_KEY and GEMINI_API_KEY." -ForegroundColor Yellow
}

Write-Host "Starting Aurelia Health backend on http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\backend'; .\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host "Starting Aurelia Health dashboard on http://localhost:5173 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; npm run dev"

Write-Host "Open http://localhost:5173 in your browser." -ForegroundColor Green
