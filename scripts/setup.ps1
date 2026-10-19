# ==============================================================================
# Central Annotation Platform - Setup & Client Check Script (Windows / PowerShell)
# ==============================================================================
[CmdletBinding()]
param()

Write-Host "=== [1/4] Checking Windows Client Prerequisites ===" -ForegroundColor Cyan

# Check Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCmd) {
    Write-Warning "Python 3 is not found in PATH. Please install Python 3.10+ from https://www.python.org/"
} else {
    $pyVer = python --version
    Write-Host "Python detected: $pyVer" -ForegroundColor Green
}

# Check Docker / Docker Desktop
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCmd) {
    Write-Host "`n[NOTICE] Docker is not installed or not in PATH." -ForegroundColor Yellow
    Write-Host "To run the central server platform on Windows, please install Docker Desktop:" -ForegroundColor Yellow
    Write-Host "1. Download Docker Desktop from: https://www.docker.com/products/docker-desktop/"
    Write-Host "2. Enable WSL2 backend during installation."
    Write-Host "3. Start Docker Desktop and ensure the engine is running before starting the server.`n"
} else {
    $dockerVer = docker --version
    Write-Host "Docker detected: $dockerVer" -ForegroundColor Green
}

# Check Rclone (for local testing/client)
$rcloneCmd = Get-Command rclone -ErrorAction SilentlyContinue
if ($null -eq $rcloneCmd) {
    Write-Host "Rclone is not found in PATH (optional for client agent, required for direct Rclone syncing)." -ForegroundColor Yellow
} else {
    Write-Host "Rclone detected: $(rclone --version | Select-Object -First 1)" -ForegroundColor Green
}

Write-Host "`n=== [2/4] Client Configuration & Setup Instructions ===" -ForegroundColor Cyan
Write-Host "To run the Annotator Desktop Agent on Windows:"
Write-Host "1. Create a virtual environment:"
Write-Host "   python -m venv .venv"
Write-Host "2. Activate virtual environment:"
Write-Host "   .venv\Scripts\Activate.ps1"
Write-Host "3. Install agent dependencies:"
Write-Host "   pip install -r requirements.txt"
Write-Host "4. Launch Annotator Agent CLI / GUI:"
Write-Host "   python -m annotator_agent.agent --server-url http://<SERVER_HOST>:8000"

Write-Host "`n=== [3/4] Server-Side Bootstrap on Windows (via Docker Desktop) ===" -ForegroundColor Cyan
Write-Host "If running the central server on this machine using Docker Desktop:"
Write-Host "1. Ensure .env exists (copy from .env.example if absent)."
Write-Host "2. Generate random passwords for APP_SECRET_KEY and POSTGRES_PASSWORD."
Write-Host "3. Run: docker compose up -d"
Write-Host "4. Run: docker compose run --rm migrate"
Write-Host "5. Create initial admin: docker compose exec controller python -m controller.app.cli create-admin"

Write-Host "`nDone." -ForegroundColor Green

