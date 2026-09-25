# Local code context

CodeGraph 0.20.1 (`@astudioplus/codegraph-mcp`, official repository https://github.com/codegraph-ai/CodeGraph) is installed in:

`C:\Users\vijay\AppData\Local\MedparkTools\codegraph`

The native Windows engine is configured for this project in `.codex/config.toml`. It indexes source locally, uses structural/name search without embeddings, and has telemetry explicitly disabled. No API key or cloud embedding service is required. Model/audio/data, dependencies, generated files, and audit outputs are excluded.

Restart the Codex MCP connection or reopen the project/session to load the new server. Project-scoped configuration requires a trusted project. The direct executable remains usable even before MCP configuration is reloaded.

## Efficient usage

1. Read `AGENTS.md` and the relevant section of `IMPLEMENTATION_STATUS.md`.
2. Use `codegraph_symbol_search` with `query`, `compact: true`, and `limit: 5`.
3. Request `codegraph_get_ai_context` or `codegraph_get_detailed_symbol` for only the selected result.
4. Check its source and targeted tests. Use `rg` when searching exact text or if the graph misses a symbol.

The `core` profile exposes eight tools instead of the entire tool catalog. This is intended to reduce repeated discovery and irrelevant context; no percentage of token savings has been measured or guaranteed.

## Verification and limitations

- MCP initialize succeeded and reported version 0.20.1.
- `tools/list` returned the eight core tools.
- Symbol lookup successfully found `run_pipeline` in `backend/app/services/pipeline_orchestrator.py`.
- Six TSX files produced partial parser warnings around literal JSX `&` text, even though the TypeScript/Vite build passes. The graph still extracts symbols from the rest of those files; verify frontend relationships against source.
- Semantic search is deliberately unavailable in graph-only mode. A generic result banner claiming embeddings are building is misleading in this mode.
- Persistent code data lives in the local CodeGraph cache. New sessions re-index/load the workspace; restart the connection if a just-edited symbol appears stale.

Official client configuration reference: https://developers.openai.com/codex/mcp
