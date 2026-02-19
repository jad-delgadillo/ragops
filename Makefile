# RAG Ops Platform
.PHONY: dev dev-down ingest scan query chat feedback eval repo-add repo-add-lazy repo-sync repo-migrate repo-list frontend mock-api test lint fmt package package-check clean help

# Use venv Python if available, otherwise system Python
PYTHON := $(shell if [ -f .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------
# Local Development
# ----------------------------------------------------------------
dev: ## Start local Postgres + pgvector
	docker compose up -d
	@echo "⏳ Waiting for database..."
	@sleep 3
	@echo "✅ Database ready at localhost:5432"

dev-down: ## Stop local database
	docker compose down

dev-reset: ## Reset database (delete volume + restart)
	docker compose down -v
	docker compose up -d
	@sleep 3
	@echo "✅ Database reset complete"

# ----------------------------------------------------------------
# Install
# ----------------------------------------------------------------
install: ## Install dependencies
	pip install -e ".[dev]"

package: ## Build source and wheel distributions into dist/
	$(PYTHON) -m build

package-check: package ## Build packages and run metadata checks
	$(PYTHON) -m twine check dist/*

# ----------------------------------------------------------------
# ragops CLI (v2 — recommended)
# ----------------------------------------------------------------
init: ## Initialize ragops in a project (usage: make init DIR=../myproject)
	$(PYTHON) -m services.cli.main init $${DIR:-.}

ingest: ## Ingest docs/code (usage: make ingest or make ingest DIR=./docs)
	$(PYTHON) -m services.cli.main ingest $${DIR:+--dir $$DIR} $${PROJECT:+--project $$PROJECT}

scan: ## One-command project scan (ingest + manuals)
	$(PYTHON) -m services.cli.main scan $${COLLECTION:+--collection $$COLLECTION} $${OUTPUT:+--output $$OUTPUT}

query: ## Query the project (usage: make query Q="your question")
	$(PYTHON) -m services.cli.main query "$${Q:-How does this work?}" $${PROJECT:+--project $$PROJECT}

chat: ## Multi-turn chat (usage: make chat Q="question" MODE=explain_like_junior)
	$(PYTHON) -m services.cli.main chat "$${Q:-How should I learn this codebase?}" \
		$${MODE:+--mode $$MODE} $${SESSION:+--session-id $$SESSION} $${PROJECT:+--project $$PROJECT}

feedback: ## Submit feedback (usage: make feedback VERDICT=positive COMMENT="helpful")
	$(PYTHON) -m services.cli.main feedback \
		--verdict "$${VERDICT:-positive}" \
		$${COLLECTION:+--collection $$COLLECTION} \
		$${SESSION:+--session-id $$SESSION} \
		$${QUESTION:+--question "$$QUESTION"} \
		$${ANSWER:+--answer "$$ANSWER"} \
		$${COMMENT:+--comment "$$COMMENT"}

eval: ## Run eval dataset (usage: make eval DATASET=./eval/cases.yaml)
	$(PYTHON) -m services.cli.main eval --dataset "$${DATASET:-./eval/cases.yaml}" \
		$${COLLECTION:+--collection $$COLLECTION} $${TOPK:+--top-k $$TOPK}

repo-add: ## Add GitHub repo (usage: make repo-add URL=... REF=main FORCE=1)
	$(PYTHON) -m services.cli.main repo add "$${URL:?Set URL=https://github.com/org/repo}" \
		$${NAME:+--name $$NAME} \
		$${COLLECTION:+--collection $$COLLECTION} \
		$${REF:+--ref $$REF} \
		$${TOKEN:+--github-token $$TOKEN} \
		$${CACHE_DIR:+--cache-dir $$CACHE_DIR} \
		$${SKIP_INGEST:+--skip-ingest} \
		$${RESET_CODE:+--reset-code-collection} \
		$${RESET_MANUALS:+--reset-manuals-collection} \
		$${GENERATE_MANUALS:+--generate-manuals} \
		$${MANUALS_COLLECTION:+--manuals-collection $$MANUALS_COLLECTION} \
		$${MANUALS_OUTPUT:+--manuals-output $$MANUALS_OUTPUT} \
		$${FORCE:+--force}

repo-add-lazy: ## ⚡ Lazy-onboard a GitHub repo (instant, content embedded on-demand)
	$(PYTHON) -m services.cli.main repo add-lazy "$${URL:?Set URL=https://github.com/org/repo}" \
		$${NAME:+--name $$NAME} \
		$${COLLECTION:+--collection $$COLLECTION} \
		$${REF:+--ref $$REF} \
		$${TOKEN:+--github-token $$TOKEN} \
		$${FORCE:+--force}

repo-sync: ## Sync tracked repo(s) (usage: make repo-sync NAME=owner-repo or ALL=1)
	$(PYTHON) -m services.cli.main repo sync \
		$${NAME:-} \
		$${ALL:+--all} \
		$${REF:+--ref $$REF} \
		$${SKIP_INGEST:+--skip-ingest} \
		$${RESET_CODE:+--reset-code-collection} \
		$${RESET_MANUALS:+--reset-manuals-collection} \
		$${GENERATE_MANUALS:+--generate-manuals} \
		$${MANUALS_COLLECTION:+--manuals-collection $$MANUALS_COLLECTION} \
		$${MANUALS_OUTPUT:+--manuals-output $$MANUALS_OUTPUT}

repo-migrate: ## Migrate tracked repos to split collections (usage: make repo-migrate ALL=1 APPLY=1 PURGE_OLD=1)
	$(PYTHON) -m services.cli.main repo migrate-collections \
		$${NAME:-} \
		$${ALL:+--all} \
		$${MANUALS_COLLECTION:+--manuals-collection $$MANUALS_COLLECTION} \
		$${MANUALS_OUTPUT:+--manuals-output $$MANUALS_OUTPUT} \
		$${GENERATE_MANUALS:+--generate-manuals} \
		$${REINDEX:+--reindex} \
		$${PURGE_OLD:+--purge-old} \
		$${RESET_CODE:+--reset-code-collection} \
		$${RESET_MANUALS:+--reset-manuals-collection} \
		$${APPLY:+--apply}

repo-list: ## List tracked repositories
	$(PYTHON) -m services.cli.main repo list

frontend: ## Serve onboarding chat UI at http://localhost:4173
	$(PYTHON) -m http.server 4173 --directory frontend

mock-api: ## Start mock /v1/chat + /v1/feedback API at http://localhost:8090
	$(PYTHON) scripts/mock_chat_api.py --port 8090

local-api: ## Start REAL local API (wraps Lambda handler) at http://localhost:8090
	$(PYTHON) scripts/local_api.py --port 8090

# ----------------------------------------------------------------
# Testing
# ----------------------------------------------------------------
test: ## Run unit tests
	$(PYTHON) -m pytest services/ -v --tb=short

test-cov: ## Run tests with coverage
	$(PYTHON) -m pytest services/ -v --tb=short --cov=services --cov-report=term-missing

# ----------------------------------------------------------------
# Linting
# ----------------------------------------------------------------
lint: ## Run linter
	$(PYTHON) -m ruff check services/

fmt: ## Auto-format code
	$(PYTHON) -m ruff check --fix services/
	$(PYTHON) -m ruff format services/

# ----------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------
clean: ## Remove build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ dist/ build/
