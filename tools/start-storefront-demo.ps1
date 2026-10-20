param([switch]$SkipInit)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir = Join-Path $projectRoot 'backend'
$pythonExe = Join-Path $backendDir '.venv/Scripts/python.exe'
$nodeExe = (Get-Command node -ErrorAction Stop).Source
$logDir = Join-Path $projectRoot '.superpowers/sdd/2026-10-19-storefront-first-order/logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Ensure-DemoDatabase {
    if (Get-NetTCPConnection -LocalPort 15432 -State Listen -ErrorAction SilentlyContinue) { return }
    $container = 'crossborder-erp-db-1'
    $state = & docker inspect --format '{{.State.Status}}' $container 2>$null
    if ($LASTEXITCODE -ne 0) { throw "数据库端口 15432 未就绪，且找不到容器 $container；请先启动 Docker Desktop 和项目数据库。" }
    if ($state.Trim() -ne 'running') {
        & docker start $container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "无法启动数据库容器 $container。" }
        Write-Host "已启动演示所需的数据库容器 $container。"
    }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $health = & docker inspect --format '{{.State.Health.Status}}' $container 2>$null
        if ($LASTEXITCODE -eq 0 -and $health.Trim() -eq 'healthy' -and
            (Get-NetTCPConnection -LocalPort 15432 -State Listen -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "数据库容器 $container 未在 30 秒内就绪，请检查 Docker 日志。"
}

Ensure-DemoDatabase

if (-not $SkipInit) {
    Push-Location $backendDir
    try { & $pythonExe -m app.storefront.demo init; if ($LASTEXITCODE -ne 0) { throw '演示数据库初始化失败' } }
    finally { Pop-Location }
}

function Start-DemoService($label, $port, $exe, $arguments, $directory) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) { Write-Host "端口 $port 已被占用；未重启或终止任何进程，请确认是 $label。"; return }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "$label-$stamp.out.log") -RedirectStandardError (Join-Path $logDir "$label-$stamp.err.log")
    Write-Host "$label 已启动进程 $($process.Id)，端口 $port；就绪状态请以页面或日志为准。"
}

Start-DemoService 'api' 18081 $pythonExe '-m app.storefront.demo serve' $backendDir
Start-DemoService 'storefront' 15174 $nodeExe 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15174 --strictPort' (Join-Path $projectRoot 'storefront')
$oldTarget = $env:VITE_API_TARGET
$oldCache = $env:VITE_CACHE_DIR
try {
    $env:VITE_API_TARGET = 'http://127.0.0.1:18081'
    $env:VITE_CACHE_DIR = Join-Path ([System.IO.Path]::GetTempPath()) 'zhijian-demo-erp-vite'
    Start-DemoService 'erp' 15175 $nodeExe 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15175 --strictPort' (Join-Path $projectRoot 'frontend')
} finally { $env:VITE_API_TARGET = $oldTarget; $env:VITE_CACHE_DIR = $oldCache }
Write-Host '顾客商城 http://127.0.0.1:15174/ ; 演示 ERP http://127.0.0.1:15175/storefront'
Write-Host '原 ERP 15173/18080 未停止；公司和商品均为演示资料，无真实交易。'
