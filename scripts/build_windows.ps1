[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$outputRoot = Join-Path $projectRoot "outputs"
$workRoot = Join-Path $projectRoot "work\pyinstaller"
$bundleName = "YouTubeMusicDesktop"
$bundlePath = Join-Path $outputRoot $bundleName
$iconDirectory = Join-Path $projectRoot "src\ytmusic_player\assets\icons"
$iconPath = Join-Path $iconDirectory "youtube_music_desktop.ico"
$versionInfoPath = Join-Path $workRoot "windows-version-info.txt"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Create .venv and install the project first."
}
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Application icon not found. Run: .\.venv\Scripts\python.exe .\tools\build_icons.py"
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: .\.venv\Scripts\python.exe -m pip install -e '.[build]'"
}

$appVersion = (& $python -c "from ytmusic_player.metadata import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $appVersion) {
    throw "Unable to read the application version."
}
$archivePath = Join-Path $outputRoot "$bundleName-$appVersion-windows-x64.zip"

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null

& $python (Join-Path $projectRoot "tools\build_version_info.py") --output $versionInfoPath
if ($LASTEXITCODE -ne 0) {
    throw "Unable to generate Windows version metadata."
}

if (Test-Path -LiteralPath $bundlePath) {
    Remove-Item -LiteralPath $bundlePath -Recurse -Force
}
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name $bundleName `
        --icon $iconPath `
        --version-file $versionInfoPath `
        --add-data "$iconDirectory;ytmusic_player/assets/icons" `
        --paths (Join-Path $projectRoot "src") `
        --distpath $outputRoot `
        --workpath $workRoot `
        --specpath $workRoot `
        (Join-Path $projectRoot "packaging\launcher.py")

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

# Some development environments add an unrelated Poppler installation to PATH.
# PyInstaller can then mistake Poppler's ICU libraries for Qt dependencies. The
# PySide6 Windows wheel uses the ICU runtime provided by Windows, so those DLLs
# make QtCore fail at startup if they are bundled beside the application.
$pySidePackage = Join-Path $projectRoot ".venv\Lib\site-packages\PySide6"
$pySideShipsIcu = Get-ChildItem -LiteralPath $pySidePackage -Recurse -File -Filter "icuuc.dll" -ErrorAction SilentlyContinue
if (-not $pySideShipsIcu) {
    $internalPath = Join-Path $bundlePath "_internal"
    foreach ($icuName in @("icuuc.dll", "icudt*.dll")) {
        Get-ChildItem -LiteralPath $internalPath -File -Filter $icuName -ErrorAction SilentlyContinue |
            Remove-Item -Force
    }
}

Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $bundlePath -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "PROTOCOL.md") -Destination $bundlePath -Force

Compress-Archive -LiteralPath $bundlePath -DestinationPath $archivePath -CompressionLevel Optimal

$executable = Join-Path $bundlePath "$bundleName.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Build finished without producing $executable."
}

Write-Host "Build complete: $executable"
Write-Host "Archive created: $archivePath"
