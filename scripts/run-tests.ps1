# Run all tests (PowerShell equivalent of run-tests.sh)
$ErrorActionPreference = "Stop"

$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-Host "Running tests..." -ForegroundColor Yellow

& $python -c "import pytest" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Running tests with pytest..."
    & $python -m pytest tests/ -v
} else {
    Write-Host "Running tests with unittest..."
    & $python -m unittest discover -s tests -v
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "All tests passed" -ForegroundColor Green
