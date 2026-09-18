$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create .venv and install apps/api[dev] first." }
Push-Location (Join-Path $repoRoot "apps\api")
try {
  & $python -c "import json; from app.main import app; open('openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2))"
} finally {
  Pop-Location
}
Push-Location $repoRoot
try { npm run generate:api-client } finally { Pop-Location }
