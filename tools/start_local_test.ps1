$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$testDirectory = Join-Path $projectDirectory '.test-local'
if (-not (Test-Path -LiteralPath (Join-Path $testDirectory 'setup-report.json'))) {
    throw 'The isolated test setup has not completed.'
}
$env:LIBRA_CONFIG_DIR = Join-Path $testDirectory 'config'
$env:LIBRA_ENV_FILE = Join-Path $env:LIBRA_CONFIG_DIR '.env'
$env:LIBRA_RUNTIME_DIR = Join-Path $testDirectory 'data'
$env:LIBRA_CODEX_HOME = Join-Path $testDirectory 'codex'
$env:CODEX_HOME = $env:LIBRA_CODEX_HOME
$env:LIBRA_LOG_DIR = Join-Path $testDirectory 'logs'
$env:LIBRA_BACKUP_DIR = Join-Path $testDirectory 'backups'
$env:LIBRA_CACHE_DIR = Join-Path $projectDirectory 'cache'
$backendDirectory = Join-Path $projectDirectory 'backend'
Set-Location -LiteralPath $backendDirectory
$pythonPath = (Get-Command python -ErrorAction Stop).Source
& $pythonPath -m uvicorn main:app --host 127.0.0.1 --port 8001 --loop app.server_loop:create_loop --no-access-log
exit $LASTEXITCODE
