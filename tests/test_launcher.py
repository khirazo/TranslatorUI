from __future__ import annotations

import os
import signal
from io import StringIO

from app.launcher import (
    Launcher,
    LogBuffer,
    browser_url,
    is_interrupt_key,
    open_browser,
    parse_args,
    supports_tui,
)


class FakeTerminal(StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 45678
        self.stdout = StringIO()
        self.returncode: int | None = None
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def send_signal(self, signal_number: int) -> None:
        self.signals.append(signal_number)


def test_browser_url_uses_a_loopback_address_for_wildcard_binds() -> None:
    assert browser_url("0.0.0.0", 4568) == "http://127.0.0.1:4568"
    assert browser_url("::", 4568) == "http://[::1]:4568"
    assert browser_url("localhost", 9999) == "http://localhost:9999"


def test_wsl_browser_opener_prefers_wslview(monkeypatch) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr("app.launcher.is_wsl", lambda: True)
    monkeypatch.setattr(
        "app.launcher.shutil.which",
        lambda name: "/usr/bin/wslview" if name == "wslview" else None,
    )
    monkeypatch.setattr(
        "app.launcher.subprocess.Popen",
        lambda command, **kwargs: launched.append(command),
    )
    monkeypatch.setattr("app.launcher.webbrowser.open", lambda url: False)

    assert open_browser("http://127.0.0.1:4568") is True
    assert launched == [["/usr/bin/wslview", "http://127.0.0.1:4568"]]


def test_log_buffer_keeps_a_window_and_can_scroll_back() -> None:
    logs = LogBuffer()
    logs.append("first\n")
    logs.append("second\n")
    logs.append("third\n")

    assert logs.tail(2) == ["second", "third"]
    assert logs.tail(2, offset=1) == ["first", "second"]


def test_tui_is_disabled_for_non_interactive_streams() -> None:
    assert supports_tui(FakeTerminal(tty=False), FakeTerminal(tty=True), disabled=False) is False
    assert supports_tui(FakeTerminal(tty=True), FakeTerminal(tty=False), disabled=False) is False
    assert supports_tui(FakeTerminal(tty=True), FakeTerminal(tty=True), disabled=True) is False


def test_tui_is_disabled_in_the_vscode_windows_terminal(monkeypatch) -> None:
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr("app.launcher.os.name", "nt")

    assert supports_tui(FakeTerminal(tty=True), FakeTerminal(tty=True), disabled=False) is False


def test_ctrl_c_character_is_an_immediate_interrupt() -> None:
    assert is_interrupt_key("\x03") is True
    assert is_interrupt_key("q") is False


def test_launcher_builds_the_existing_uvicorn_command() -> None:
    launcher = Launcher(
        host="127.0.0.1",
        port=4568,
        open_browser=False,
        tui=False,
        stdin=FakeTerminal(tty=False),
        stdout=FakeTerminal(tty=False),
    )

    assert launcher.command()[1:] == [
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        "translator_ui",
        "--host",
        "127.0.0.1",
        "--port",
        "4568",
    ]


def test_launcher_starts_a_new_child_session(monkeypatch) -> None:
    process = FakeProcess()
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured.update(kwargs)
        return process

    launcher = Launcher(
        host="127.0.0.1",
        port=4568,
        open_browser=False,
        tui=False,
        stdin=FakeTerminal(tty=False),
        stdout=FakeTerminal(tty=False),
        popen=fake_popen,  # type: ignore[arg-type]
    )
    launcher.start()

    assert captured["command"] == launcher.command()
    if os.name == "nt":
        assert "creationflags" in captured
    else:
        assert captured["start_new_session"] is True


def test_launcher_stops_only_the_owned_process_group(monkeypatch) -> None:
    process = FakeProcess()
    killed: list[tuple[int, signal.Signals]] = []
    launcher = Launcher(
        host="127.0.0.1",
        port=4568,
        open_browser=False,
        tui=False,
        stdin=FakeTerminal(tty=False),
        stdout=FakeTerminal(tty=False),
    )
    launcher._process = process  # type: ignore[assignment]
    if os.name != "nt":
        monkeypatch.setattr("app.launcher.os.killpg", lambda pid, sig: killed.append((pid, sig)))

    launcher.stop()

    if os.name == "nt":
        assert process.signals == [signal.CTRL_BREAK_EVENT]
    else:
        assert killed == [(45678, signal.SIGINT)]


def test_launcher_commands_open_browser_and_quit_without_touching_a_server() -> None:
    opened: list[str] = []
    launcher = Launcher(
        host="127.0.0.1",
        port=4568,
        open_browser=False,
        tui=True,
        stdin=FakeTerminal(tty=True),
        stdout=FakeTerminal(tty=True),
        health_check=lambda url: True,
        browser_open=lambda url: opened.append(url) or True,
    )

    assert launcher._handle_key("o", confirmation=False) is False
    assert opened == ["http://127.0.0.1:4568"]
    assert launcher._handle_key("q", confirmation=False) is True


def test_parse_args_supports_existing_options_and_tui_opt_out() -> None:
    args = parse_args(["--host", "0.0.0.0", "--port", "9999", "--open-browser", "--no-tui"])

    assert args.host == "0.0.0.0"
    assert args.port == 9999
    assert args.open_browser is True
    assert args.no_tui is True
