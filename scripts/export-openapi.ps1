$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    throw "Create .venv or apps/api/.venv and install apps/api[dev] first."
}
& $python (Join-Path $repoRoot "apps\api\scripts\export_openapi.py")
Push-Location $repoRoot
try { npm run generate:api-client } finally { Pop-Location }
