[CmdletBinding()]
param(
    [string]$PythonPath,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5178,
    [switch]$Demo,
    [switch]$Check,
    [switch]$VerifyStartup
)

$ErrorActionPreference = 'Stop'
$backendDirectory = Join-Path $PSScriptRoot 'backend'
$frontendDirectory = Join-Path $PSScriptRoot 'frontend'
$backendProcess = $null
$frontendProcess = $null
$environmentNames = @('VITE_DATA_MODE', 'VITE_API_BASE', 'API_PROXY_TARGET', 'PYTHONUNBUFFERED')
$savedEnvironment = @{}
foreach ($variableName in $environmentNames) {
    $savedEnvironment[$variableName] = [Environment]::GetEnvironmentVariable($variableName, 'Process')
}

function Test-AvailablePort([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Server.ExclusiveAddressUse = $true
    try { $listener.Start() }
    catch { throw "Port $Port is already in use. Stop its service or specify another port." }
    finally { $listener.Stop() }
}

function Resolve-ServicePort([int]$PreferredPort, [bool]$Explicit, [int]$ExcludedPort = 0) {
    if ($Explicit) {
        Test-AvailablePort $PreferredPort
        return $PreferredPort
    }
    $lastPort = [Math]::Min(65535, $PreferredPort + 100)
    for ($candidatePort = $PreferredPort; $candidatePort -le $lastPort; $candidatePort++) {
        if ($candidatePort -eq $ExcludedPort) { continue }
        try { Test-AvailablePort $candidatePort }
        catch { continue }
        if ($candidatePort -ne $PreferredPort) {
            Write-Host "Default port $PreferredPort is unavailable. Using $candidatePort instead."
        }
        return $candidatePort
    }
    throw "No available port between $PreferredPort and $lastPort. Specify another port explicitly."
}

function Wait-Service([System.Diagnostics.Process]$Process, [string]$Url, [string]$Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) { throw "$Name exited. See logs in $runDirectory" }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within 120 seconds. See logs in $runDirectory"
}

function Stop-OwnedProcess([System.Diagnostics.Process]$Process) {
    if ($null -ne $Process -and -not $Process.HasExited) {
        try {
            $treeKill = $Process.GetType().GetMethod('Kill', [type[]]@([bool]))
            if ($null -ne $treeKill) {
                $Process.Kill($true)
            }
            else {
                $stopper = Start-Process -FilePath "$env:SystemRoot\System32\taskkill.exe" -ArgumentList @('/PID', "$($Process.Id)", '/T', '/F') -WindowStyle Hidden -PassThru
                if (-not $stopper.WaitForExit(10000)) {
                    $stopper.Kill()
                    throw 'Process cleanup timed out.'
                }
                if ($stopper.ExitCode -ne 0 -and -not $Process.HasExited) { throw 'Process cleanup failed.' }
            }
        }
        catch { Write-Warning "Could not stop owned process $($Process.Id): $($_.Exception.Message)" }
    }
}

try {
    if ($PSBoundParameters.ContainsKey('BackendPort') -and $PSBoundParameters.ContainsKey('FrontendPort') -and $BackendPort -eq $FrontendPort) { throw 'Frontend and backend ports must be different.' }
    if (-not $PythonPath) {
        $candidates = @(
            (Join-Path $backendDirectory '.venv\Scripts\python.exe'),
            (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
            (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe')
        )
        $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    }
    $PythonPath = (Get-Command $PythonPath -ErrorAction Stop).Source
    $nodePath = (Get-Command node.exe -ErrorAction Stop).Source
    $vitePath = Join-Path $frontendDirectory 'node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $vitePath)) {
        throw 'Frontend dependencies are missing. Run npm ci in the frontend directory first.'
    }
    & $PythonPath -c 'import fastapi, uvicorn, pydantic_settings, sqlalchemy, geoalchemy2, psycopg2, shapely, pyproj, httpx, requests, bcrypt, jwt, cryptography' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies are missing. Use the selected Python to install backend/requirements.txt.' }
    $reservedFrontendPort = if ($PSBoundParameters.ContainsKey('FrontendPort')) { $FrontendPort } else { 0 }
    $BackendPort = Resolve-ServicePort $BackendPort $PSBoundParameters.ContainsKey('BackendPort') $reservedFrontendPort
    $FrontendPort = Resolve-ServicePort $FrontendPort $PSBoundParameters.ContainsKey('FrontendPort') $BackendPort
    Write-Host "Python: $PythonPath"
    Write-Host "Preflight passed. Backend: $BackendPort; frontend: $FrontendPort."
    if ($Check) { return }

    $runDirectory = Join-Path $PSScriptRoot ('logs\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $PID)
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $env:VITE_DATA_MODE = if ($Demo) { 'demo' } else { 'api' }
    $env:VITE_API_BASE = '/api/v1'
    $env:API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
    $env:PYTHONUNBUFFERED = '1'

    Write-Host "Starting backend (existing startup initializes platform tables). Logs: $runDirectory"
    $backendProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") -WorkingDirectory $backendDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDirectory 'backend.stdout.log') -RedirectStandardError (Join-Path $runDirectory 'backend.stderr.log')
    Wait-Service $backendProcess "http://127.0.0.1:$BackendPort/health" 'Backend'

    $frontendProcess = Start-Process -FilePath $nodePath -ArgumentList @('"' + $vitePath + '"', '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort') -WorkingDirectory $frontendDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDirectory 'frontend.stdout.log') -RedirectStandardError (Join-Path $runDirectory 'frontend.stderr.log')
    Wait-Service $frontendProcess "http://127.0.0.1:$FrontendPort/" 'Frontend'
    Write-Host ''
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort/?mode=$env:VITE_DATA_MODE"
    Write-Host "API docs: http://127.0.0.1:$BackendPort/docs"
    Write-Host "Data mode: $env:VITE_DATA_MODE"
    if ($VerifyStartup) { Write-Host 'Startup verification passed. Stopping verification services.'; return }
    Write-Host 'Keep this window open. Press Ctrl+C to stop both services.'
    while ($true) {
        if ($backendProcess.HasExited -or $frontendProcess.HasExited) {
            throw "A service exited unexpectedly. See logs in $runDirectory"
        }
        Start-Sleep -Seconds 1
    }
}
catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-OwnedProcess $frontendProcess
    Stop-OwnedProcess $backendProcess
    foreach ($variableName in $environmentNames) {
        [Environment]::SetEnvironmentVariable($variableName, $savedEnvironment[$variableName], 'Process')
    }
}
