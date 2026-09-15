$WshShell = New-Object -ComObject WScript.Shell
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$TargetExe = Join-Path $ProjectRoot "FocusloopLabs.exe"
if (-not (Test-Path $TargetExe)) { $TargetExe = Join-Path $ProjectRoot "SaveSpace.exe" }
$IconPath = Join-Path $ProjectRoot "FocusloopLabs.ico"
if (-not (Test-Path $IconPath)) { $IconPath = Join-Path $ProjectRoot "SaveSpace.ico" }

if (-not (Test-Path $TargetExe)) {
    Write-Error "Launcher executable not found at $TargetExe"
    exit 1
}

# 1. Start Menu Shortcut (Instantly searchable from Windows Start Menu)
$StartMenuPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (-not (Test-Path $StartMenuPath)) {
    $StartMenuPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Programs)
}

# Remove old SaveSpace shortcut if present
$oldStartShortcut = Join-Path $StartMenuPath "SaveSpace.lnk"
if (Test-Path $oldStartShortcut) { Remove-Item $oldStartShortcut -Force -ErrorAction SilentlyContinue }

$StartShortcutPath = Join-Path $StartMenuPath "Focusloop Labs.lnk"
$StartShortcut = $WshShell.CreateShortcut($StartShortcutPath)
$StartShortcut.TargetPath = $TargetExe
$StartShortcut.WorkingDirectory = $ProjectRoot
$StartShortcut.IconLocation = "$IconPath,0"
$StartShortcut.Description = 'Focusloop Labs - Studio Assistant and Media Manager'
$StartShortcut.Save()
Write-Host "Created Start Menu shortcut: $StartShortcutPath"

# 2. Desktop Shortcut
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$oldDesktopShortcut = Join-Path $DesktopPath "SaveSpace.lnk"
if (Test-Path $oldDesktopShortcut) { Remove-Item $oldDesktopShortcut -Force -ErrorAction SilentlyContinue }

$DesktopShortcutPath = Join-Path $DesktopPath "Focusloop Labs.lnk"
$DesktopShortcut = $WshShell.CreateShortcut($DesktopShortcutPath)
$DesktopShortcut.TargetPath = $TargetExe
$DesktopShortcut.WorkingDirectory = $ProjectRoot
$DesktopShortcut.IconLocation = "$IconPath,0"
$DesktopShortcut.Description = 'Focusloop Labs - Studio Assistant and Media Manager'
$DesktopShortcut.Save()
Write-Host "Created Desktop shortcut: $DesktopShortcutPath"
