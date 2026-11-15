$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m PyInstaller --noconfirm --clean --distpath build\package --onedir --windowed --name Mirage --paths src --collect-data mirage --collect-all frida --hidden-import PySide6.QtSvg --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtPdf --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --copy-metadata frida --copy-metadata PySide6 launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
# Preserve the output directory itself: Explorer/other shells may hold its handle.
New-Item -ItemType Directory -Path 'dist\Mirage' -Force | Out-Null
Get-ChildItem -LiteralPath 'dist\Mirage' -Force | Remove-Item -Recurse -Force
Copy-Item -Path 'build\package\Mirage\*' -Destination 'dist\Mirage' -Recurse -Force
Copy-Item -LiteralPath 'THIRD_PARTY.md' -Destination 'dist\Mirage\THIRD_PARTY.md'
Copy-Item -LiteralPath 'README.md' -Destination 'dist\Mirage\README.md'
Copy-Item -LiteralPath 'README.en.md' -Destination 'dist\Mirage\README.en.md'
New-Item -ItemType Directory -Path 'dist\Mirage\docs' -Force | Out-Null
Copy-Item -Path 'docs\*.md' -Destination 'dist\Mirage\docs' -Force
Write-Output (Join-Path $root 'dist\Mirage\Mirage.exe')
