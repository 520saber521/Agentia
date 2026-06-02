# AgentHub v2 一键启动脚本 (PowerShell)
# 启动 BFF + Web 开发服务器
#
# 用法:
#   .\scripts\dev.ps1           # 默认模式（BFF :8788 + Web :5173）
#   $env:AGENTHUB_BFF_PORT=8080; .\scripts\dev.ps1   # 自定义 BFF 端口

param(
  [int]$BffPort = 8788,
  [int]$WebPort = 5173,
  [switch]$NoWeb
)

$RootDir = Split-Path -Path $PSScriptRoot -Parent
$ServerDir = Join-Path $RootDir "server"
$WebDir = Join-Path $RootDir "web"

Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       AgentHub v2 · 开发模式            ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  BFF  : http://127.0.0.1:$BffPort"
Write-Host "  Web  : http://127.0.0.1:$WebPort"
Write-Host "  WS   : ws://127.0.0.1:$BffPort/ws"
Write-Host ""

# 验证依赖
$PythonOk = $null
try { $PythonOk = python --version } catch {}
if (-not $PythonOk) {
  Write-Error "Python 未安装或不在 PATH 中"
  exit 1
}

$NodeOk = $null
try { $NodeOk = node --version } catch {}
if (-not $NodeOk) {
  Write-Error "Node.js 未安装或不在 PATH 中"
  exit 1
}

# 安装 Python 依赖
Write-Host "→ 安装 Python 依赖..." -ForegroundColor Yellow
pip install -q -r (Join-Path $ServerDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
  Write-Error "Python 依赖安装失败"
  exit 1
}

# 安装 Node 依赖
Write-Host "→ 安装 Node 依赖..." -ForegroundColor Yellow
Push-Location $WebDir
npm install --silent 2>$null
Pop-Location

# 设置环境变量
$env:AGENTHUB_BFF_PORT = $BffPort

# 启动 BFF
Write-Host "→ 启动 BFF (端口 $BffPort)..." -ForegroundColor Yellow
$BffJob = Start-Job -ScriptBlock {
  param($Dir, $Port)
  Set-Location $Dir
  python dev_server.py --host 127.0.0.1 --port $Port --reload --log-level info
} -ArgumentList $ServerDir, $BffPort

# 等待 BFF 就绪
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BffPort/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) {
      $ready = $true
      break
    }
  } catch {}
  Start-Sleep -Milliseconds 500
}

if (-not $ready) {
  Write-Error "BFF 启动超时"
  Stop-Job $BffJob
  Remove-Job $BffJob
  exit 1
}
Write-Host "  ✓ BFF 已就绪" -ForegroundColor Green

if (-not $NoWeb) {
  # 启动 Web 开发服务器
  Write-Host "→ 启动 Web (端口 $WebPort)..." -ForegroundColor Yellow
  $WebJob = Start-Job -ScriptBlock {
    param($Dir)
    Set-Location $Dir
    npx vite --port 5173 --strictPort
  } -ArgumentList $WebDir

  Write-Host ""
  Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
  Write-Host "║   AgentHub v2 已启动!                    ║" -ForegroundColor Green
  Write-Host "║                                          ║" -ForegroundColor Green
  Write-Host "║   浏览器打开:                             ║" -ForegroundColor Green
  Write-Host "║   http://127.0.0.1:$WebPort              ║" -ForegroundColor Green
  Write-Host "║                                          ║" -ForegroundColor Green
  Write-Host "║   停止: 按 Ctrl+C 或 close-all.ps1       ║" -ForegroundColor Green
  Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
  Write-Host ""

  # 等待用户按 Ctrl+C
  try {
    while ($true) {
      Start-Sleep -Seconds 1
      # 检查 Jobs 是否还在运行
      $bffOk = (Get-Job $BffJob).State -eq "Running"
      $webOk = (Get-Job $WebJob).State -eq "Running"
      if (-not $bffOk -or -not $webOk) {
        Write-Host "! 检测到进程退出" -ForegroundColor Red
        break
      }
    }
  } finally {
    Write-Host "→ 正在停止服务..." -ForegroundColor Yellow
    Stop-Job $BffJob -ErrorAction SilentlyContinue
    Stop-Job $WebJob -ErrorAction SilentlyContinue
    Remove-Job $BffJob -ErrorAction SilentlyContinue
    Remove-Job $WebJob -ErrorAction SilentlyContinue
    Write-Host "  ✓ 已停止" -ForegroundColor Green
  }
} else {
  Write-Host ""
  Write-Host "BFF 已在 http://127.0.0.1:$BffPort 运行" -ForegroundColor Green
  Write-Host "按 Ctrl+C 停止" -ForegroundColor Yellow
  try {
    while ($true) { Start-Sleep -Seconds 1 }
  } finally {
    Stop-Job $BffJob -ErrorAction SilentlyContinue
    Remove-Job $BffJob -ErrorAction SilentlyContinue
  }
}
