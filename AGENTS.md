# Medpark: concise context for coding agents

## Start here
- This repository is an existing prototype, not the unimplemented production architecture discussed in earlier chat.
- Read `docs/IMPLEMENTATION_STATUS.md` for verified behavior, gaps, and test limitations. Recheck affected code before relying on dated findings.
- User requirement: review before any email. The backend and intake defaults are now `supervised`, but `auto_pilot` is still selectable and `deploy/scripts/benchmark_speed.py` hardcodes it. Do not send hospital email while testing.
- Preserve the user's implementation. Audit/configuration work does not authorize rewriting the app.

## Navigate without loading the whole repository
- Project-local CodeGraph MCP is configured in `.codex/config.toml`; see `docs/CODE_CONTEXT.md`.
- For symbol/relationship questions, query `codegraph_symbol_search` with `compact: true, limit: 5`, then request context only for the selected symbol.
- Use a bounded context budget when the selected tool supports one. Do not dump the complete graph or all tool schemas.
- For literal text/files, use targeted `rg` first. Read only the affected module and its immediate consumers/tests.
- The graph is an aid, not ground truth: this release reports partial TSX parsing around some JSX ampersands. Confirm behavior in source.
- Do not index or include `.venv`, `node_modules`, `dist`, `.audit`, `data`, model weights, recordings, exports, credentials, or IDE caches in agent context.

## Implementation map
- Backend: FastAPI; entry `backend/app/main.py`; API `backend/app/api/v1/endpoints`.
- Pipeline: `backend/app/services/pipeline_orchestrator.py`.
- Speech: `services/audio`, `services/asr`, `services/diarization` under `backend/app`.
- Minutes: `services/extraction`, `services/documents`; mail: `services/delivery`.
- State: JSON files via `backend/app/storage/repository.py`. No PostgreSQL/Redis/job worker exists yet.
- Frontend: React/Vite/TypeScript; `frontend/src/App.tsx`, `api/client.ts`, `types/index.ts`, `components`.
- Deployment: `deploy/docker-compose.yml`, `deploy/Dockerfile`, `deploy/n8n`.

## Run and verify
- Python: `F:\DEEPTECH\.venv\Scripts\python.exe` (currently Python 3.13).
- Run from repository root: `.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`.
- Set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_HUB_DISABLE_TELEMETRY=1` for local inference checks.
- Frontend build: `npm.cmd run build` in `frontend`; API serves the resulting `frontend/dist`.
- Existing tests are executable scripts under `backend/tests`; set `PYTHONPATH=backend`. Their passing status does not prove inference quality or delivery.
- Isolate tests with **environment variables**, not by assigning to `settings` at runtime: set `DATA_DIR`, `UPLOADS_DIR`, `EXPORTS_DIR`, `FIXTURES_DIR` to a temp directory before the process starts. Derived settings do not follow a DATA_DIR override, and the `repository` singleton resolves its store at import, so a runtime assignment (what `backend/tests` currently does) still writes into `data/store`. Reuse only MODELS_DIR if needed.
- Test with supervised workflow and local-only SMTP (`SMTP_HOST=127.0.0.1 SMTP_PORT=9`, `ALLOW_SIMULATED_DELIVERY=false`); never benchmark by emailing actual participants.
- Update the status/context documents only when new verification changes their facts. Keep summaries short and link evidence.
