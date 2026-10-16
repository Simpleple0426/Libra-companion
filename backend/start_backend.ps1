param(
    [int]$Port = 8000,
    [switch]$TraceImports
)

$ErrorActionPreference = "Stop"
$backendDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDirectory = Join-Path (Split-Path -Parent $backendDirectory) "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$runStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$bootstrapLog = Join-Path $logDirectory "backend-$runStamp.bootstrap.log"

try {

$pythonPath = Join-Path $backendDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
Set-Location -LiteralPath $backendDirectory
$serverArguments = @("-u", "-m", "scripts.run_server", "--port", $Port)
if ($TraceImports) { $serverArguments += "--trace-imports" }

# Uvicorn writes directly to files, so task readiness never depends on
# PowerShell draining redirected stdout/stderr pipes.
& $pythonPath @serverArguments
$serverExitCode = $LASTEXITCODE
exit $(if ($serverExitCode -eq 0) { 1 } else { $serverExitCode })
} catch {
    "$(Get-Date -Format o) $($_ | Out-String)" | Out-File -LiteralPath $bootstrapLog -Append -Encoding utf8
    throw
}
