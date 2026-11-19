[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$ListenHost = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 4568
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
    $envContents = Get-Content -LiteralPath $envTemplatePath -Raw
    $envContents = $envContents.Replace(
        "LLM_ENDPOINT=http://host.docker.internal:1234",
        "LLM_ENDPOINT=http://localhost:1234"
    )
    Set-Content -LiteralPath $envPath -Value $envContents -Encoding utf8
    Write-Warning "Review $envPath and set LLM_MODEL to the model ID published by your LLM server."
}

Write-Host "Starting TranslatorUI at http://${ListenHost}:$Port"
$uv = Get-Command -Name "uv" -ErrorAction SilentlyContinue
if ($null -ne $uv) {
    & $uv.Source run --locked -- python -m uvicorn app.main:app --app-dir translator_ui --host $ListenHost --port $Port
    exit $LASTEXITCODE
}

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

& $python.Executable @($python.Arguments) -m uvicorn app.main:app --app-dir translator_ui --host $ListenHost --port $Port
exit $LASTEXITCODE
