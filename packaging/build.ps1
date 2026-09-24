param(
    [string]$Python = "python",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
$venvPython = Join-Path $project ".build-venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv .build-venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create build environment" }
}
& $venvPython -m pip install -r requirements.txt pyinstaller==6.22.3
if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies" }
& $venvPython packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Could not create icon" }
& $venvPython -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name AuroraMusic --icon assets\aurora.ico --add-data "ui;ui" `
    --collect-all imageio_ffmpeg aurora_music.py
if ($LASTEXITCODE -ne 0) { throw "Could not build AuroraMusic.exe" }

if (-not $InnoCompiler) {
    $choices = @(
        (Join-Path $project ".build-tools\InnoSetup7\ISCC.exe"),
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = $choices | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $InnoCompiler) { throw "ISCC.exe not found. Install Inno Setup 7 or pass -InnoCompiler." }
& $InnoCompiler packaging\aurora.iss
if ($LASTEXITCODE -ne 0) { throw "Could not build Setup.exe" }
Write-Host "Built dist\AuroraMusic\AuroraMusic.exe and dist\AuroraMusic-Setup-1.0.0.exe"
