# start_dev.ps1

Write-Host "Starting OneShot Development Environment..." -ForegroundColor Cyan

# Function to kill process on a port
function Kill-PortProcess {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connection) {
        $processId = $connection.OwningProcess
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Port $Port is in use by PID $processId ($($process.ProcessName)). Killing..." -ForegroundColor Yellow
            Stop-Process -Id $processId -Force
            Write-Host "Process killed." -ForegroundColor Green
        }
    }
}

# 1. Check/Free port 3000 (Frontend)
Kill-PortProcess -Port 3000
# 2. Check/Free port 8000 (Backend) - Good practice to clear this too
Kill-PortProcess -Port 8000

# 3. Start Backend
Write-Host "Launching Backend (Port 8000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {Write-Host 'Backend Server'; python -m uvicorn app.main:app --reload --port 8000}"

# 4. Start Frontend
Write-Host "Launching Frontend (Port 3000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {Write-Host 'Frontend (MentraApp)'; cd MentraApp; `$env:PORT=3000; bun run dev}"

# 5. Open User Terminal
Write-Host "Launching User Terminal..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& {Write-Host 'OneShot User Terminal'; Get-Location}"

Write-Host "Startup sequence complete." -ForegroundColor Cyan
