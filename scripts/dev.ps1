# Windows equivalent of the Makefile (no `make` needed). Run from the repository root:
#   .\scripts\dev.ps1 install | test | test-golden | test-security | demo | evidence | api | up
# Uses .venv\ (Python 3.12) when it exists; `install` creates it.
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "test", "test-golden", "test-security", "demo", "evidence", "api", "up")]
    [string]$Task = "test"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv\Scripts\python.exe"
$Backend = Join-Path $Root "backend"

function Invoke-Py([string[]]$PyArgs, [hashtable]$Env = @{}) {
    $saved = @{}
    foreach ($key in $Env.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key)
        [Environment]::SetEnvironmentVariable($key, $Env[$key])
    }
    Push-Location $Backend
    try {
        & $Venv @PyArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
        foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key]) }
    }
}

$Demo = @{ NL_CLOCK = "fixed"; NL_IDS = "sequential"; PYTHONPATH = "src" }

switch ($Task) {
    "install" {
        if (-not (Test-Path $Venv)) { & py -3.12 -m venv (Join-Path $Root ".venv") }
        & $Venv -m pip install -e "$Backend[api,dev,pdf]"
    }
    "test" { Invoke-Py @("-m", "pytest") }
    "test-golden" { Invoke-Py @("-m", "pytest", "-m", "golden", "-v") }
    "test-security" { Invoke-Py @("-m", "pytest", "-m", "security", "-v") }
    "demo" { Invoke-Py @("-m", "neural_ledger.bootstrap.cli", "demo") $Demo }
    "evidence" {
        Invoke-Py @("-m", "neural_ledger.bootstrap.cli", "demo-and-export", "--out", "../evidence/sandbox-logs/audit.jsonl") $Demo
        Invoke-Py @("-m", "pytest", "--junitxml=../evidence/test-results/junit.xml")
    }
    "api" { Invoke-Py @("-m", "uvicorn", "neural_ledger.bootstrap.asgi:app", "--reload", "--port", "8000") @{ PYTHONPATH = "src" } }
    "up" {
        Push-Location $Root
        try { docker compose up --build } finally { Pop-Location }
    }
}
