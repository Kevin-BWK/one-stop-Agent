# 一件事·一次办 —— 一键启动开发环境（后端 + 前端 H5 调试端）
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1            启动并打开浏览器
#   powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1 -NoOpen    只启动，不开浏览器
#   powershell -NoProfile -ExecutionPolicy Bypass -File dev.ps1 -Stop      停止前后端
#
# 说明：H5 仅用于调试；最终成品是 App（见 docs/07-前端交互设计.md）。

param(
  [switch]$Stop,
  [switch]$NoOpen,
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-Listener([int]$Port) {
  Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
}

function Stop-ServiceOnPort([int]$Port, [string]$Name) {
  $listener = Get-Listener $Port
  if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host ("  已停止 " + $Name + "（端口 " + $Port + "，PID " + $listener.OwningProcess + "）") -ForegroundColor Yellow
  }
  else {
    Write-Host ("  " + $Name + " 未在运行") -ForegroundColor DarkGray
  }
}

# 优先用 PATH 里的 Node；否则回退到 IDE 工具目录里已解压的 Node
function Resolve-NodeDir {
  $cmd = Get-Command node -ErrorAction SilentlyContinue
  if ($cmd) { return (Split-Path $cmd.Source -Parent) }

  $base = Join-Path $env:USERPROFILE '.workbuddy\binaries\node\versions'
  if (-not (Test-Path $base)) { return $null }

  foreach ($dir in (Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
    $candidates = @($dir.FullName)
    $candidates += (Get-ChildItem $dir.FullName -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($candidate in $candidates) {
      if (Test-Path (Join-Path $candidate 'node.exe')) { return $candidate }
    }
  }
  return $null
}

if ($Stop) {
  Write-Host '正在停止开发环境...' -ForegroundColor Cyan
  Stop-ServiceOnPort $FrontendPort '前端'
  Stop-ServiceOnPort $BackendPort '后端'
  exit 0
}

Write-Host '正在启动开发环境...' -ForegroundColor Cyan

# ---------- 后端：FastAPI ----------
if (Get-Listener $BackendPort) {
  Write-Host ("  后端已在运行（http://127.0.0.1:" + $BackendPort + "）") -ForegroundColor DarkGray
}
else {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python) {
    Write-Host '  找不到 python，请先安装 Python 3.10+' -ForegroundColor Red
    exit 1
  }
  $backendArgs = @('-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', "$BackendPort")
  Start-Process -FilePath 'python' -ArgumentList $backendArgs -WorkingDirectory $Root | Out-Null
  Write-Host ("  后端已启动（http://127.0.0.1:" + $BackendPort + "）") -ForegroundColor Green
}

# ---------- 前端：uni-app H5 ----------
if (Get-Listener $FrontendPort) {
  Write-Host ("  前端已在运行（http://127.0.0.1:" + $FrontendPort + "）") -ForegroundColor DarkGray
}
else {
  $nodeDir = Resolve-NodeDir
  if (-not $nodeDir) {
    Write-Host '  找不到 Node，请先安装 Node.js 18+（https://nodejs.org）后重试' -ForegroundColor Red
    exit 1
  }
  Write-Host ("  Node: " + $nodeDir) -ForegroundColor DarkGray

  $frontendDir = Join-Path $Root 'frontend'
  if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Host '  首次运行，正在安装前端依赖（约 1-2 分钟）...' -ForegroundColor Yellow
    Push-Location $frontendDir
    & (Join-Path $nodeDir 'npm.cmd') install --registry=https://registry.npmmirror.com --no-fund --no-audit
    Pop-Location
  }

  $inner = 'set "PATH=' + $nodeDir + ';%PATH%" && cd /d "' + $frontendDir + '" && npm run dev:h5'
  Start-Process -FilePath 'cmd' -ArgumentList '/k', $inner -WorkingDirectory $frontendDir | Out-Null
  Write-Host ("  前端已启动（http://127.0.0.1:" + $FrontendPort + "）") -ForegroundColor Green
}

# ---------- 等待前端就绪 ----------
$url = 'http://127.0.0.1:' + $FrontendPort + '/'
Write-Host '  等待前端编译...' -ForegroundColor DarkGray

$ready = $false
foreach ($i in 1..40) {
  Start-Sleep -Milliseconds 1500
  try {
    $resp = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
    if ($resp.StatusCode -eq 200) { $ready = $true; break }
  }
  catch { }
}

Write-Host ''
if ($ready) {
  Write-Host ('就绪：' + $url) -ForegroundColor Green
  Write-Host '提示：停止请执行  dev.ps1 -Stop，或直接关掉前端/后端那两个窗口。' -ForegroundColor DarkGray
  if (-not $NoOpen) { Start-Process $url }
}
else {
  Write-Host '等待超时：请看前端窗口的编译日志（首次编译会比较慢）。' -ForegroundColor Red
  exit 1
}
