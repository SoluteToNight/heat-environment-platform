[CmdletBinding()]
param(
    [string]$PythonPath,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5178,
    [switch]$Demo,
    [switch]$NoReload,
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
        if ($Process.HasExited) { throw "$Name 进程已意外退出，请查看对应独立 pwsh 窗口中的报错输出。" }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name 在 120 秒内未就绪，请检查对应独立 pwsh 窗口中的启动状态。"
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

    $pwshCmd = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if (-not $pwshCmd) {
        $pwshCmd = Get-Command powershell.exe -ErrorAction Stop
    }
    $pwshPath = $pwshCmd.Source
    $dataMode = if ($Demo) { 'demo' } else { 'api' }
    # 后端代码热重载：uvicorn --reload 仅监视 backend/app 下的 *.py；未安装 watchfiles 时自动回退为轮询
    $reloadArgs = if ($NoReload) { '' } else { ' --reload --reload-dir app' }
    $reloadLabel = if ($NoReload) { '已关闭' } else { '已启用 (backend/app)' }

    $backendScript = @"
`$host.UI.RawUI.WindowTitle = '热环境平台 - 后端服务 (端口: $BackendPort)'
Set-Location -LiteralPath '$backendDirectory'
`$env:PYTHONUNBUFFERED = '1'
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '  热环境平台 - 后端服务 (FastAPI / Uvicorn)' -ForegroundColor Cyan
Write-Host '  运行目录: $backendDirectory' -ForegroundColor DarkGray
Write-Host '  监听端口: 127.0.0.1:$BackendPort' -ForegroundColor DarkGray
Write-Host '  代码热重载: $reloadLabel' -ForegroundColor DarkGray
Write-Host '==================================================' -ForegroundColor Cyan
& '$PythonPath' -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort$reloadArgs
"@

    $frontendScript = @"
`$host.UI.RawUI.WindowTitle = '热环境平台 - 前端服务 (端口: $FrontendPort)'
Set-Location -LiteralPath '$frontendDirectory'
`$env:VITE_DATA_MODE = '$dataMode'
`$env:VITE_API_BASE = '/api/v1'
`$env:API_PROXY_TARGET = 'http://127.0.0.1:$BackendPort'
Write-Host '==================================================' -ForegroundColor Green
Write-Host '  热环境平台 - 前端服务 (Vite / Vue 3)' -ForegroundColor Green
Write-Host '  运行目录: $frontendDirectory' -ForegroundColor DarkGray
Write-Host '  本地访问: http://127.0.0.1:$FrontendPort/?mode=$dataMode' -ForegroundColor DarkGray
Write-Host '==================================================' -ForegroundColor Green
& '$nodePath' '$vitePath' --host 127.0.0.1 --port $FrontendPort --strictPort
"@

    Write-Host "正在拉起独立 pwsh 会话启动后端服务 (端口: $BackendPort)..."
    $backendProcess = Start-Process -FilePath $pwshPath -ArgumentList @('-NoExit', '-Command', $backendScript) -WorkingDirectory $backendDirectory -PassThru

    Write-Host "正在拉起独立 pwsh 会话启动前端服务 (端口: $FrontendPort)..."
    $frontendProcess = Start-Process -FilePath $pwshPath -ArgumentList @('-NoExit', '-Command', $frontendScript) -WorkingDirectory $frontendDirectory -PassThru

    Write-Host "等待服务启动就绪..."
    Wait-Service $backendProcess "http://127.0.0.1:$BackendPort/health" 'Backend'
    Wait-Service $frontendProcess "http://127.0.0.1:$FrontendPort/" 'Frontend'

    Write-Host ''
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "前后端服务已在两个独立 pwsh 窗口中成功运行：" -ForegroundColor Green
    Write-Host "  - 前端界面: http://127.0.0.1:$FrontendPort/?mode=$dataMode" -ForegroundColor Cyan
    Write-Host "  - API 文档: http://127.0.0.1:$BackendPort/docs" -ForegroundColor Cyan
    Write-Host "  - 数据模式: $dataMode" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "提示: 前后端窗口各自独立运行，可在各自窗口查看实时日志，按 Ctrl+C 独立关闭或重启。"

    if ($VerifyStartup) {
        Write-Host 'Startup verification passed. Stopping verification services.'
        return
    }

    # 启动成功且非验证模式，解除托管，保留两个独立 pwsh 窗口长期运行
    $backendProcess = $null
    $frontendProcess = $null
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
