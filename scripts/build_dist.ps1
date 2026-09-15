# build_dist.ps1
# Builds a self-contained, zero-dependency distribution of SaveSpace Pro for any Windows PC.

param(
    [string]$DistDir = "$PSScriptRoot\..\dist\FocusloopLabs",
    [string]$PythonHost = "",
    [switch]$SkipPython,
    [switch]$MakeZip
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Focusloop Labs: Building Standalone Distribution   " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "Project Root: $ProjectRoot"
Write-Host "Dist Output:  $DistDir"

# 1. Resolve Host Python
if (-not $PythonHost) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) { $PythonHost = $cand; break }
    }
    if (-not $PythonHost) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $PythonHost = $cmd.Source }
    }
}

if (-not (Test-Path $PythonHost)) {
    Write-Error "Could not find a valid host Python executable. Please specify -PythonHost <path>."
}
Write-Host "Using Host Python: $PythonHost"

# 2. Prepare Directory Layout
Write-Host "`n[1/6] Staging distribution directories..." -ForegroundColor Yellow
$dirsToCreate = @(
    $DistDir,
    (Join-Path $DistDir "bin"),
    (Join-Path $DistDir "data"),
    (Join-Path $DistDir "data\thumbnails"),
    (Join-Path $DistDir "data\quarantine"),
    (Join-Path $DistDir "logs")
)
foreach ($dir in $dirsToCreate) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# If dist\SaveSpace\python exists and dist\FocusloopLabs\python does not, reuse it
$legacyPython = Join-Path $ProjectRoot "dist\SaveSpace\python"
$targetPython = Join-Path $DistDir "python"
if ((Test-Path $legacyPython) -and (-not (Test-Path $targetPython))) {
    Write-Host "Reusing staged runtime from $legacyPython..." -ForegroundColor Cyan
    Copy-Item -Recurse -Path $legacyPython -Destination $DistDir -Force
}

# 3. Compile Native Launcher (FocusloopLabs.exe)
Write-Host "`n[2/6] Compiling native FocusloopLabs.exe launcher..." -ForegroundColor Yellow
$launcherExe = Join-Path $DistDir "FocusloopLabs.exe"
$compileScript = Join-Path $PSScriptRoot "compile_launcher.ps1"
powershell -ExecutionPolicy Bypass -File $compileScript -OutputPath $launcherExe
Copy-Item (Join-Path $ProjectRoot "FocusloopLabs.ico") (Join-Path $DistDir "FocusloopLabs.ico") -Force
Copy-Item (Join-Path $ProjectRoot "run_focusloop.bat") (Join-Path $DistDir "run_focusloop.bat") -Force

# 4. Bundle FFmpeg and FFprobe binaries
Write-Host "`n[3/6] Bundling FFmpeg & FFprobe utilities..." -ForegroundColor Yellow
$ffmpegCandidates = @(
    "C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe",
    (Join-Path $ProjectRoot "bin\ffmpeg.exe")
)
$ffprobeCandidates = @(
    "C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffprobe.exe",
    (Join-Path $ProjectRoot "bin\ffprobe.exe")
)

$ffmpegSrc = $ffmpegCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$ffprobeSrc = $ffprobeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($ffmpegSrc -and $ffprobeSrc) {
    Copy-Item $ffmpegSrc (Join-Path $DistDir "bin\ffmpeg.exe") -Force
    Copy-Item $ffprobeSrc (Join-Path $DistDir "bin\ffprobe.exe") -Force
    Write-Host "Bundled FFmpeg:  $ffmpegSrc" -ForegroundColor Green
    Write-Host "Bundled FFprobe: $ffprobeSrc" -ForegroundColor Green
} else {
    Write-Warning "Direct FFmpeg binaries not found in standard paths. Attempting fallback via PATH..."
    $whichFfmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $whichFfprobeCmd = Get-Command ffprobe -ErrorAction SilentlyContinue
    $whichFfmpeg = if ($whichFfmpegCmd) { $whichFfmpegCmd.Source } else { $null }
    $whichFfprobe = if ($whichFfprobeCmd) { $whichFfprobeCmd.Source } else { $null }
    if ($whichFfmpeg -and $whichFfprobe) {
        Copy-Item $whichFfmpeg (Join-Path $DistDir "bin\ffmpeg.exe") -Force
        Copy-Item $whichFfprobe (Join-Path $DistDir "bin\ffprobe.exe") -Force
        Write-Host "Bundled FFmpeg from PATH" -ForegroundColor Green
    } else {
        Write-Warning "Could not find FFmpeg binaries to bundle. Target machine must have FFmpeg installed on PATH."
    }
}

# Check for HandBrakeCLI
$hbCandidates = @(
    "C:\Program Files\HandBrake\HandBrakeCLI.exe",
    (Join-Path $ProjectRoot "bin\HandBrakeCLI.exe")
)
$hbSrc = $hbCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($hbSrc) {
    Copy-Item $hbSrc (Join-Path $DistDir "bin\HandBrakeCLI.exe") -Force
    Write-Host "Bundled HandBrakeCLI: $hbSrc" -ForegroundColor Green
}

# 5. Build Standalone Python Runtime
Write-Host "`n[4/6] Setting up standalone Python runtime..." -ForegroundColor Yellow
$distPythonDir = Join-Path $DistDir "python"
$distPythonExe = Join-Path $distPythonDir "Scripts\python.exe"

if ($SkipPython -and (Test-Path $distPythonExe)) {
    Write-Host "Skipping Python recreation (-SkipPython flag active)." -ForegroundColor Cyan
} else {
    if (Test-Path $distPythonDir) {
        Write-Host "Refreshing existing Python runtime at $distPythonDir..."
    } else {
        Write-Host "Creating standalone virtual environment with binaries..."
        & $PythonHost -m venv --copies $distPythonDir
    }

    Write-Host "Installing dependencies into standalone runtime from requirements.txt..."
    $reqFile = Join-Path $ProjectRoot "requirements.txt"
    & $distPythonExe -m pip install --upgrade pip --quiet
    & $distPythonExe -m pip install -r $reqFile --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install into standalone runtime failed with exit code $LASTEXITCODE."
    }
    Write-Host "Dependencies successfully installed into runtime." -ForegroundColor Green
}

# 6. Copy Application Source Code & UI (Excluding caches)
Write-Host "`n[5/6] Copying SaveSpace application code..." -ForegroundColor Yellow
Copy-Item (Join-Path $ProjectRoot "main.py") (Join-Path $DistDir "main.py") -Force
Copy-Item (Join-Path $ProjectRoot "requirements.txt") (Join-Path $DistDir "requirements.txt") -Force

# Copy src directory
$destSrc = Join-Path $DistDir "src"
if (Test-Path $destSrc) { Remove-Item -Recurse -Force $destSrc }
Copy-Item -Recurse -Path (Join-Path $ProjectRoot "src") -Destination $DistDir -Force
# Remove any pycache in dist
Get-ChildItem -Path $destSrc -Recurse -Include "__pycache__", "*.pyc" | Remove-Item -Recurse -Force

# Copy ui directory
$destUi = Join-Path $DistDir "ui"
if (Test-Path $destUi) { Remove-Item -Recurse -Force $destUi }
Copy-Item -Recurse -Path (Join-Path $ProjectRoot "ui") -Destination $DistDir -Force

# Sanitize / Initialize data
$localPresets = Join-Path $ProjectRoot "data\watermark_presets.json"
if (Test-Path $localPresets) {
    Copy-Item $localPresets (Join-Path $DistDir "data\watermark_presets.json") -Force
    Write-Host "Copied default watermark presets to package."
}

# Clean any transient db and log files from dist staging
Remove-Item -Path (Join-Path $DistDir "data\*.db*") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $DistDir "logs\*.log") -Force -ErrorAction SilentlyContinue

# 7. Optional ZIP creation
if ($MakeZip) {
    Write-Host "`n[6/6] Generating portable ZIP archive..." -ForegroundColor Yellow
    $zipPath = Join-Path (Split-Path $DistDir -Parent) "FocusloopLabs-v1.0-Portable.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Compress-Archive -Path "$DistDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host "Created portable package: $zipPath ($((Get-Item $zipPath).Length / 1MB | ForEach-Object { '{0:N1} MB' -f $_ }))" -ForegroundColor Green
} else {
    Write-Host "`n[6/6] Build complete! (Pass -MakeZip to produce a compressed zip archive)" -ForegroundColor Cyan
}

Write-Host "`n====================================================" -ForegroundColor Green
Write-Host " BUILD SUCCESSFUL: Focusloop Labs Standalone Folder " -ForegroundColor Green
Write-Host " Location: $DistDir" -ForegroundColor Green
Write-Host " Test it by running: '$launcherExe'" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
