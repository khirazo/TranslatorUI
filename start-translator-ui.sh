#!/usr/bin/env bash

set -euo pipefail

listen_host="127.0.0.1"
port="4568"
install_dependencies=false
recreate_venv=false
minimum_python_version="3.12"

usage() {
    cat <<'EOF'
Usage: ./start-translator-ui.sh [options]

Options:
  --listen-host HOST       Address to bind (default: 127.0.0.1)
  --port PORT              Port to bind (default: 4568)
  --install-dependencies   Reinstall requirements.txt dependencies
  --recreate-venv          Delete and recreate .venv
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
        --install-dependencies)
            install_dependencies=true
            shift
            ;;
        --recreate-venv)
            recreate_venv=true
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

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_path="$repository_root/.venv"
venv_python="$venv_path/bin/python"
requirements_path="$repository_root/translator_ui/requirements.txt"
env_example_path="$repository_root/.env.example"
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

    if ! "$executable" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"; then
        echo "$description uses Python $version. TranslatorUI requires Python $minimum_python_version or newer." >&2
        exit 1
    fi
}

if [ "$recreate_venv" = true ] && [ -e "$venv_path" ]; then
    echo "Removing the existing virtual environment: $venv_path"
    rm -rf "$venv_path"
fi

if [ -x "$venv_python" ]; then
    assert_supported_python "$venv_python" "The existing virtual environment"
    python="$venv_python"
elif [ -e "$venv_path" ]; then
    echo "The existing .venv is not a usable Unix virtual environment. Use --recreate-venv to recreate it." >&2
    exit 1
else
    python_command=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
                python_command="$candidate"
                break
            fi
        fi
    done

    if [ -z "$python_command" ]; then
        echo "Python $minimum_python_version or newer was not found. Install Python, then run this script again." >&2
        exit 1
    fi

    version="$(get_python_version "$python_command")"
    echo "Creating virtual environment with Python $version: $venv_path"
    "$python_command" -m venv "$venv_path"
    if [ ! -x "$venv_python" ]; then
        echo "Failed to create the virtual environment at $venv_path." >&2
        exit 1
    fi
    python="$venv_python"
    install_dependencies=true
fi

if [ ! -f "$requirements_path" ]; then
    echo "Requirements file was not found: $requirements_path" >&2
    exit 1
fi

if [ "$install_dependencies" = true ] || ! "$python" -c 'import fastapi, httpx, pydantic, dotenv, uvicorn' >/dev/null 2>&1; then
    echo "Installing TranslatorUI dependencies..."
    "$python" -m pip install --upgrade pip
    "$python" -m pip install -r "$requirements_path"
fi

if [ ! -f "$env_path" ]; then
    if [ ! -f "$env_example_path" ]; then
        echo "Environment example file was not found: $env_example_path" >&2
        exit 1
    fi
    echo "Creating $env_path from .env.example for local Uvicorn execution."
    sed 's|^LLM_ENDPOINT=http://host\.docker\.internal:1234$|LLM_ENDPOINT=http://localhost:1234|' \
        "$env_example_path" > "$env_path"
    echo "Warning: review $env_path and set LLM_MODEL to the model ID published by your LLM server." >&2
fi

export PYTHONPATH="$repository_root/translator_ui${PYTHONPATH:+:$PYTHONPATH}"
echo "Starting TranslatorUI at http://${listen_host}:$port"
exec "$python" -m uvicorn app.main:app --host "$listen_host" --port "$port"