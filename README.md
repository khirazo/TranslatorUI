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
./translator-ui.sh
```

On Windows PowerShell:

```powershell
.\translator-ui.ps1
```

If Windows PowerShell 5 rejects the script under its execution policy, run it once without changing
the persistent policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\translator-ui.ps1
```

Follow an organization-managed group policy if it disallows this. For a downloaded checkout under
`RemoteSigned`, `Unblock-File .\translator-ui.ps1` is another option.

The wrappers prefer `uv run --locked` to resolve the locked environment, then launch the controller
directly with that environment's Python so `Ctrl+C` reaches it instead of an uv relay. If uv is
unavailable, they use an existing `.venv`; without one they only use a local Python 3.12+
installation when all dependencies are already present. They never install dependencies into the
global Python environment.

The service binds to `127.0.0.1:4568`. Add `--open-browser` on macOS/Linux/WSL or `-OpenBrowser`
on PowerShell to open the browser after the health check succeeds.

When started from an interactive ANSI-capable terminal, the wrappers show a small terminal
controller. Press `q` then `y` to stop only the TranslatorUI server, `o` to open the UI again,
`h` or `?` for help, and `j`/`k`/`f` to browse or follow the in-memory server log. `Ctrl+C` also
stops the server safely. The browser is never closed by the launcher. Add `--no-tui` on
macOS/Linux/WSL or `-NoTui` on PowerShell to keep plain foreground logs; non-interactive
invocations automatically use that mode. The Windows VS Code integrated terminal also uses it
automatically and runs Uvicorn in the foreground so that `Ctrl+C` remains reliable; use Windows
Terminal or another supported external terminal for the TUI.

On WSL, `--open-browser` and `o` use `wslview`, then `cmd.exe /c start`, to open the Windows
default browser.

### Sharing a checkout between Windows and WSL

Windows and Linux virtual environments are not interchangeable. If WSL opens the same checkout
through `/mnt/<drive>/...` and both platforms use the default `.venv`, WSL's uv can replace the
Windows environment with a Linux one. Windows uv then cannot remove the Linux `lib64` link and
stops with `failed to remove file '.venv/lib64'`.

Separate checkouts are safest. If both platforms must share one checkout, use separate environment
directories before starting the wrappers:

```powershell
# Windows PowerShell, from the repository root
$env:UV_PROJECT_ENVIRONMENT = ".venv-win"
.\translator-ui.ps1
```

```bash
# WSL, from the same repository root
export UV_PROJECT_ENVIRONMENT=.venv-linux
./translator-ui.sh
```

Both directories are ignored by Git. You may run `uv sync --locked` once in each environment with
the corresponding variable set.

To repair a default `.venv` already replaced by WSL, first stop all TranslatorUI, Python, and uv
processes. First remove only `.venv` from Windows, then rerun the wrapper. `uv run --locked`
automatically recreates the Windows environment, so a manual `uv sync` is normally unnecessary.
This does not remove source files, `.env`, or `translator-ui.toml`.

```powershell
# Windows PowerShell, from the repository root
if (-not (Test-Path -LiteralPath .\pyproject.toml)) { throw "Run this from the repository root." }
Remove-Item -LiteralPath .\.venv -Recurse -Force
.\translator-ui.ps1
```

Only if Windows cannot delete `.venv` because of `failed to remove file '.venv/lib64'` or an
access-denied error, use WSL. Verify that the current directory is the intended repository root,
then remove only the virtual environment:

```bash
pwd
test -f pyproject.toml && test -d .venv || exit 1
rm -rf -- .venv
```

Return to Windows PowerShell in the repository root and rerun the wrapper:

```powershell
.\translator-ui.ps1
```

## Provider configuration

For multiple providers, copy `translator-ui.toml.example` to `translator-ui.toml` and set
`TRANSLATOR_UI_CONFIG=translator-ui.toml` in `.env`. Keep API keys in `.env`; TOML contains only
the environment-variable name, such as `api_key_env = "OPENAI_COMPAT_API_KEY"`.

Only enabled `openai_compatible` providers are available in the UI. ACP entries may be reserved in
TOML but remain unavailable until a separately designed adapter with process-isolation safeguards
is implemented.

Each provider may retain its legacy `model` field and add one or more
`[[providers.model_overrides]]` entries. An override supplies a display name and, where needed, a
model-specific `translation_profile` such as `plamo3`; ordered `[[providers.model_rules]]` entries
provide a validated regular-expression fallback. Exact overrides take precedence over rules, then
the provider default. At startup and after **Reload settings**, the UI refreshes the provider's
`/v1/models` catalog and offers only currently reported IDs, enriched by that TOML metadata. A model
entry can expose an optional allowlist of `efforts`; only models that declare an `effort_request_field`
send that value upstream. The **Reload settings** button rereads
`.env` and the selected TOML without restarting the app. Parent-process environment
variables override `.env`; failed reloads leave the running configuration unchanged.

The `generic` translation profile sends a model-neutral translation instruction and preserves XML,
HTML, placeholders, and code structure while translating natural-language text. It does not send
PLaMo-specific prompt tokens or stop tokens.

The UI remembers the selected provider, model, effort, source and target languages, and Japanese
writing style in the browser's local storage for this origin. It does not store source text,
translations, API keys, endpoints, or configuration values. Saved provider choices are validated
against the current configuration on the next load; unavailable values fall back safely to the
current defaults.

## Proxy configuration

TranslatorUI uses the standard HTTPX proxy environment variables for outbound OpenAI-compatible
LLM requests: `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY`. Copy the commented examples
in `.env.template` to the Git-ignored `.env` and set only the variables required by your network.
For a typical HTTP forward proxy, use an `http://` proxy URL even when the LLM endpoint itself uses
HTTPS. Keep local LM Studio traffic out of the proxy with:

```dotenv
NO_PROXY=localhost,127.0.0.1,::1
```

Proxy URLs may contain credentials, so treat them as secrets: place real values only in `.env` or
the process environment, never in `translator-ui.toml`, documentation, logs, or commits. Proxy
behavior and authentication compatibility are provided by HTTPX and the configured proxy. Proxy
configuration applies process-wide; it cannot currently be selected per provider.

## Verify

```bash
curl http://localhost:4568/health
```

The expected response is `{"status":"ok"}`. Translation requests are sent to the same-origin
`/api/translate-text` endpoint and are delivered as Server-Sent Events.
