# 语录字体子集生成（需 pip install fonttools）
# 用法: .\tools\subset-quote-font.ps1 [-Font wenkai|zcool|smiley|all]

param(
  [ValidateSet('wenkai', 'zcool', 'smiley', 'all')]
  [string]$Font = 'all'
)

$root = Split-Path -Parent $PSScriptRoot
$chars = node -e "const { getQuoteCharset } = require('./utils/theme'); process.stdout.write(getQuoteCharset())"
if (-not $chars) { Write-Host '无法读取语录字符集'; exit 1 }

$jobs = @{
  wenkai = @{
    full = 'https://github.com/lxgw/LxgwWenKai/releases/download/v1.501/LXGWWenKai-Regular.ttf'
    fullPath = Join-Path $root 'assets\fonts\_wenkai-full.ttf'
    out = Join-Path $root 'assets\fonts\quote-wenkai-subset.ttf'
  }
  zcool = @{
    full = 'https://cdn.jsdelivr.net/gh/googlefonts/zcool-kuaile@main/fonts/ttf/ZCOOLKuaiLe-Regular.ttf'
    fullPath = Join-Path $root 'assets\fonts\_zcool-full.ttf'
    out = Join-Path $root 'assets\fonts\quote-zcool-subset.ttf'
  }
  smiley = @{
    full = ''
    fullPath = Join-Path $root 'assets\fonts\_smiley-full.otf'
    out = Join-Path $root 'assets\fonts\quote-smiley-subset.ttf'
  }
}

function Ensure-SmileyFull($path) {
  if ((Test-Path $path) -and (Get-Item $path).Length -gt 100000) { return }
  python -c @"
import urllib.request, ssl, zipfile, io
url = 'https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip'
ctx = ssl.create_default_context()
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
    z = zipfile.ZipFile(io.BytesIO(r.read()))
for n in z.namelist():
    if n.lower().endswith(('.ttf','.otf')):
        open(r'$path','wb').write(z.read(n))
        break
"@
}

$targets = if ($Font -eq 'all') { @('wenkai','zcool','smiley') } else { @($Font) }

foreach ($name in $targets) {
  $j = $jobs[$name]
  if ($name -eq 'smiley') { Ensure-SmileyFull $j.fullPath }
  elseif (-not (Test-Path $j.fullPath) -or (Get-Item $j.fullPath).Length -lt 10000) {
    curl -L -o $j.fullPath $j.full -s --max-time 300
  }
  if (-not (Test-Path $j.fullPath)) { Write-Host "跳过 $name：缺少完整字体"; continue }
  pyftsubset $j.fullPath --text="$chars" --output-file=$j.out
  Write-Host "$name -> $($j.out) ($((Get-Item $j.out).Length) bytes)"
}

Write-Host "当前配置见 utils/config.js QUOTE_FONT"
