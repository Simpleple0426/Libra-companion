param(
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 180,
    [string]$RecoveryJobId = "",
    [switch]$RetireSchedule,
    [switch]$RetireNeeds
)

$ErrorActionPreference = "Stop"
$taskName = "LibraBackend"
$Port = 8000
$startScript = Join-Path $PSScriptRoot "start_backend.ps1"
$task = Get-ScheduledTask -TaskName $taskName
if (-not ($task.Actions | Where-Object { $_.Arguments -like "*`"$startScript`"*" })) {
    throw "Scheduled task does not point to this project's start script."
}
$allProcesses = @(Get-CimInstance Win32_Process)
$launchers = @($allProcesses | Where-Object {
    $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*-File*`"$startScript`"*"
})
$supervisors = @($allProcesses | Where-Object {
    $_.Name -eq 'python.exe' -and $_.ParentProcessId -in $launchers.ProcessId -and
    $_.CommandLine -match '-m\s+scripts\.run_server\b'
})
$serverParents = @($launchers.ProcessId) + @($supervisors.ProcessId)
$servers = @($allProcesses | Where-Object {
    $_.Name -eq 'python.exe' -and $_.ParentProcessId -in $serverParents -and
    $_.CommandLine -match '\buvicorn\s+main:app\b'
})

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    if ($listener.OwningProcess -notin $servers.ProcessId) {
        throw "Port $Port is not owned by this project's scheduled task; refusing to stop it."
    }
}

# Stop the supervising task first so its restart policy cannot race this restart.
Stop-ScheduledTask -TaskName $taskName
foreach ($serverProcess in @($servers) + @($supervisors)) {
    $stoppingProcess = Get-Process -Id $serverProcess.ProcessId -ErrorAction SilentlyContinue
    if ($stoppingProcess) {
        Stop-Process -Id $serverProcess.ProcessId -Force
        if (-not $stoppingProcess.WaitForExit(15000)) {
            throw "Project process did not fully exit; refusing offline migration."
        }
    }
}

if ($RecoveryJobId -or $RetireSchedule -or $RetireNeeds) {
    Push-Location -LiteralPath $PSScriptRoot
    try {
        if ($RetireNeeds) { & python -m scripts.retire_life_needs --apply }
        elseif ($RetireSchedule) { & python -m scripts.retire_schedule_data --apply }
        else { & python -m scripts.recover_life_job --job $RecoveryJobId }
        if ($LASTEXITCODE -ne 0) { throw "Scheduler recovery failed; prior records preserved." }
    } finally {
        Pop-Location
        Start-ScheduledTask -TaskName $taskName
    }
} else {
    Start-ScheduledTask -TaskName $taskName
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready = $false
$lastFailure = "No response received"
do {
    try {
        $request = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/health")
        $request.Proxy = $null
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $response = $request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try { $health = $reader.ReadToEnd() | ConvertFrom-Json }
            finally { $reader.Dispose() }
            $ready = ($response.StatusCode -eq 200 -and $health.healthy -eq $true)
            if (-not $ready) { $lastFailure = "Health endpoint did not report healthy=true" }
        } finally { $response.Dispose() }
    } catch {
        $lastFailure = $_.Exception.Message
    }
    if (-not $ready) { Start-Sleep -Milliseconds 500 }
} until ($ready -or (Get-Date) -ge $deadline)

if (-not $ready) {
    throw "Libra backend did not become healthy on port $Port. $lastFailure"
}

Write-Output "Libra backend is healthy on port $Port."
