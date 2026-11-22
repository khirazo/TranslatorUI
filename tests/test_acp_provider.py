import sys

import pytest
from app.config import ProviderSettings, TranslationOptions
from app.providers.acp import AcpProvider

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


@pytest.mark.asyncio
async def test_acp_provider_streams_chunks_and_rejects_permission(tmp_path) -> None:
    agent = tmp_path / "fake_acp_agent.py"
    agent.write_text(FAKE_AGENT, encoding="utf-8")
    settings = ProviderSettings(
        id="acp",
        name="Test ACP",
        kind="acp",
        command=(sys.executable, str(agent)),
        timeout_seconds=10,
    )
    provider = AcpProvider(settings)
    options = TranslationOptions(model_id="ignored", translation_profile="generic")

    chunks = [
        chunk
        async for chunk in provider.translate(
            text="hello", source_lang="en", target_lang="ja", options=options
        )
    ]

    assert chunks == ["translated ", "text"]
