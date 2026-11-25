"""Run TranslatorUI in the foreground with optional browser startup."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
import webbrowser

import uvicorn


def browser_url(host: str, port: int) -> str:
    """Return a browser-reachable URL for a server bind address."""
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "[::1]"
    return f"http://{host}:{port}"


def health_is_ready(url: str) -> bool:
    """Return whether the local application health endpoint is available."""
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=1) as response:  # noqa: S310
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def is_wsl() -> bool:
    """Return whether the launcher is running under Windows Subsystem for Linux."""
    return bool(os.getenv("WSL_DISTRO_NAME")) or "microsoft" in platform.release().lower()


def open_browser(url: str) -> bool:
    """Open a URL, preferring host-browser bridges when running in WSL."""
    commands: list[list[str]] = []
    if is_wsl():
        if wslview := shutil.which("wslview"):
            commands.append([wslview, url])
        if cmd := shutil.which("cmd.exe"):
            commands.append([cmd, "/c", "start", "", url])
    for command in commands:
        try:
            subprocess.Popen(  # noqa: S603
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return webbrowser.open(url)


def open_when_ready(server: uvicorn.Server, url: str, done: threading.Event) -> None:
    for _ in range(60):
        if done.is_set() or server.should_exit:
            return
        if server.started and health_is_ready(url):
            if not done.is_set() and not server.should_exit:
                open_browser(url)
            return
        done.wait(0.5)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TranslatorUI with foreground logs.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4568)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--no-tui", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be an integer from 1 through 65535.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port))
    done = threading.Event()
    if args.open_browser:
        threading.Thread(
            target=open_when_ready,
            args=(server, browser_url(args.host, args.port), done),
            daemon=True,
        ).start()
    try:
        server.run()
    except KeyboardInterrupt:
        return 130
    finally:
        done.set()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
