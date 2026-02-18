# Frontend Chat Manual

## Goal
Run a lightweight junior-onboarding chat screen that uses:
- `POST /v1/chat`
- `POST /v1/feedback`
- `POST /v1/repos/onboard` (optional, disabled by default)

## 1. Start a Backend

### Option A: Quick local smoke backend (recommended first)
```bash
make mock-api
```
This starts `http://127.0.0.1:8090` with mock `/v1/chat` and `/v1/feedback`.

### Option B: Real backend
Use your deployed API base URL:
`https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`

Important:
- For generated answers (not retrieval-only fallback), deployed Lambda must include `LLM_ENABLED=true`.
- In Terraform dev env, set: `TF_VAR_llm_enabled=true` before `terraform apply`.
- For frontend repo onboarding, set `REPO_ONBOARDING_ENABLED=true` in backend env.
- For non-local repo onboarding, also set `API_AUTH_ENABLED=true` and provide `API_KEYS_JSON` with `repo_manage` permission.

## 2. Start the Frontend
```bash
make frontend
```
Open: `http://127.0.0.1:4173`

## 3. UI Setup
In the Connection panel:
1. `API Base URL`: `http://127.0.0.1:8090` (or your real API URL)
2. `API Key`: set only if `API_AUTH_ENABLED=true`
3. `Collection`: e.g. `default` or `ragops`
4. `Mode`: `explain_like_junior` for onboarding
5. `Answer Style`: `concise` for short summaries, `detailed` for deeper answers
6. `Top K`: `5` (or tune as needed)

Submit a question. The UI will:
1. Call `/v1/chat`
2. Render answer + citations
3. Let you send `Helpful` or `Needs Work` feedback to `/v1/feedback`

Optional repo onboarding flow:
1. Fill `GitHub Repo URL` and `Ref` in `Repo Onboarding`.
2. Click `Onboard Repo`.
3. UI calls `/v1/repos/onboard` in async mode and receives a `job_id`.
4. UI polls `/v1/repos/onboard` with `{"action":"status","job_id":"..."}` until completion.
5. On success, UI auto-sets the active code collection and you can chat against `<repo>_code`.

## 4. Quick API Test (without browser)
```bash
curl -sS -X POST http://127.0.0.1:8090/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Where should a junior start?","collection":"default","mode":"explain_like_junior","answer_style":"concise","top_k":5,"include_context":true}'

curl -sS -X POST http://127.0.0.1:8090/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"verdict":"positive","collection":"default","comment":"good citations"}'
```

## 5. CLI Commands and Flags

### Chat
```bash
python -m services.cli.main chat "How should I learn this codebase?" \
  --mode explain_like_junior \
  --answer-style concise \
  --collection ragops \
  --top-k 5 \
  --show-context \
  --session-id <optional-session-id> \
  --api-url <optional-remote-url> \
  --api-key <optional-api-key> \
  --json
```

Key flags:
- `--mode`: `default|explain_like_junior|show_where_in_code|step_by_step`
- `--answer-style`: `concise|detailed`
- `--session-id`: continue an existing thread
- `--show-context`: request/print raw retrieved snippets
- `--api-url`: target remote `/v1/chat`
- `--api-key`: sends `X-API-Key`
- `--json`: machine-readable output

### Feedback
```bash
python -m services.cli.main feedback \
  --verdict positive \
  --collection ragops \
  --session-id <optional-session-id> \
  --mode explain_like_junior \
  --question "Where should I start?" \
  --answer "Start with services/cli/main.py" \
  --comment "very clear" \
  --citations-json '[{"source":"services/cli/main.py","line_start":1,"line_end":120}]' \
  --metadata-json '{"source":"frontend"}' \
  --api-url <optional-remote-url> \
  --api-key <optional-api-key> \
  --json
```

### Eval
```bash
python -m services.cli.main eval \
  --dataset ./eval/cases.yaml \
  --collection ragops \
  --top-k 5 \
  --output-json ./eval/eval-report.json \
  --output-md ./eval/eval-report.md \
  --json
```

## 6. Can this read GitHub repos?
Yes.

Supported options:
- CLI flow: `repo add` / `repo sync` (git clone/pull on a local machine)
- Frontend/API flow: `/v1/repos/onboard` (downloads GitHub archive, no local git required)

Notes:
- `/v1/repos/onboard` is disabled by default.
- In non-local deployments, repo onboarding requires `API_AUTH_ENABLED=true` + `X-API-Key`.
- It targets GitHub URLs and is optimized for public repos.
- For private repos, configure `GITHUB_TOKEN` in backend environment.
- Large repos should use async onboarding (default in UI) to avoid API timeout.

## 7. Troubleshooting

- If UI shows `TypeError: Failed to fetch`, verify `API Base URL` is the exact stage URL from Terraform output:
  `terraform output -raw api_url`
- If `/health` works but `/v1/chat` returns `404 Not found`, redeploy API Gateway + Lambda.
- If answers look like raw code dumps, click `New Session` (old bad history can poison follow-ups), then retry.
