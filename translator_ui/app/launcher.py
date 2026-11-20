"""Interactive local supervisor for the TranslatorUI Uvicorn process."""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

LOG_CAPACITY = 1000
GRACEFUL_STOP_SECONDS = 10
TERMINATE_STOP_SECONDS = 5


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


def supports_tui(stdin: TextIO, stdout: TextIO, *, disabled: bool) -> bool:
    """Use ANSI redraw only where it is safe and useful."""
    if disabled or not stdin.isatty() or not stdout.isatty():
        return False
    if os.name != "nt":
        return True
    if os.getenv("TERM_PROGRAM", "").lower() == "vscode":
        return False
    return bool(
        os.getenv("WT_SESSION")
        or os.getenv("ANSICON")
        or os.getenv("CONEMUANSI") == "ON"
        or os.getenv("TERM")
    )


def _raise_keyboard_interrupt(*_: object) -> None:
    raise KeyboardInterrupt


def is_interrupt_key(key: str) -> bool:
    """Recognize Ctrl+C when a Windows terminal reports it as a character."""
    return key == "\x03"


@dataclass
class LogBuffer:
    """A bounded, thread-safe-enough-for-this-use log history."""

    lines: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_CAPACITY))

    def append(self, line: str) -> None:
        self.lines.append(line.rstrip("\r\n"))

    def tail(self, count: int, offset: int = 0) -> list[str]:
        if count <= 0:
            return []
        end = max(0, len(self.lines) - offset)
        start = max(0, end - count)
        return list(self.lines)[start:end]


class TerminalInput:
    """Read one key at a time while restoring POSIX terminal settings on exit."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._original: list[object] | None = None

    def __enter__(self) -> TerminalInput:
        if os.name != "nt":
            import termios
            import tty

            self._original = termios.tcgetattr(self._stream.fileno())
            tty.setcbreak(self._stream.fileno())
        return self

    def __exit__(self, *_: object) -> None:
        if self._original is not None:
            import termios

            termios.tcsetattr(self._stream.fileno(), termios.TCSADRAIN, self._original)

    def read(self, timeout: float) -> str | None:
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key in {"\x00", "\xe0"}:
                        msvcrt.getwch()
                        return None
                    return key
                time.sleep(0.02)
            return None

        import select

        readable, _, _ = select.select([self._stream], [], [], timeout)
        return self._stream.read(1) if readable else None


class Launcher:
    """Own one Uvicorn child and present either a TUI or a log relay."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        open_browser: bool,
        tui: bool,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        health_check: Callable[[str], bool] = health_is_ready,
        browser_open: Callable[[str], bool] = open_browser,
    ) -> None:
        self.host = host
        self.port = port
        self.url = browser_url(host, port)
        self.open_browser_on_ready = open_browser
        self.tui = tui
        self.stdin = stdin
        self.stdout = stdout
        self._popen = popen
        self._health_check = health_check
        self._browser_open = browser_open
        self._logs = LogBuffer()
        self._process: subprocess.Popen[str] | None = None
        self._stop_event = threading.Event()
        self._stopping = threading.Event()
        self._reader: threading.Thread | None = None
        self._browser_waiter: threading.Thread | None = None
        self._message = "Starting server…"
        self._follow_logs = True
        self._log_offset = 0
        self._started_at = time.monotonic()

    def command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "translator_ui",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]

    def start(self) -> None:
        kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self._process = self._popen(self.command(), **kwargs)
        self._reader = threading.Thread(target=self._read_logs, daemon=True)
        self._reader.start()
        if self.open_browser_on_ready:
            self._browser_waiter = threading.Thread(target=self._wait_and_open_browser, daemon=True)
            self._browser_waiter.start()

    def _read_logs(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            self._logs.append(line)
            if not self.tui:
                self.stdout.write(line)
                self.stdout.flush()

    def _wait_and_open_browser(self) -> None:
        for _ in range(60):
            if (
                self._stop_event.is_set()
                or self._process is None
                or self._process.poll() is not None
            ):
                return
            if self._health_check(self.url):
                self._browser_open(self.url)
                self._message = "Browser opened."
                return
            self._stop_event.wait(0.5)

    def _open_browser(self) -> None:
        if self._health_check(self.url):
            self._browser_open(self.url)
            self._message = "Browser opened."
        else:
            self._message = "Server is not ready yet; browser was not opened."

    def _draw(self, *, confirmation: bool) -> None:
        try:
            height = shutil.get_terminal_size(fallback=(80, 24)).lines
            log_count = max(3, height - 7)
            elapsed = int(time.monotonic() - self._started_at)
            process_id = self._process.pid if self._process is not None else "-"
            prompt = (
                "Exit TranslatorUI? [y/N]"
                if confirmation
                else "q quit · o open browser · h/? help · j/k scroll · f follow"
            )
            lines = [
                "TranslatorUI local launcher",
                f"URL: {self.url}  PID: {process_id}  Uptime: {elapsed}s",
                self._message,
                prompt,
                "─" * 72,
                *self._logs.tail(log_count, self._log_offset),
            ]
            self.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")
            self.stdout.flush()
        except OSError:
            self.tui = False

    def _handle_key(self, key: str, *, confirmation: bool) -> bool:
        if confirmation:
            if key.lower() == "y":
                self.stop()
                return False
            self._message = "Exit cancelled."
            return False
        if key.lower() == "q":
            self._message = "Exit requested."
            return True
        if key.lower() == "o":
            self._open_browser()
        elif key.lower() in {"h", "?"}:
            self._message = "q: quit  o: open browser  j/k: scroll logs  f: follow logs"
        elif key.lower() == "j":
            self._follow_logs = False
            self._log_offset = min(len(self._logs.lines), self._log_offset + 1)
        elif key.lower() == "k":
            self._log_offset = max(0, self._log_offset - 1)
            self._follow_logs = self._log_offset == 0
        elif key.lower() == "f":
            self._log_offset = 0
            self._follow_logs = True
        return False

    def run(self) -> int:
        self.start()
        assert self._process is not None
        previous_sigterm = self._install_sigterm_handler()
        if not self.tui:
            try:
                return self._process.wait()
            except KeyboardInterrupt:
                self.stop()
                return self._process.wait()
            finally:
                self._restore_sigterm_handler(previous_sigterm)

        confirmation = False
        try:
            with TerminalInput(self.stdin) as terminal:
                while self._process.poll() is None:
                    if self._follow_logs:
                        self._log_offset = 0
                    self._draw(confirmation=confirmation)
                    key = terminal.read(0.1)
                    if key is None:
                        continue
                    if is_interrupt_key(key):
                        self.stop()
                        break
                    if confirmation:
                        if key.lower() == "y":
                            self.stop()
                            confirmation = False
                        else:
                            self._message = "Exit cancelled."
                            confirmation = False
                    elif self._handle_key(key, confirmation=False):
                        confirmation = True
        except KeyboardInterrupt:
            self.stop()
        finally:
            self._stop_event.set()
            if self._process.poll() is None:
                self.stop()
            self.stdout.write("\x1b[?25h")
            self.stdout.flush()
            self._restore_sigterm_handler(previous_sigterm)

        return self._process.wait()

    def _install_sigterm_handler(self) -> signal.Handlers | None:
        """Turn launcher termination into the same cleanup path as Ctrl+C."""
        try:
            previous = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        except (AttributeError, ValueError):
            return None
        return previous

    @staticmethod
    def _restore_sigterm_handler(previous: signal.Handlers | None) -> None:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)

    def stop(self) -> None:
        """Stop only the process group created by this launcher."""
        process = self._process
        if process is None or process.poll() is not None or self._stopping.is_set():
            return
        self._stopping.set()
        self._stop_event.set()
        self._message = "Stopping TranslatorUI…"
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=GRACEFUL_STOP_SECONDS)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass

        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=TERMINATE_STOP_SECONDS)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass

        if os.name == "nt":
            subprocess.run(["taskkill", "/pid", str(process.pid), "/t", "/f"], check=False)
        else:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TranslatorUI with a local terminal controller."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4568)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--no-tui", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be an integer from 1 through 65535.")
    tui = supports_tui(sys.stdin, sys.stdout, disabled=args.no_tui)
    return Launcher(host=args.host, port=args.port, open_browser=args.open_browser, tui=tui).run()


if __name__ == "__main__":
    raise SystemExit(main())
