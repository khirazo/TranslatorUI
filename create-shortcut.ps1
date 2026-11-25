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
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -OpenBrowser"
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'Start TranslatorUI'
    $shortcut.Save()
    Write-Host "Shortcut created: $path"
} catch {
    Write-Host "Could not create shortcut: $_"
    exit 1
}
