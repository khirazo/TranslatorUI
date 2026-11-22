# Repository guidance

## Scope

TranslatorUI extends the LocaLingo baseline with a web UI for streaming text translation through
OpenAI-compatible LLM endpoints. The initial implementation uses LM Studio locally, but the product
is not limited to local models; support for other compatible providers and, later, ACP agents is in
scope. PDF translation is intentionally out of scope.

## Instruction loading

At the start of work, read this file and, if it exists, `AGENTS.local.md` in the repository root.
`AGENTS.local.md` contains machine-specific supplemental guidance. Follow it together with this
file, but treat system and user instructions as higher priority. Do not commit `AGENTS.local.md`
or copy credentials from it into source code, logs, or documentation.

## Repository layout

- `translator_ui/`: FastAPI text-translation service.
- `docs/`: public documentation assets.
- `work/`: local-only notes and scratch files; do not commit its contents.

## Development conventions

- Keep `main` as the upstream baseline. Make product work in `develop` or `feature/<name>` branches;
  the current Python migration branch is `feature/python-migration`.
- Make focused changes and avoid unrelated formatting changes.
- Do not commit credentials, API tokens, translation data, or machine-specific paths.
- Update public documentation when a user-visible behavior, configuration option, or deployment procedure changes.
- Preserve upstream license notices and check the terms of models, APIs, and other non-code dependencies separately.

## Local services

Use the start wrappers and uv for local service execution. The FastAPI service health endpoint is
`http://localhost:4568/health`. See `work/DESIGN-CHECKPOINT.md` for the implementation contract.

## Local-only instructions

Put machine-specific setup notes, secrets locations, and unpublished design notes in `AGENTS.local.md` or `work/`. Both are intentionally ignored by Git.
