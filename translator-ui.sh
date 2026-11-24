#!/usr/bin/env bash

set -euo pipefail

listen_host="127.0.0.1"
port="4568"
open_browser=false
no_tui=false
minimum_python_version="3.12"

usage() {
    cat <<'EOF'
Usage: ./translator-ui.sh [options]

Options:
  --listen-host HOST       Address to bind (default: 127.0.0.1)
  --port PORT              Port to bind (default: 4568)
  --open-browser           Open the UI after its health check succeeds
  --no-tui                 Disable the interactive terminal controller
  -h, --help               Show this help message
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --listen-host)
            listen_host="$2"
            shift 2
            ;;
        --port)
            port="$2"
            shift 2
            ;;
        --open-browser)
            open_browser=true
            shift
            ;;
        --no-tui)
            no_tui=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "--port must be an integer from 1 through 65535." >&2
    exit 2
fi

repository_root="$(cd "$(dirname "$0")" && pwd)"
venv_path="$repository_root/.venv"
venv_python="$venv_path/bin/python"
env_template_path="$repository_root/.env.template"
env_path="$repository_root/.env"

get_python_version() {
    "$@" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
}

assert_supported_python() {
    local executable="$1"
    local description="$2"
    local version

    if ! version="$(get_python_version "$executable")"; then
        echo "Unable to determine the Python version for $description." >&2
        exit 1
    fi
    if ! "$executable" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        echo "$description uses Python $version. TranslatorUI requires Python $minimum_python_version or newer." >&2
        exit 1
    fi
}

if [ ! -f "$env_path" ]; then
    if [ ! -f "$env_template_path" ]; then
        echo "Environment template file was not found: $env_template_path" >&2
        exit 1
    fi
    echo "Creating $env_path from .env.template for local Uvicorn execution."
    cp "$env_template_path" "$env_path"
    echo "Warning: review $env_path and set LLM_MODEL to the model ID published by your LLM server." >&2
fi

echo "Starting TranslatorUI at http://$listen_host:$port"

has_uv=false
if command -v uv >/dev/null 2>&1; then
    has_uv=true
fi

python=""
if [ "$has_uv" = false ] && [ -x "$venv_python" ]; then
    assert_supported_python "$venv_python" "The existing virtual environment"
    python="$venv_python"
elif [ "$has_uv" = false ] && [ -e "$venv_path" ]; then
    echo "The existing .venv is not a usable Unix virtual environment. Install uv or recreate .venv yourself." >&2
    exit 1
elif [ "$has_uv" = false ]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
            python="$candidate"
            break
        fi
    done
    if [ -z "$python" ]; then
        echo "Python $minimum_python_version or newer was not found. Install uv or Python, then run this script again." >&2
        exit 1
    fi
fi

if [ "$has_uv" = false ] && ! "$python" -c 'import fastapi, httpx, pydantic, dotenv, uvicorn' >/dev/null 2>&1; then
    echo "TranslatorUI dependencies are unavailable. Install uv (recommended), or create .venv and run '$python -m pip install -r translator_ui/requirements.txt'." >&2
    exit 1
fi

cd "$repository_root"
if [ -n "${PYTHONPATH:-}" ]; then
    export PYTHONPATH="$repository_root/translator_ui:$PYTHONPATH"
else
    export PYTHONPATH="$repository_root/translator_ui"
fi
launcher_args=(-m app.launcher --host "$listen_host" --port "$port")
if [ "$open_browser" = true ]; then
    launcher_args+=(--open-browser)
fi
if [ "$no_tui" = true ]; then
    launcher_args+=(--no-tui)
fi

if [ "$has_uv" = true ]; then
    if ! launcher_python="$(uv run --locked -- python -c 'import sys; print(sys.executable)')"; then
        echo "uv could not resolve the locked Python environment for TranslatorUI." >&2
        exit 1
    fi
    if "$launcher_python" "${launcher_args[@]}"; then
        exit_code=0
    else
        exit_code=$?
    fi
else
    if "$python" "${launcher_args[@]}"; then
        exit_code=0
    else
        exit_code=$?
    fi
fi

exit "$exit_code"
