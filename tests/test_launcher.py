from __future__ import annotations

from app.launcher import browser_url, open_browser


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
