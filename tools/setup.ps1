$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
Set-Location -LiteralPath $root
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& '.\.venv\Scripts\python.exe' -m pip install -e . --no-deps
if ($LASTEXITCODE -ne 0) { throw 'Mirage installation failed' }
Write-Output 'Mirage environment is ready. Launch Mirage.bat.'
