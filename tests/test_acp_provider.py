import asyncio
import os
import sys
from pathlib import Path

import pytest
from app.config import ProviderSettings, TranslationOptions
from app.providers.acp import AcpProvider
from app.providers.base import TranslationProviderError

FAKE_AGENT = """
import json
import sys

def send(message):
    print(json.dumps(message), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "test"}})
    elif method == "session/prompt":
        send({"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {}})
        response = json.loads(next(sys.stdin))
        assert response["result"]["outcome"]["outcome"] == "cancelled"
        for chunk in ("translated ", "text"):
            update = {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": chunk},
            }
            send({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"update": update},
            })
        send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})
        break
"""

NOISY_AGENT = """
import json
import sys

def send(message):
    print(json.dumps(message), flush=True)

print("startup noise", flush=True)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        print("not json", flush=True)
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": 1}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"sessionId": "test"}})
    elif method == "session/prompt":
        sys.stderr.write("x" * 200_000)
        sys.stderr.flush()
        send({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "clean"},
            }},
        })
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"stopReason": "end_turn"}})
        break
"""

HANGING_AGENT = """
import json
from pathlib import Path
import subprocess
import sys
import time

def send(message):
    print(json.dumps(message), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "initialize":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": 1}})
    elif message.get("method") == "session/new":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"sessionId": "test"}})
    elif message.get("method") == "session/prompt":
        if len(sys.argv) > 1:
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
        time.sleep(60)
"""


def write_agent(tmp_path: Path, source: str) -> tuple[str, str]:
    agent = tmp_path / "fake_acp_agent.py"
    agent.write_text(source, encoding="utf-8")
    return sys.executable, str(agent)


def settings_for(command: tuple[str, ...], timeout_seconds: int = 10) -> ProviderSettings:
    return ProviderSettings(
        id="acp", name="Test ACP", kind="acp", command=command, timeout_seconds=timeout_seconds
    )


@pytest.mark.asyncio
async def test_acp_provider_streams_chunks_and_rejects_permission(tmp_path) -> None:
    settings = settings_for(write_agent(tmp_path, FAKE_AGENT))
    provider = AcpProvider(settings)
    options = TranslationOptions(model_id="ignored", translation_profile="generic")

    chunks = [
        chunk
        async for chunk in provider.translate(
            text="hello", source_lang="en", target_lang="ja", options=options
        )
    ]

    assert chunks == ["translated ", "text"]


@pytest.mark.asyncio
async def test_acp_provider_uses_agent_default_when_no_model_capability(tmp_path) -> None:
    provider = AcpProvider(settings_for(write_agent(tmp_path, FAKE_AGENT)))

    models = await provider.discover_models()

    assert [(model.id, model.display_name, model.efforts) for model in models] == [
        ("agent-default", "Agent default", ())
    ]


def test_acp_provider_passes_only_explicit_environment(monkeypatch) -> None:
    monkeypatch.setenv("USERPROFILE", "profile")
    monkeypatch.setenv("TRANSLATOR_UI_TEST_SECRET", "must-not-leak")
    provider = AcpProvider(
        ProviderSettings(
            id="acp",
            name="Test ACP",
            kind="acp",
            command=("agent",),
            environment=("USERPROFILE",),
        )
    )

    environment = provider._child_environment()

    assert environment["USERPROFILE"] == "profile"
    assert "TRANSLATOR_UI_TEST_SECRET" not in environment


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"message": "folder is not trusted"}, "dedicated workspace"),
        ({"message": "Authentication required"}, "Log in with the agent CLI first (sso)."),
        ({"message": "license acceptance required"}, "Accept the agent license"),
    ],
)
def test_acp_provider_explains_recoverable_rpc_errors(error, expected) -> None:
    provider = AcpProvider(settings_for((sys.executable,)))
    provider._auth_methods = ("sso",)

    assert expected in str(provider._rpc_error("session/new", error))


@pytest.mark.asyncio
async def test_acp_provider_ignores_stdout_noise_and_drains_stderr(tmp_path) -> None:
    provider = AcpProvider(settings_for(write_agent(tmp_path, NOISY_AGENT), timeout_seconds=3))
    options = TranslationOptions(model_id="agent-default", translation_profile="generic")

    chunks = [
        chunk
        async for chunk in provider.translate(
            text="hello", source_lang="en", target_lang="ja", options=options
        )
    ]

    assert chunks == ["clean"]
    assert provider._stderr_tasks == {}


@pytest.mark.asyncio
async def test_acp_provider_times_out_and_stops_its_process(tmp_path) -> None:
    provider = AcpProvider(settings_for(write_agent(tmp_path, HANGING_AGENT), timeout_seconds=1))
    options = TranslationOptions(model_id="agent-default", translation_profile="generic")

    with pytest.raises(TranslationProviderError, match="within 1 seconds"):
        async for _ in provider.translate(
            text="hello", source_lang="en", target_lang="ja", options=options
        ):
            pass

    assert provider._stderr_tasks == {}


@pytest.mark.asyncio
async def test_acp_provider_cancellation_stops_its_process(tmp_path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    command = (*write_agent(tmp_path, HANGING_AGENT), str(pid_file))
    provider = AcpProvider(settings_for(command, timeout_seconds=30))
    options = TranslationOptions(model_id="agent-default", translation_profile="generic")
    translation = provider.translate(
        text="hello", source_lang="en", target_lang="ja", options=options
    )
    pending = asyncio.create_task(anext(translation))
    for _ in range(30):
        if pid_file.exists():
            break
        await asyncio.sleep(0.1)
    assert pid_file.exists()
    grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending
    await translation.aclose()

    assert provider._stderr_tasks == {}
    for _ in range(30):
        try:
            os.kill(grandchild_pid, 0)
        except OSError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("ACP grandchild process remained after cancellation")


@pytest.mark.asyncio
async def test_acp_requests_are_serialized(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0

    async def blocked_translate(**kwargs: object):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.set()
        try:
            await release.wait()
            yield "done"
        finally:
            active -= 1

    first = AcpProvider(settings_for((sys.executable,)))
    second = AcpProvider(settings_for((sys.executable,)))
    monkeypatch.setattr(first, "_translate", blocked_translate)
    monkeypatch.setattr(second, "_translate", blocked_translate)
    options = TranslationOptions(model_id="agent-default", translation_profile="generic")

    async def collect(provider: AcpProvider) -> list[str]:
        return [
            chunk
            async for chunk in provider.translate(
                text="hello", source_lang="en", target_lang="ja", options=options
            )
        ]

    first_task = asyncio.create_task(collect(first))
    await started.wait()
    second_task = asyncio.create_task(collect(second))
    await asyncio.sleep(0.1)
    assert peak == 1
    release.set()
    assert await first_task == ["done"]
    assert await second_task == ["done"]
    assert peak == 1
