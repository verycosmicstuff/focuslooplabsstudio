$WshShell = New-Object -ComObject WScript.Shell
$ProjectRoot = "F:\antigravity projects\saveSpace"
$TargetExe = Join-Path $ProjectRoot "SaveSpace.exe"
$IconPath = Join-Path $ProjectRoot "SaveSpace.ico"

if (-not (Test-Path $TargetExe)) {
    Write-Error "SaveSpace.exe not found at $TargetExe"
    exit 1
}

# 1. Start Menu Shortcut (Instantly searchable from Windows Start Menu)
$StartMenuPath = [System.Environment]::GetFolderPath('Programs')
$StartShortcutPath = Join-Path $StartMenuPath "SaveSpace.lnk"
$StartShortcut = $WshShell.CreateShortcut($StartShortcutPath)
$StartShortcut.TargetPath = $TargetExe
$StartShortcut.WorkingDirectory = $ProjectRoot
$StartShortcut.IconLocation = "$IconPath,0"
$StartShortcut.Description = "SaveSpace Pro - Ultimate Media Storage Manager and Transcoder"
$StartShortcut.Save()
Write-Host "Created Start Menu shortcut: $StartShortcutPath"

# 2. Desktop Shortcut
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$DesktopShortcutPath = Join-Path $DesktopPath "SaveSpace.lnk"
$DesktopShortcut = $WshShell.CreateShortcut($DesktopShortcutPath)
$DesktopShortcut.TargetPath = $TargetExe
$DesktopShortcut.WorkingDirectory = $ProjectRoot
$DesktopShortcut.IconLocation = "$IconPath,0"
$DesktopShortcut.Description = "SaveSpace Pro - Ultimate Media Storage Manager and Transcoder"
$DesktopShortcut.Save()
Write-Host "Created Desktop shortcut: $DesktopShortcutPath"
