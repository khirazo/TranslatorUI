[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$ListenHost = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 4568,

    [switch]$OpenBrowser,

    [switch]$NoTui
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

function Start-BrowserWhenReady {
    param([string]$Url)

    Start-Job -ArgumentList $Url -ScriptBlock {
        param([string]$TargetUrl)

        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri "$TargetUrl/health" -TimeoutSec 1 -ErrorAction Stop
                if ($response.StatusCode -eq 200) {
                    Start-Process $TargetUrl
                    return
                }
            } catch {
                # The server is still starting or has exited.
            }
            Start-Sleep -Milliseconds 500
        }
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
$uvicornArguments = @("-m", "uvicorn", "app.main:app", "--app-dir", "translator_ui", "--host", $ListenHost, "--port", "$Port")
if ($OpenBrowser) {
    $launcherArguments += "--open-browser"
}
if ($NoTui) {
    $launcherArguments += "--no-tui"
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

    $browserJob = $null
    if ($env:TERM_PROGRAM -ieq "vscode") {
        Write-Host "VS Code integrated terminal detected; starting Uvicorn directly so Ctrl+C stops it reliably."
        if ($OpenBrowser) {
            $browserHost = if ($ListenHost -eq "0.0.0.0") { "127.0.0.1" } elseif ($ListenHost -eq "::") { "[::1]" } else { $ListenHost }
            $browserJob = Start-BrowserWhenReady -Url "http://$($browserHost):$Port"
        }
        & $runtime.Executable @($runtime.Arguments) @uvicornArguments
    } else {
        & $runtime.Executable @($runtime.Arguments) @launcherArguments
    }
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -ne $browserJob) {
        Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }
    Pop-Location
}

exit $exitCode
