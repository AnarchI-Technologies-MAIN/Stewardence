$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .
}
finally {
    Pop-Location
}
