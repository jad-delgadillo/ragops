# Codebase Manual

Generated at: 2026-02-17 20:05:09Z

## Project
- Name: `ragops`
- Tech stack: Python, Docker, Terraform
- Analyzer scope: file tree (depth <= 3), key entrypoints, Python AST symbols

## File Map (Preview)
- `frontend/app.js`
- `scripts/init_neon.py`
- `scripts/mock_chat_api.py`
- `services/__init__.py`
- `services/api/__init__.py`
- `services/api/app/__init__.py`
- `services/api/app/access.py`
- `services/api/app/chat.py`
- `services/api/app/handler.py`
- `services/api/app/retriever.py`
- `services/api/tests/__init__.py`
- `services/api/tests/test_access.py`
- `services/api/tests/test_chat.py`
- `services/cli/__init__.py`
- `services/cli/docgen/__init__.py`
- `services/cli/docgen/analyzer.py`
- `services/cli/docgen/generator.py`
- `services/cli/docgen/manuals.py`
- `services/cli/eval.py`
- `services/cli/main.py`
- `services/cli/project.py`
- `services/cli/remote.py`
- `services/cli/tests/__init__.py`
- `services/cli/tests/test_eval.py`
- `services/cli/tests/test_manuals.py`
- `services/core/__init__.py`
- `services/core/bedrock_provider.py`
- `services/core/claude_provider.py`
- `services/core/config.py`
- `services/core/database.py`
- `services/core/gemini_provider.py`
- `services/core/groq_provider.py`
- `services/core/logging.py`
- `services/core/ollama_provider.py`
- `services/core/openai_provider.py`
- `services/core/providers.py`
- `services/core/tests/__init__.py`
- `services/core/tests/test_database.py`
- `services/core/tests/test_providers.py`
- `services/ingest/__init__.py`
- `services/ingest/app/__init__.py`
- `services/ingest/app/chunker.py`
- `services/ingest/app/handler.py`
- `services/ingest/app/pipeline.py`
- `services/ingest/tests/__init__.py`
- `services/ingest/tests/test_chunker.py`

## Key Symbols
### `services/api/app/handler.py`
- Function `lambda_handler`
- Function `_handle_health`
- Function `_handle_query`
- Function `_handle_chat`
- Function `_handle_feedback`
- Function `_authorize`
- Function `_forbidden`
- Function `_with_cors`
- Function `main`
### `services/cli/main.py`
- Function `cmd_init`
- Function `cmd_ingest`
- Function `cmd_query`
- Function `cmd_chat`
- Function `cmd_feedback`
- Function `cmd_eval`
- Function `cmd_generate_docs`
- Function `cmd_generate_manuals`
- Function `cmd_providers`
- Function `build_parser`
- Function `main`
### `services/ingest/app/handler.py`
- Function `lambda_handler`
- Function `main`

## Onboarding Notes
1. Start with `services/cli/main.py` to understand developer workflow.
2. Review `services/ingest` for indexing pipeline behavior.
3. Review `services/api` for runtime query behavior and response contract.
4. Review `services/core` for provider, config, and database abstractions.
