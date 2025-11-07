# CouchDB JWT Proxy - PowerShell runner script
# Usage: .\run.ps1 [command]

param(
    [string]$Command = "help"
)

function Show-Help {
    Write-Host "CouchDB JWT Proxy - uv commands" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Setup & Installation:" -ForegroundColor Green
    Write-Host "  .\run.ps1 install       Install dependencies"
    Write-Host "  .\run.ps1 dev          Install with dev dependencies"
    Write-Host ""
    Write-Host "Running:" -ForegroundColor Green
    Write-Host "  .\run.ps1 run          Run the proxy server"
    Write-Host "  .\run.ps1 dev-run      Run with auto-reload"
    Write-Host ""
    Write-Host "Testing:" -ForegroundColor Green
    Write-Host "  .\run.ps1 test         Run all tests"
    Write-Host "  .\run.ps1 test-cov     Run tests with coverage report"
    Write-Host ""
    Write-Host "Utilities:" -ForegroundColor Green
    Write-Host "  .\run.ps1 clean        Remove cache and build files"
    Write-Host "  .\run.ps1 env-setup    Create .env file from .env.example"
    Write-Host "  .\run.ps1 help         Show this help message"
    Write-Host ""
}

function Install {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    uv sync
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "✗ Installation failed" -ForegroundColor Red
        exit 1
    }
}

function Dev {
    Write-Host "Installing dependencies with dev extras..." -ForegroundColor Yellow
    uv sync --all-extras
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Dev dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "✗ Installation failed" -ForegroundColor Red
        exit 1
    }
}

function Run {
    Write-Host "Starting CouchDB JWT Proxy..." -ForegroundColor Yellow
    $env:PYTHONPATH = "src"
    uv run python -m couchdb_jwt_proxy.main
}

function DevRun {
    Write-Host "Starting proxy with auto-reload..." -ForegroundColor Yellow
    $env:PYTHONPATH = "src"
    uv run uvicorn couchdb_jwt_proxy.main:app --reload --port 5985
}

function Test {
    Write-Host "Running tests..." -ForegroundColor Yellow
    uv run pytest tests -v
}

function TestCov {
    Write-Host "Running tests with coverage..." -ForegroundColor Yellow
    uv run pytest tests -v --cov=couchdb_jwt_proxy --cov-report=html --cov-report=term-missing
    Write-Host ""
    Write-Host "✓ Coverage report: htmlcov/index.html" -ForegroundColor Green
}

function Clean {
    Write-Host "Cleaning up..." -ForegroundColor Yellow

    $patterns = @(
        "__pycache__",
        ".pytest_cache",
        "htmlcov",
        ".coverage",
        ".uv"
    )

    foreach ($pattern in $patterns) {
        Get-ChildItem -Path . -Name $pattern -ErrorAction SilentlyContinue -Recurse | ForEach-Object {
            Remove-Item -Path $_ -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "✓ Cleanup complete" -ForegroundColor Green
}

function EnvSetup {
    if (Test-Path ".env") {
        Write-Host ".env file already exists" -ForegroundColor Yellow
    } else {
        Copy-Item ".env.example" ".env"
        Write-Host "✓ .env file created. Please update with your settings." -ForegroundColor Green
    }
}

# Execute command
switch ($Command.ToLower()) {
    "help" { Show-Help }
    "install" { Install }
    "dev" { Dev }
    "run" { Run }
    "dev-run" { DevRun }
    "test" { Test }
    "test-cov" { TestCov }
    "clean" { Clean }
    "env-setup" { EnvSetup }
    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Write-Host ""
        Show-Help
        exit 1
    }
}
