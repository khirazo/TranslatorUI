"""ACP translation provider using a fresh, restricted stdio session per request.

This adapts the user-authored reference ``work/ref/LLMtranslator/acp_client.py``
to TranslatorUI's async streaming-provider boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.config import ProviderSettings, TranslationOptions
from app.providers.base import TranslationProviderError
from app.providers.openai_compatible import (
    _BoundaryOutputFilter,
    build_generic_prompt,
    generate_translation_boundary,
)

_PROTOCOL_VERSION = 1
_POLL_SECONDS = 0.25


class AcpProvider:
    """Translate through an ACP agent without advertising filesystem or terminal tools."""

    def __init__(self, settings: ProviderSettings) -> None:
        self._settings = settings

    async def translate(
        self,
        *,
        text: str,
        source_lang: str,
        target_lang: str,
        options: TranslationOptions,
    ) -> AsyncIterator[str]:
        command = self._command()
        boundary = generate_translation_boundary(text)
        prompt = build_generic_prompt(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            form=options.japanese_style,
            boundary=boundary,
        )
        output_filter = _BoundaryOutputFilter(boundary)

        # A per-request system temporary directory cannot contain the application's
        # config, profiles, API keys, or saved translations.
        with tempfile.TemporaryDirectory(prefix="translator-ui-acp-") as raw_cwd:
            process = await self._start(command, Path(raw_cwd))
            try:
                await self._request(
                    process,
                    1,
                    "initialize",
                    {
                        "protocolVersion": _PROTOCOL_VERSION,
                        "clientCapabilities": {
                            "fs": {"readTextFile": False, "writeTextFile": False},
                            "terminal": False,
                        },
                        "clientInfo": {"name": "TranslatorUI", "version": "1.0"},
                    },
                )
                created = await self._request(
                    process, 2, "session/new", {"cwd": raw_cwd, "mcpServers": []}
                )
                session_id = created.get("sessionId")
                if not isinstance(session_id, str) or not session_id:
                    raise TranslationProviderError(
                        "ACP agent did not create a translation session."
                    )
                await self._set_mode(process, session_id, created)
                config_options = created.get("configOptions")
                request_id = 3
                request_id, config_options = await self._set_option(
                    process, request_id, session_id, config_options, "model", options.model_id
                )
                request_id, _ = await self._set_option(
                    process, request_id, session_id, config_options, "thought_level", options.effort
                )
                await self._send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": prompt}],
                        },
                    },
                )
                async for chunk in self._stream_prompt(process, request_id):
                    filtered = output_filter.feed(chunk)
                    if filtered:
                        yield filtered
                final = output_filter.finish()
                if final:
                    yield final
            finally:
                await self._stop_tree(process)

    def _command(self) -> tuple[str, ...]:
        if not self._settings.command:
            raise TranslationProviderError("ACP provider has no configured command.")
        executable = shutil.which(self._settings.command[0])
        if executable is None:
            raise TranslationProviderError("Configured ACP command was not found on PATH.")
        return (executable, *self._settings.command[1:])

    async def _start(self, command: tuple[str, ...], cwd: Path) -> asyncio.subprocess.Process:
        kwargs: dict[str, Any] = {"cwd": str(cwd)}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            return await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )
        except OSError as error:
            raise TranslationProviderError("Could not start the configured ACP command.") from error

    async def _send(self, process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise TranslationProviderError("ACP agent exited before accepting a request.")
        process.stdin.write((json.dumps(message) + "\n").encode())
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise TranslationProviderError("ACP agent exited unexpectedly.") from error

    async def _read(self, process: asyncio.subprocess.Process) -> dict[str, Any]:
        if process.stdout is None:
            raise TranslationProviderError("ACP agent has no stdout stream.")
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=_POLL_SECONDS)
            except TimeoutError as error:
                if process.returncode is not None:
                    raise TranslationProviderError("ACP agent exited unexpectedly.") from error
                continue
            if not line:
                raise TranslationProviderError("ACP agent exited unexpectedly.")
            try:
                message = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(message, dict):
                return message

    async def _request(
        self,
        process: asyncio.subprocess.Process,
        request_id: int,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        await self._send(
            process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            message = await self._read(process)
            if "method" in message:
                await self._handle_agent_request(process, message)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise TranslationProviderError(f"ACP {method} request was rejected.")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    async def _handle_agent_request(
        self, process: asyncio.subprocess.Process, message: dict[str, Any]
    ) -> None:
        if "id" not in message:
            return
        if message.get("method") == "session/request_permission":
            response: dict[str, Any] = {"result": {"outcome": {"outcome": "cancelled"}}}
        else:
            response = {"error": {"code": -32601, "message": "Method not found"}}
        await self._send(process, {"jsonrpc": "2.0", "id": message["id"], **response})

    async def _set_mode(
        self, process: asyncio.subprocess.Process, session_id: str, created: dict[str, Any]
    ) -> None:
        if not self._settings.mode:
            return
        modes = created.get("modes")
        available = modes.get("availableModes", []) if isinstance(modes, dict) else []
        if self._settings.mode not in [
            item.get("id") for item in available if isinstance(item, dict)
        ]:
            raise TranslationProviderError("Configured ACP mode is unavailable.")
        await self._request(
            process,
            20,
            "session/set_mode",
            {"sessionId": session_id, "modeId": self._settings.mode},
        )

    async def _set_option(
        self,
        process: asyncio.subprocess.Process,
        request_id: int,
        session_id: str,
        config_options: Any,
        category: str,
        value: str | None,
    ) -> tuple[int, Any]:
        if not value or not isinstance(config_options, list):
            return request_id, config_options
        option = next(
            (
                item
                for item in config_options
                if isinstance(item, dict)
                and item.get("category") == category
                and item.get("type") == "select"
            ),
            None,
        )
        if option is None or not isinstance(option.get("id"), str):
            raise TranslationProviderError(
                f"ACP agent does not offer the requested {category} setting."
            )
        result = await self._request(
            process,
            request_id,
            "session/set_config_option",
            {"sessionId": session_id, "configId": option["id"], "value": value},
        )
        return request_id + 1, result.get("configOptions", config_options)

    async def _stream_prompt(
        self, process: asyncio.subprocess.Process, request_id: int
    ) -> AsyncIterator[str]:
        while True:
            message = await self._read(process)
            if "method" in message:
                if message.get("method") == "session/update":
                    update = (
                        message.get("params", {}).get("update", {})
                        if isinstance(message.get("params"), dict)
                        else {}
                    )
                    content = (
                        update.get("content")
                        if update.get("sessionUpdate") == "agent_message_chunk"
                        else None
                    )
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "text"
                        and isinstance(content.get("text"), str)
                    ):
                        yield content["text"]
                await self._handle_agent_request(process, message)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message or message.get("result", {}).get("stopReason") != "end_turn":
                raise TranslationProviderError(
                    "ACP agent did not complete the translation normally."
                )
            return

    async def _stop_tree(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            with contextlib.suppress(OSError):
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/T", "/F", "/PID", str(process.pid)
                )
                await asyncio.wait_for(killer.wait(), timeout=5)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=2)
        if process.returncode is None:
            process.kill()
            await process.wait()
