# TranslatorUI

TranslatorUI is a local web UI for streaming text translation through OpenAI-compatible LLM
endpoints. It supports LM Studio and other compatible providers. PDF translation is intentionally
out of scope: this repository does not download, bundle, or run PDFMathTranslate.

The project is based on the MIT-licensed LocaLingo baseline; its MIT license is retained in
[`LICENSE`](LICENSE).

## Run locally

Install [uv](https://docs.astral.sh/uv/), copy `.env.template` to `.env`, and set the model ID and
endpoint exposed by your LLM server. `LLM_ENDPOINT` is the root URL without `/v1`.

```bash
./start-translator-ui.sh
```

On Windows PowerShell:

```powershell
.\start-translator-ui.ps1
```

The wrappers prefer `uv run --locked`. If uv is unavailable, they use an existing `.venv`; without
one they only use a local Python 3.12+ installation when all dependencies are already present.
They never install dependencies into the global Python environment.

The service binds to `127.0.0.1:4568`. Add `--open-browser` on macOS/Linux/WSL or `-OpenBrowser`
on PowerShell to open the browser after the health check succeeds.

## Provider configuration

For multiple providers, copy `translator-ui.toml.example` to `translator-ui.toml` and set
`TRANSLATOR_UI_CONFIG=translator-ui.toml` in `.env`. Keep API keys in `.env`; TOML contains only
the environment-variable name, such as `api_key_env = "OPENAI_COMPAT_API_KEY"`.

Only enabled `openai_compatible` providers are available in the UI. ACP entries may be reserved in
TOML but remain unavailable until a separately designed adapter with process-isolation safeguards
is implemented.

## Docker Compose

Compose is optional and starts only the TranslatorUI service:

```bash
docker compose up -d translator-ui
```

The TOML path in `TRANSLATOR_UI_CONFIG` identifies the host file; Compose mounts it read-only at
`/app/translator-ui.toml`. Create the TOML file before starting Compose.

## Verify

```bash
curl http://localhost:4568/health
```

The expected response is `{"status":"ok"}`. Translation requests are sent to the same-origin
`/api/translate-text` endpoint and are delivered as Server-Sent Events.
