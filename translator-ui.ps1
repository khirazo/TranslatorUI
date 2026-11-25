[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$ListenHost = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 4568,

    [switch]$OpenBrowser,

    # Accepted for older commands and shortcuts.
    [switch]$NoTui,

    [switch]$DirectServer
)

$ErrorActionPreference = "Stop"

$repositoryRoot = $PSScriptRoot
$venvPath = Join-Path $repositoryRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$envTemplatePath = Join-Path $repositoryRoot ".env.template"
$envPath = Join-Path $repositoryRoot ".env"
$minimumPythonVersion = [Version]"3.12"

function Get-PythonVersion {
    param([string]$Executable, [string[]]$Arguments = @())

    $version = & $Executable @Arguments -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return [Version]($version | Select-Object -First 1)
}

function Assert-SupportedPython {
    param([Version]$Version, [string]$Description)

    if ($Version -lt $minimumPythonVersion) {
        throw "$Description uses Python $Version. TranslatorUI requires Python $minimumPythonVersion or newer."
    }
}

function Get-LocalPython {
    if (Get-Command -Name "py" -ErrorAction SilentlyContinue) {
        $version = Get-PythonVersion -Executable "py" -Arguments @("-3")
        if ($null -ne $version) {
            Assert-SupportedPython -Version $version -Description "The Python launcher selection"
            return @{ Executable = "py"; Arguments = @("-3") }
        }
    }

    if (-not (Get-Command -Name "python" -ErrorAction SilentlyContinue)) {
        throw "Python 3.12 or newer was not found. Install uv or Python, then run this script again."
    }
    $version = Get-PythonVersion -Executable "python"
    if ($null -eq $version) {
        throw "Python 3.12 or newer was not found. Install uv or Python, then run this script again."
    }
    Assert-SupportedPython -Version $version -Description "The default Python command"
    return @{ Executable = "python"; Arguments = @() }
}

if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $envTemplatePath)) {
        throw "Environment template file was not found: $envTemplatePath"
    }
    Write-Host "Creating $envPath from .env.template for local Uvicorn execution."
    Copy-Item -LiteralPath $envTemplatePath -Destination $envPath
    Write-Warning "Review $envPath and set LLM_MODEL to the model ID published by your LLM server."
}

Write-Host "Starting TranslatorUI at http://$($ListenHost):$Port"
$uv = Get-Command -Name "uv" -ErrorAction SilentlyContinue
$python = $null
if ($null -eq $uv) {
    if (Test-Path $venvPython) {
        $venvVersion = Get-PythonVersion -Executable $venvPython
        if ($null -eq $venvVersion) {
            throw "The existing virtual environment is not usable: $venvPython. Install uv or recreate .venv yourself."
        }
        Assert-SupportedPython -Version $venvVersion -Description "The existing virtual environment"
        $python = @{ Executable = $venvPython; Arguments = @() }
    } else {
        $python = Get-LocalPython
    }

    & $python.Executable @($python.Arguments) -c "import fastapi, httpx, pydantic, dotenv, uvicorn"
    if ($LASTEXITCODE -ne 0) {
        throw "TranslatorUI dependencies are unavailable. Install uv (recommended), or create .venv and run '$($python.Executable) -m pip install -r translator_ui/requirements.txt'."
    }
}

$launcherArguments = @("-m", "app.launcher", "--host", $ListenHost, "--port", "$Port")
if ($OpenBrowser) {
    $launcherArguments += "--open-browser"
}

Push-Location $repositoryRoot
$previousPythonPath = $env:PYTHONPATH
$launcherPythonPath = Join-Path $repositoryRoot "translator_ui"
$env:PYTHONPATH = if ([string]::IsNullOrEmpty($previousPythonPath)) {
    $launcherPythonPath
} else {
    "$launcherPythonPath;$previousPythonPath"
}
try {
    if ($null -ne $uv) {
        $launcherExecutable = (& $uv.Source run --locked -- python -c "import sys; print(sys.executable)" | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($launcherExecutable)) {
            throw "uv could not resolve the locked Python environment for TranslatorUI."
        }
        $runtime = @{ Executable = $launcherExecutable; Arguments = @() }
    } else {
        $runtime = $python
    }

    & $runtime.Executable @($runtime.Arguments) @launcherArguments
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }
    Pop-Location
}

exit $exitCode
