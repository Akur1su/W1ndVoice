$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$templates = Join-Path $projectRoot 'app/templates'
$static = Join-Path $projectRoot 'app/static'

uv run --with pyinstaller==6.22.3 -- pyinstaller `
  --noconfirm `
  --onefile `
  --windowed `
  --name W1ndVoice `
  --icon "$static/w1ndvoice.ico" `
  --add-data "$templates;app/templates" `
  --add-data "$static;app/static" `
  --collect-submodules uvicorn `
  --collect-all webview `
  --specpath build/spec `
  --workpath build/pyinstaller `
  --distpath dist `
  app/desktop.py

if ($LASTEXITCODE -ne 0) { throw 'EXE 构建失败' }
