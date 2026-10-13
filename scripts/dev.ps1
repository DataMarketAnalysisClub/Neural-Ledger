# Windows equivalent of the Makefile (no `make` needed). Run from the repository root:
#   .\scripts\dev.ps1 install | test | test-all | test-property | test-golden | test-security | demo | demo-ledger | ledgers | backtest | evidence | api | up
# Uses .venv\ (Python 3.12) when it exists; `install` creates it.
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "test", "test-all", "test-property", "test-golden", "test-security", "demo", "demo-ledger", "ledgers", "backtest", "evidence", "api", "up")]
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
        & $Venv -m pip install -e "$Backend[api,dev,pdf,ml]"
    }
    "test" { Invoke-Py @("-m", "pytest") }
    "test-all" { Invoke-Py @("-m", "pytest", "-o", "addopts=-q") }  # full suite; PowerShell 5.1 drops an empty -m ""
    "test-property" { Invoke-Py @("-m", "pytest", "-m", "property") }
    "test-golden" { Invoke-Py @("-m", "pytest", "-m", "golden", "-v") }
    "test-security" { Invoke-Py @("-m", "pytest", "-m", "security", "-v") }
    "demo" { Invoke-Py @("-m", "neural_ledger.bootstrap.cli", "demo") $Demo }
    "demo-ledger" { Invoke-Py @("-m", "neural_ledger.bootstrap.cli", "demo") ($Demo + @{ NL_MODEL_SOURCE = "ledger" }) }
    "ledgers" { Invoke-Py @("-m", "tests.fixtures.ledger_generator", "--out", "../data/ledgers") @{ PYTHONPATH = "src;." } }
    "backtest" { Invoke-Py @("-m", "tests.backtest.run", "--seeds", "100", "--out", "../evidence/backtest/synthetic_backtest.json") @{ PYTHONPATH = "src;." } }
    "evidence" {
        Invoke-Py @("-m", "neural_ledger.bootstrap.cli", "demo-and-export", "--out", "../evidence/sandbox-logs/audit.jsonl") $Demo
        Invoke-Py @("-m", "pytest", "-o", "addopts=-q", "--junitxml=../evidence/test-results/junit.xml")
    }
    "api" { Invoke-Py @("-m", "uvicorn", "neural_ledger.bootstrap.asgi:app", "--reload", "--port", "8000") @{ PYTHONPATH = "src" } }
    "up" {
        Push-Location $Root
        try { docker compose up --build } finally { Pop-Location }
    }
}
