param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9.-]+$')]
    [string]$Domain,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedThread
)

$ErrorActionPreference = 'Stop'

# Run on the VPS, under the same Windows account running Caddy.
$caddyDirectory = 'C:\Caddy'
$caddyExecutable = Join-Path $caddyDirectory 'caddy.exe'
$configuration = Join-Path $caddyDirectory 'Caddyfile'
$keyFile = Join-Path $caddyDirectory 'libra-access-key.txt'
$connectionFile = Join-Path $caddyDirectory 'libra-app-address.txt'

if (-not (Test-Path -LiteralPath $caddyExecutable)) {
    throw 'C:\Caddy\caddy.exe was not found. Run this script on the VPS.'
}
if (-not (Test-Path -LiteralPath $configuration)) {
    throw 'The existing Caddyfile was not found.'
}
$backend = Invoke-RestMethod 'http://127.0.0.1:8000/' -TimeoutSec 15
if ($backend.thread_id -ne $ExpectedThread) {
    throw 'The backend is not using the expected migrated thread. Configuration was not changed.'
}

if (Test-Path -LiteralPath $keyFile) {
    $accessKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
} else {
    $randomBytes = New-Object byte[] 32
    $randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $randomGenerator.GetBytes($randomBytes) } finally { $randomGenerator.Dispose() }
    $accessKey = ([BitConverter]::ToString($randomBytes)).Replace('-', '').ToLowerInvariant()
    [IO.File]::WriteAllText($keyFile, $accessKey, [Text.UTF8Encoding]::new($false))
}
if ($accessKey -notmatch '^[0-9a-f]{64}$') {
    throw 'The saved access key is invalid. Configuration was not changed.'
}

$candidate = Join-Path $caddyDirectory 'Caddyfile.libra-candidate'
$newConfiguration = @"
$Domain {
    header >Referrer-Policy "no-referrer"
    header >Cache-Control "private, no-store"

    handle_path /connect/$accessKey/* {
        reverse_proxy 127.0.0.1:8000
    }

    handle {
        respond "Unauthorized" 401
    }
}
"@
[IO.File]::WriteAllText($candidate, $newConfiguration, [Text.UTF8Encoding]::new($false))
& $caddyExecutable validate --config $candidate --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy validation failed. The running configuration was not changed.' }

$backup = Join-Path $caddyDirectory ('Caddyfile.before-proxy-' + [Guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath $configuration -Destination $backup
Copy-Item -LiteralPath $candidate -Destination $configuration -Force
& $caddyExecutable reload --config $configuration --adapter caddyfile
if ($LASTEXITCODE -ne 0) {
    Copy-Item -LiteralPath $backup -Destination $configuration -Force
    throw 'Caddy reload failed. The previous configuration file was restored. Keep the Caddy window open.'
}

$address = "https://$Domain/connect/$accessKey"
try {
    $publicBackend = Invoke-RestMethod "$address/" -TimeoutSec 30
    if ($publicBackend.thread_id -ne $ExpectedThread) { throw 'Public thread verification failed.' }
    $unauthorizedStatus = 0
    try {
        $response = Invoke-WebRequest "https://$Domain/" -UseBasicParsing -TimeoutSec 15
        $unauthorizedStatus = [int]$response.StatusCode
    } catch {
        if ($null -eq $_.Exception.Response) { throw }
        $unauthorizedStatus = [int]$_.Exception.Response.StatusCode
    }
    if ($unauthorizedStatus -ne 401) { throw 'Requests without a key are not being rejected.' }
} catch {
    Copy-Item -LiteralPath $backup -Destination $configuration -Force
    & $caddyExecutable reload --config $configuration --adapter caddyfile
    throw 'Public verification failed. The previous configuration was restored. Check the backend and Caddy windows.'
}

[IO.File]::WriteAllText($connectionFile, $address, [Text.UTF8Encoding]::new($false))
Write-Host 'HTTPS proxy verified. The original Codex thread is unchanged.'
Write-Host 'Your private app address is in C:\Caddy\libra-app-address.txt.'
Write-Host 'Treat that address as a password. Do not share screenshots of it.'
Write-Host 'Keep both the backend and Caddy windows running for now.'
Start-Process -FilePath 'notepad.exe' -ArgumentList $connectionFile
