# build_installer.ps1
# Compiles the Inno Setup script (SaveSpace.iss) to produce SaveSpace-Setup-v1.0.exe

param(
    [string]$IssFile = "$PSScriptRoot\FocusloopLabs.iss"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$DistDir = Join-Path $ProjectRoot "dist\FocusloopLabs"

if (-not (Test-Path (Join-Path $DistDir "FocusloopLabs.exe"))) {
    Write-Host "dist\FocusloopLabs directory not found or incomplete." -ForegroundColor Yellow
    Write-Host "Running build_dist.ps1 first to stage the distribution..." -ForegroundColor Cyan
    & "$PSScriptRoot\build_dist.ps1" -SkipPython
}

# Find Inno Setup Compiler (iscc.exe)
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    $whichIsccCmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($whichIsccCmd) { $iscc = $whichIsccCmd.Source }
}

if (-not $iscc) {
    Write-Host "`n[NOTE] Inno Setup 6 compiler (ISCC.exe) was not found." -ForegroundColor Yellow
    Write-Host "To generate the 1-click installer .exe, install Inno Setup with:" -ForegroundColor Cyan
    Write-Host "    winget install JRSoftware.InnoSetup" -ForegroundColor White
    Write-Host "or download it from: https://jrsoftware.org/isdl.php" -ForegroundColor White
    Write-Host "`nOnce installed, re-run this script to build SaveSpace-Setup-v1.0.exe.`n"
    exit 0
}

Write-Host "Using Inno Setup Compiler: $iscc" -ForegroundColor Green
Write-Host "Compiling installer from:  $IssFile" -ForegroundColor Cyan

& $iscc $IssFile

if ($LASTEXITCODE -eq 0) {
    $setupExe = Join-Path $ProjectRoot "dist\Focusloop-Labs-Setup-v1.0.0.exe"
    if (-not (Test-Path $setupExe)) {
        $setupExe = (Get-ChildItem -Path (Join-Path $ProjectRoot "dist") -Filter "*Setup*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    }
    if ($setupExe -and (Test-Path $setupExe)) {
        Write-Host "`n====================================================" -ForegroundColor Green
        Write-Host " INSTALLER CREATED SUCCESSFULLY!                    " -ForegroundColor Green
        Write-Host " File: $setupExe ($((Get-Item $setupExe).Length / 1MB | ForEach-Object { '{0:N1} MB' -f $_ }))" -ForegroundColor Green
        Write-Host "====================================================" -ForegroundColor Green
    }
} else {
    Write-Error "Inno Setup compilation failed with exit code $LASTEXITCODE."
}
