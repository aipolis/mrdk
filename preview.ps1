# 本地预览：默认使用线上 API 的真实数据；仅调试后端时用 -LocalApi
param(
  [switch]$LocalApi
)

$webRoot = $PSScriptRoot
$apiPort = 8010

if ($LocalApi) {
  $serverRoot = Resolve-Path (Join-Path $webRoot '..\server')
  if (-not (Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "启动本地 API: http://127.0.0.1:$apiPort"
    $cacheDir = Join-Path $serverRoot '.cache'
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
    Start-Process -FilePath powershell `
      -ArgumentList '-NoProfile', '-Command', "`$env:PORT='$apiPort'; `$env:HOME_CACHE_FILE='$cacheDir\home_cache.json'; python app.py" `
      -WorkingDirectory $serverRoot `
      -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
      Start-Sleep -Seconds 1
      try {
        $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
          $ready = $true
          break
        }
      } catch {}
    }
    if (-not $ready) {
      throw '本地 API 启动超时，请检查 server 依赖与日志。'
    }
  }
  Write-Host "API: http://127.0.0.1:$apiPort (本地)"
  Write-Host "请在浏览器控制台执行: localStorage.setItem('mrdk_use_local_api','1') 后刷新"
} else {
  Write-Host "API: 线上生产环境 (真实数据)"
  Write-Host "如需调试本地 server: .\preview.ps1 -LocalApi"
}

Set-Location $webRoot
Write-Host "Web 预览: http://127.0.0.1:8890"
Write-Host "按 Ctrl+C 停止 Web 服务。"
python -m http.server 8890
