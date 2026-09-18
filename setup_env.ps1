<#
.SYNOPSIS
    Heat Environment Platform - 快速环境搭建脚本 (PowerShell)
.DESCRIPTION
    在新设备上自动创建 Python 虚拟环境、安装后端与前端依赖、准备环境配置文件。
.EXAMPLE
    .\setup_env.ps1
    .\setup_env.ps1 -InitDb
#>
[CmdletBinding()]
param(
    [switch]$InitDb,
    [string]$DatabaseUrl
)

$ErrorActionPreference = 'Stop'
$rootDir = $PSScriptRoot
$backendDir = Join-Path $rootDir 'backend'
$frontendDir = Join-Path $rootDir 'frontend'

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  热环境可视分析平台 (Heat Environment Platform)" -ForegroundColor Cyan
Write-Host "  一键环境搭建与依赖准备脚本" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

# 1. 检查基础环境 (Python & Node.js)
Write-Host "`n[1/5] 检查系统基础环境..." -ForegroundColor Yellow
try {
    $pythonCmd = (Get-Command python.exe -ErrorAction Stop).Source
    $pyVersion = (& python.exe --version 2>&1)
    Write-Host "  Python: $pyVersion ($pythonCmd)" -ForegroundColor Green
} catch {
    throw "未找到 python.exe。请先安装 Python 3.10+ 并勾选 'Add Python to PATH'。"
}

try {
    $nodeCmd = (Get-Command node.exe -ErrorAction Stop).Source
    $nodeVersion = (& node.exe --version 2>&1)
    $npmVersion = (& npm.cmd --version 2>&1)
    Write-Host "  Node.js: $nodeVersion ($nodeCmd)" -ForegroundColor Green
    Write-Host "  npm: v$npmVersion" -ForegroundColor Green
} catch {
    throw "未找到 node.exe 或 npm。请先安装 Node.js (推荐 v18 或 v20 LTS)。"
}

# 2. 创建并配置 Python 虚拟环境
Write-Host "`n[2/5] 配置 Python 虚拟环境..." -ForegroundColor Yellow
$venvDir = Join-Path $rootDir '.venv'
if (-not (Test-Path $venvDir)) {
    Write-Host "  正在创建虚拟环境 $venvDir ..."
    & python.exe -m venv $venvDir
}
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    # 针对 Linux/macOS 软兼容路径
    $venvPython = Join-Path $venvDir 'bin/python'
}
Write-Host "  使用虚拟环境解释器: $venvPython" -ForegroundColor Green

Write-Host "  正在更新 pip 并安装后端依赖 (requirements.txt)..."
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r (Join-Path $backendDir 'requirements.txt')
Write-Host "  后端依赖安装完成。" -ForegroundColor Green

# 3. 安装前端依赖
Write-Host "`n[3/5] 安装前端依赖 (npm install)..." -ForegroundColor Yellow
Push-Location $frontendDir
try {
    & npm.cmd install
    Write-Host "  前端依赖安装完成。" -ForegroundColor Green
} finally {
    Pop-Location
}

# 4. 初始化配置文件 (.env)
Write-Host "`n[4/5] 检查环境配置文件..." -ForegroundColor Yellow
$backendEnv = Join-Path $backendDir '.env'
$backendEnvEx = Join-Path $backendDir '.env.example'
if (-not (Test-Path $backendEnv) -and (Test-Path $backendEnvEx)) {
    Copy-Item $backendEnvEx $backendEnv
    Write-Host "  已从 .env.example 创建 backend/.env" -ForegroundColor Green
} else {
    Write-Host "  backend/.env 已存在。" -ForegroundColor Gray
}

$frontendEnv = Join-Path $frontendDir '.env'
$frontendEnvEx = Join-Path $frontendDir '.env.example'
if (-not (Test-Path $frontendEnv) -and (Test-Path $frontendEnvEx)) {
    Copy-Item $frontendEnvEx $frontendEnv
    Write-Host "  已从 .env.example 创建 frontend/.env" -ForegroundColor Green
} else {
    Write-Host "  frontend/.env 已存在。" -ForegroundColor Gray
}

# 5. 可选：数据库初始化与数据导入
if ($InitDb) {
    Write-Host "`n[5/5] 执行数据库初始化与数据导入..." -ForegroundColor Yellow
    $initScript = Join-Path $rootDir 'scripts\init_database.py'
    $initArgs = @($initScript)
    if ($DatabaseUrl) {
        $initArgs += @('--db-url', $DatabaseUrl)
    }
    & $venvPython @initArgs
} else {
    Write-Host "`n[5/5] 数据库准备提示：" -ForegroundColor Yellow
    Write-Host "  若需要立即初始化 PostgreSQL/PostGIS 数据库并导入上海核心区数据包："
    Write-Host "  请运行: & .\.venv\Scripts\python.exe scripts\init_database.py" -ForegroundColor Cyan
    Write-Host "  （或者在运行本脚本时加上 -InitDb 参数）"
}

Write-Host "`n======================================================" -ForegroundColor Green
Write-Host "  环境搭建与准备已全部完成！" -ForegroundColor Green
Write-Host "  启动平台只需运行: .\start.bat" -ForegroundColor Cyan
Write-Host "  仅体验纯前端演示模式: .\start.ps1 -Demo" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Green
