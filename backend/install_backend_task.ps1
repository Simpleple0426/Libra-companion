param(
    [string]$TaskName = "LibraBackend"
)

$ErrorActionPreference = "Stop"
$backendDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $backendDirectory "start_backend.ps1"
$powerShellPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`"" `
    -WorkingDirectory $backendDirectory
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $currentUser)
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Description "Keeps the local Libra Companion backend available on port 8000." `
    -Force | Out-Null

Write-Output "Scheduled task '$TaskName' installed for $currentUser."
