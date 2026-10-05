$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    uv run --no-sync python manage.py runserver
}
finally {
    Pop-Location
}
