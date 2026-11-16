# Repository guidance

## Scope

LocaLingo provides a web UI for text and PDF translation through an OpenAI-compatible local LLM endpoint.

## Repository layout

- `localingo/`: Ruby web application and its data directory.
- `pdf2zh/`: PDF translation service and configuration.
- `docs/`: public documentation assets.
- `compose.yml`: local multi-service development configuration.
- `work/`: local-only notes and scratch files; do not commit its contents.

## Development conventions

- Keep `main` as the upstream baseline. Make product work in `develop` or `feature/<name>` branches.
- Make focused changes and avoid unrelated formatting changes.
- Do not commit credentials, API tokens, translation data, or machine-specific paths.
- Update public documentation when a user-visible behavior, configuration option, or deployment procedure changes.
- Preserve upstream license notices and check the terms of models, APIs, and other non-code dependencies separately.

## Local services

Use `docker compose up -d` to start the configured services. The application health endpoint is `http://localhost:4567/health`.

## Local-only instructions

Put machine-specific setup notes, secrets locations, and unpublished design notes in `AGENTS.local.md` or `work/`. Both are intentionally ignored by Git.
