# 打包 server 目录为云托管 zip（文件在 zip 根目录，不要 server 子文件夹）
$serverDir = $PSScriptRoot
$zipPath = Join-Path (Split-Path $serverDir -Parent) "mingri-api.zip"

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

$files = @(
    "Dockerfile", "requirements.txt", "app.py", "config.py",
    "fetcher.py", "home_cache.py", "home_archive.py", "db_store.py",
    "daily_sections.py", "scheduler.py", "update_schedule.py",
    "history_store.py", "history_sync.py", "intraday.py",
    "sentiment.py", "subscribe_msg.py", "user_store.py", "wechat_http.py", "wxacode.py", "ocr.py", ".dockerignore"
)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
foreach ($f in $files) {
    $full = Join-Path $serverDir $f
    if (Test-Path $full) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $full, $f) | Out-Null
        Write-Host "  + $f"
    }
}
$zip.Dispose()
Write-Host ""
Write-Host "已生成: $zipPath"
Write-Host "上传到云托管，Dockerfile 路径填: Dockerfile"
