$ErrorActionPreference = 'Stop'

try {
    $launcher = Join-Path $PSScriptRoot 'translator-ui.ps1'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "Launcher not found: $launcher"
    }
    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    if (-not $desktop -or -not (Test-Path -LiteralPath $desktop -PathType Container)) {
        throw 'Desktop folder not found.'
    }
    $path = Join-Path $desktop 'TranslatorUI.lnk'
    if (Test-Path -LiteralPath $path) {
        $answer = Read-Host "Shortcut already exists: $path. Replace it? [y/N]"
        if ($answer -notmatch '^[yY]$') {
            Write-Host 'Cancelled.'
            exit 0
        }
    }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $terminal = Get-Command -Name 'wt.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($terminal) {
        $shortcut.TargetPath = $terminal.Source
        $shortcut.Arguments = "new-tab --startingDirectory `"$PSScriptRoot`" `"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -OpenBrowser"
        Write-Host 'Using Windows Terminal. If it fails to open, check your Windows Terminal installation.'
    } else {
        $shortcut.TargetPath = $powershell
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -OpenBrowser -DirectServer"
        Write-Host 'Windows Terminal not found; the shortcut will show logs. Press Ctrl+C to stop.'
    }
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'Start TranslatorUI'
    $shortcut.Save()
    Write-Host "Shortcut created: $path"
} catch {
    Write-Host "Could not create shortcut: $_"
    exit 1
}
