# compile_launcher.ps1
# Compiles FocusloopLauncher.cs into FocusloopLabs.exe with embedded icon and application metadata

param(
    [string]$OutputPath = "$PSScriptRoot\..\FocusloopLabs.exe"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$SourcePath = Join-Path $PSScriptRoot "FocusloopLauncher.cs"
$IconPath = Join-Path $ProjectRoot "FocusloopLabs.ico"
if (-not (Test-Path $IconPath)) { $IconPath = Join-Path $ProjectRoot "SaveSpace.ico" }

if (-not (Test-Path $SourcePath)) {
    Write-Error "Launcher source not found: $SourcePath"
}

# Find csc.exe in standard .NET Framework directory
$cscCandidates = @(
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

$csc = $cscCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $csc) {
    Write-Error "Microsoft C# Compiler (csc.exe) was not found in Windows directory."
}

Write-Host "Compiling Focusloop Labs launcher..."
Write-Host "Compiler: $csc"
Write-Host "Source:   $SourcePath"
Write-Host "Icon:     $IconPath"
Write-Host "Output:   $OutputPath"

$compileArgs = @(
    "/target:winexe",
    "/optimize+",
    "/platform:anycpu",
    "/out:$OutputPath",
    "/reference:System.Windows.Forms.dll",
    "/reference:System.Drawing.dll",
    "/reference:System.dll"
)

if (Test-Path $IconPath) {
    $compileArgs += "/win32icon:$IconPath"
}

$compileArgs += $SourcePath

& $csc $compileArgs

if ($LASTEXITCODE -eq 0 -and (Test-Path $OutputPath)) {
    Write-Host "`nSuccessfully built FocusloopLabs.exe ($((Get-Item $OutputPath).Length) bytes) at: $OutputPath" -ForegroundColor Green
} else {
    Write-Error "Compilation failed with exit code $LASTEXITCODE."
}
