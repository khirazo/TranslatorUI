# Repository guidance

## Scope

TranslatorUI extends the LocaLingo baseline with a web UI for text and PDF translation through
OpenAI-compatible LLM endpoints. The initial Python migration uses LM Studio locally, but the
product is not limited to local models; support for other compatible providers and, later, ACP
agents is in scope.

## Instruction loading

At the start of work, read this file and, if it exists, `AGENTS.local.md` in the repository root.
`AGENTS.local.md` contains machine-specific supplemental guidance. Follow it together with this
file, but treat system and user instructions as higher priority. Do not commit `AGENTS.local.md`
or copy credentials from it into source code, logs, or documentation.

## Repository layout

- `localingo/`: Ruby web application and its data directory.
- `pdf2zh/`: PDF translation service and configuration.
- `translator_ui/`: planned FastAPI text-translation service.
- `docs/`: public documentation assets.
- `compose.yml`: local multi-service development configuration.
- `work/`: local-only notes and scratch files; do not commit its contents.

## Development conventions

- Keep `main` as the upstream baseline. Make product work in `develop` or `feature/<name>` branches;
  the current Python migration branch is `feature/python-migration`.
- Make focused changes and avoid unrelated formatting changes.
- Do not commit credentials, API tokens, translation data, or machine-specific paths.
- Update public documentation when a user-visible behavior, configuration option, or deployment procedure changes.
- Preserve upstream license notices and check the terms of models, APIs, and other non-code dependencies separately.

## Local services

Use `docker compose up -d` to start the configured services. The existing Ruby application health
endpoint is `http://localhost:4567/health`. The planned Python text service uses port 4568 during
parallel verification; see `work/DESIGN-CHECKPOINT.md` for its implementation contract.

## Local-only instructions

Put machine-specific setup notes, secrets locations, and unpublished design notes in `AGENTS.local.md` or `work/`. Both are intentionally ignored by Git.
