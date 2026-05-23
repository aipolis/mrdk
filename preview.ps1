# 本地预览网站（必须在 web 目录运行）
Set-Location $PSScriptRoot
Write-Host "明日当空网站预览: http://127.0.0.1:8888"
Write-Host "按 Ctrl+C 停止"
python -m http.server 8888
