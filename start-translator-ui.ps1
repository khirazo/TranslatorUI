[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$ListenHost = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 4568,

    [switch]$InstallDependencies,

    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"

$repositoryRoot = $PSScriptRoot
$venvPath = Join-Path $repositoryRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $repositoryRoot "translator_ui\requirements.txt"
$envTemplatePath = Join-Path $repositoryRoot ".env.template"
$envPath = Join-Path $repositoryRoot ".env"
$minimumPythonVersion = [Version]"3.12"

function Get-PythonVersion {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    $version = & $Executable @Arguments -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return [Version]($version | Select-Object -First 1)
}

function Assert-SupportedPython {
    param(
        [Version]$Version,
        [string]$Description
    )

    if ($Version -lt $minimumPythonVersion) {
        throw "$Description uses Python $Version. TranslatorUI requires Python $minimumPythonVersion or newer."
    }
}

if ($RecreateVenv -and (Test-Path $venvPath)) {
    Write-Host "Removing the existing virtual environment: $venvPath"
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (Test-Path $venvPython) {
    $venvVersion = Get-PythonVersion -Executable $venvPython
    if ($null -eq $venvVersion) {
        throw "The existing virtual environment is not usable: $venvPython. Use -RecreateVenv to recreate it."
    }
    Assert-SupportedPython -Version $venvVersion -Description "The existing virtual environment"
    $python = $venvPython
} else {
    $pythonCommand = $null
    $pythonArguments = @()

    if (Get-Command -Name "py" -ErrorAction SilentlyContinue) {
        $candidateVersion = Get-PythonVersion -Executable "py" -Arguments @("-3")
        if ($null -ne $candidateVersion) {
            Assert-SupportedPython -Version $candidateVersion -Description "The Python launcher selection"
            $pythonCommand = "py"
            $pythonArguments = @("-3")
        }
    }

    if ($null -eq $pythonCommand) {
        if (-not (Get-Command -Name "python" -ErrorAction SilentlyContinue)) {
            throw "Python 3.12 or newer was not found. Install Python, then run this script again."
        }
        $candidateVersion = Get-PythonVersion -Executable "python"
        if ($null -eq $candidateVersion) {
            throw "Python 3.12 or newer was not found. Install Python, then run this script again."
        }
        Assert-SupportedPython -Version $candidateVersion -Description "The default Python command"
        $pythonCommand = "python"
    }

    Write-Host "Creating virtual environment with Python ${candidateVersion}: $venvPath"
    & $pythonCommand @pythonArguments -m venv $venvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Failed to create the virtual environment at $venvPath."
    }
    $python = $venvPython
    $InstallDependencies = $true
}

if (-not (Test-Path $requirementsPath)) {
    throw "Requirements file was not found: $requirementsPath"
}

$dependenciesAvailable = $false
try {
    & $python -c "import fastapi, httpx, pydantic, dotenv, uvicorn"
    $dependenciesAvailable = $LASTEXITCODE -eq 0
} catch {
    $dependenciesAvailable = $false
}

if ($InstallDependencies -or -not $dependenciesAvailable) {
    Write-Host "Installing TranslatorUI dependencies..."
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip."
    }
    & $python -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install TranslatorUI dependencies."
    }
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

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $repositoryRoot "translator_ui"
    Write-Host "Starting TranslatorUI at http://${ListenHost}:$Port"
    & $python -m uvicorn app.main:app --host $ListenHost --port $Port
} finally {
    $env:PYTHONPATH = $previousPythonPath
}