# Local code context

CodeGraph 0.20.1 (`@astudioplus/codegraph-mcp`, official repository https://github.com/codegraph-ai/CodeGraph) is installed in:

`C:\Users\vijay\AppData\Local\MedparkTools\codegraph`

The native Windows engine is configured for this project in `.codex/config.toml`. It indexes source locally, uses structural/name search without embeddings, and has telemetry explicitly disabled. No API key or cloud embedding service is required. Model/audio/data, dependencies, generated files, and audit outputs are excluded.

Restart the Codex MCP connection or reopen the project/session to load the new server. Project-scoped configuration requires a trusted project. The direct executable remains usable even before MCP configuration is reloaded.

## Efficient usage

1. Read `AGENTS.md` and the relevant section of `IMPLEMENTATION_STATUS.md`. Its "Not done" table is the current outstanding list; treat anything not listed under "Fixed and verified" as unverified.
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

## Extraction stage map (26 Sep 2026)

- Local LLM: Ollama native API on `http://127.0.0.1:11434`, alias `medpark-extractor` (Qwen3-4B-Instruct-2507 Q4_K_M, `deploy/ollama/Modelfile`). Details and measured numbers: `docs/LLM_EXTRACTION.md`.
- Modules under `backend/app/services/extraction/`: `llm_client.py` (health/assert_ready/complete_json/unload), `chunker.py` (`build_chunks`, `filter_chunk_items`), `merge.py` (`merge_items(items, text_key)`), `schemas.py` (`MAP_SCHEMA`, `SYNTHESIS_SCHEMA`), `prompt_templates.py`, `llm_engine.py` (`LocalLLMExtractor(client=None)`, `preflight`, `extract_minutes`), `heuristic_extractor.py` (degraded fallback), `validator.py` (`resolve_owner`, `audit_free_prose`, `evidence_validator`).
- Config: `LLM_*`, `REQUIRE_LOCAL_LLM`, `LLM_FALLBACK_MODE` in `backend/app/core/config.py`; all keys with defaults in `.env.example`.
- Tests: `backend/tests/test_llm_extraction_pipeline.py` (offline, FakeClient), `test_llm_extraction_live.py` (real Ollama, self-skipping). Scorer: `tools/eval/run_extraction_eval.py`; gold: `tools/eval/gold/` (format in `tools/eval/README.md`).
- Every test script that touches the repository/pipeline sets `DATA_DIR`/`UPLOADS_DIR`/`EXPORTS_DIR`/`FIXTURES_DIR`, a dead SMTP port and (where relevant) a dead LLM port **before** importing `app`; the repository and the Ollama client bind at import.

## Speaker identity map (26 Sep 2026)

- Design (read-only, with the adversarial corrections): `docs/SPEAKER_IDENTITY_DESIGN.md`. Status, thresholds, measured numbers and non-claims: `docs/VOICE_PROFILES.md`. Model provenance: `data/models/speaker/campplus/MODEL_CARD.md`.
- Models: `models/transcript.py` (`TranscriptSegment` four-state attribution, `SpeakerSuggestion`, `display_speaker`, legacy migration, `to_full_text(use_display_names=)`), `models/person.py` (`Person`, `ConsentRecord`, `Voiceprint`, `PersonSummary`, `SampleQuality`, `SpeakerAttributionEvent`, `SpeakerMap`, `compute_space_id`, `summarize_person`), `models/extraction.py` (`owner_source="confirmed_speaker"`, `EvidenceQuote.speaker_person_id/speaker_is_confirmed`).
- Diarization, `backend/app/services/diarization/`: `fbank.py` (exact Kaldi fbank + CMN), `embedder.py` (`speaker_embedder`, `.space_id`, `.model_sha256`, `embed_batch`), `clustering.py` (`agglomerative_cosine`, `two_means_split`, `diagnose_clusters`), `matching.py` (`score_clusters`, `pick_suggestion`, `merge_suggestions`), `enrollment.py` (`assess_sample`, `build_voiceprint`), `speaker_engine.py` (`EmbeddingDiarizer` as `diarization_engine`, `load_cached_embeddings`). The old at-chance `AcousticDiarizer` is gone from the labelling path.
- API: `api/v1/endpoints/people.py` (`/api/v1/voice-profiles`, consented enrollment, never from meeting audio) and `api/v1/endpoints/speakers.py` (`/api/v1/meetings/{id}/speakers`, `rematch`, `{cluster_id}/confirm` = the only write path for a name). `transcript.py` rejects non-anonymous `speaker` values (422). `/ready` reports `voice_id{enabled, reason, embedder_available, model, dim, space_id, enrolled_people}`.
- Storage: `repository.py` (`people.json`, `speaker_maps.json`; `delete_meeting` purges cached embeddings), `file_manager.py` (voiceprint / sample / segment-embedding paths under `VOICEPRINTS_DIR`, `purge_person_biometrics`, `purge_meeting_embeddings`). No vector ever enters a JSON store.
- Rendering and delivery: `documents/generator.py` (legend, `render_evidence_speaker`, `render_action_owner`, fail-closed against the stored transcript), `delivery/smtp_service.py` (`build_body`, `assert_no_person_names`, shared by `n8n_service.py`).
- Config keys `VOICE_ID_ENABLED`, `VOICEPRINTS_DIR`, `SPEAKER_*`, `ALLOW_AUTO_CONFIRM_SPEAKERS` in `core/config.py` and `.env.example`.
- Tests (offline, CPU, isolated storage): `backend/tests/test_speaker_embedder.py`, `test_voice_models_and_storage.py`, `test_delivery_body_has_no_names.py`, `test_speaker_confirmation_flow.py`, `test_speaker_diarization_groundtruth.py`, `test_voice_profiles_api.py`. GPU-gated end-to-end proof: `scripts/voice_e2e_gpu.py` (not yet run). Embedder gate: `scripts/verify_speaker_embedder.py [--real]`.
- Frontend: `frontend/src/components/voice/` (`PeoplePage`, `EnrollmentDrawer`, `VoiceProfileCard`, `ConsentNotice`, `SpeakerConfirmationPanel`), `api/client.ts` voice methods, `types/index.ts` (`VoiceProfile`, `SpeakerCluster`, attribution fields).

Official client configuration reference: https://developers.openai.com/codex/mcp
