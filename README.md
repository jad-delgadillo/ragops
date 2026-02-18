# RAG Ops Platform

A robust, serverless-ready, and developer-first Retrieval-Augmented Generation (RAG) platform.

**RAG Ops** lets you query any codebase or document collection using AI. It can be run locally with Docker or deployed to AWS for production use.

## 🚀 Vision

- **Local-First**: Run everything on your machine with Docker.
- **Auto-Documentation**: Generates READMEs, Architecture, and API docs from your source code.
- **Multiproject**: Scope knowledge and queries to specific projects.
- **Serverless-Ready**: Designed for AWS Lambda + Aurora Serverless v2.

## 🛠️ Quick Start (Docker)

The fastest way to get started is using Docker Compose.

1.  **Configure Environment**:
    ```bash
    cp .env.example .env
    # Edit .env and add your OPENAI_API_KEY
    ```

2.  **Start Database**:
    ```bash
    docker compose up -d postgres
    ```

3.  **Initialize Project**:
    ```bash
    docker compose run --rm ragops init
    ```

4.  **Ingest Code & Docs**:
    ```bash
    docker compose run --rm ragops ingest
    ```

5.  **Query**:
    ```bash
    docker compose run --rm ragops query "How does the ingestion pipeline work?"
    ```

6.  **Chat (multi-turn onboarding)**:
    ```bash
    docker compose run --rm ragops chat "Explain this project for a junior engineer" --mode explain_like_junior
    ```

7.  **Submit Feedback (quality loop)**:
    ```bash
    docker compose run --rm ragops feedback --verdict positive --comment "Clear answer with good citations"
    ```

8.  **Auto-Generate Docs**:
    ```bash
    docker compose run --rm ragops generate-docs --output ./docs
    ```

9.  **Generate Onboarding Manuals**:
    ```bash
    docker compose run --rm ragops generate-manuals --output ./manuals
    # Optional: ingest the manual pack for Q&A
    docker compose run --rm ragops generate-manuals --output ./manuals --ingest
    ```

10. **Run Dataset Evaluation**:
    ```bash
    python -m services.cli.main eval --dataset ./eval/cases.yaml
    ```

11. **Run Frontend Onboarding Chat**:
    ```bash
    make mock-api
    make frontend
    ```
    Open `http://127.0.0.1:4173` (manual: `docs/frontend-chat-manual.md`)

12. **Connect a GitHub Repo (clone + ingest + chat)**:
    ```bash
    python -m services.cli.main repo add https://github.com/<org>/<repo> --ref main --generate-manuals
    python -m services.cli.main chat "What is this project about?" --collection <owner-repo>_code
    # Generated manuals are isolated in: <owner-repo>_manuals
    ```

## 🏗️ Architecture

- **Vector Store**: Postgres 16 + `pgvector`.
- **Backend**: Python 3.11 logic.
- **Infrastructure**: Terraform for AWS (Lambda, API Gateway, S3).
- **CLI**: Rich terminal interface with spinners and markdown rendering.

## 📁 Project Structure

```text
.
├── services/
│   ├── api/            # Query API and Retriever
│   ├── ingest/         # Ingestion Pipeline and Chunker
│   ├── core/           # Shared models, db, and config
│   └── cli/            # ragops command-line tool
├── terraform/          # IaC for AWS Deployment
├── docs/               # Manual and auto-generated docs
└── docker-compose.yml  # Local development environment
```

## 📜 License

MIT
# ragops
