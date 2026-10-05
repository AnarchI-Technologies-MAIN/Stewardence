$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    uv run --no-sync python scripts/verify_rls.py --cov --cov-report=term-missing
}
finally {
    Pop-Location
}
