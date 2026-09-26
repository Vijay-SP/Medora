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

## Inline attribution map (26 Sep 2026, contracts N1-N7)

- What and why, the reviewer's before/after view, what auto-pilot can never do, why storage keeps labels: `docs/INLINE_ATTRIBUTION.md`.
- Stored prose names people only through anonymous tokens (`S2 a propus ...`); names are substituted at READ time. Render layer: `backend/app/services/extraction/attribution_render.py` (`LABEL_RE`, `SPEAKER_RE`, `ANON`, `build_label_map(transcript, locale)`, `render_text`, `render_minutes(minutes, transcript)` = deep copy). Consumers: `api/v1/endpoints/review.py` (`GET /minutes?names=resolved|labels`, resolved `/translate`, `PUT` that restores stored tokens for unedited fields and un-renders edited ones via `_restore_stored_tokens`), clinical `S<n>` guard (`is_speaker_label`, shared with `validator` and `translation_service`), `documents/generator.py` (`_render_for_print`), the e-mail path is untouched (names only inside attachments).
- Extraction side: `prompt_templates.py` (facilitator style, labels as the only allowed naming, labelled synthesis), `schemas.py` (`speakers` per item), `merge.py` (speakers union), `validator.py` (`ground_speaker_labels`, `ground_labels_in_text`), `llm_engine.py` (grounding pass, summary grounding, `speaker_label_style="labels"`, `NOTĂ AUDIT` on repair). `translation_service.py` pins labels in the prompt and falls back per field (`_keep_labels`).
- Models: `models/extraction.py` (`MinutesOfMeeting.speaker_label_style`), `models/transcript.py` (`attribution_basis`, relaxed `corrected` invariant). Reviewer labels: `api/v1/endpoints/speakers.py` (action `label`, `display_label`/`attendee_id`, `validate_label`, `resolve_label`, `build_label_options`, `SpeakerCluster.label_options` / `current_label`).
- Frontend: `components/voice/SpeakerConfirmationPanel.tsx` (three-section "Someone else" menu, "Assigned —" state), `api/client.ts` (`getMinutes(id, names?)`, `confirmSpeaker` with label fields), `types/index.ts`.
- Tests (offline, isolated storage, dead LLM/SMTP ports): `backend/tests/test_inline_attribution.py` (FakeClient), `test_speaker_label_action.py` (TestClient, synthetic embedding cache, PDF text via `scripts/voice_e2e_gpu.py::pdf_text`), `test_translation_service.py` (fake client through `translation_service._client`).

## ASR code-switching map (26 Sep 2026, contracts K1-K6)

- Why and what was measured: `docs/ASR_CODE_SWITCHING.md`. The single whole-file `model.transcribe(language=None)` pass is gone; the engine now decodes VAD-packed windows with a per-window language identification restricted to `WHISPER_LANGUAGES`.
- Engine, `backend/app/services/asr/`: `whisper_engine.py` (`FasterWhisperEngine.transcribe(audio_path, initial_prompt=None, language=None)` signature unchanged; `initial_prompt` ignored with one WARNING; `.last_run_stats`; `DECODE_OPTIONS`; pure helpers `restrict_language_probs`, `needs_rescoring`, `garbage_reason`, `stitch_segments`, `build_transcription_options`; `MedparkBatchedPipeline` = `BatchedInferencePipeline` with the restricted per-chunk LID for `WHISPER_STRATEGY=batched`; garbage filter flags `low_confidence_asr`, never deletes), `windowing.py` (`VAD_OPTIONS`, `DecodeWindow`, `pack_windows`), `text_lid.py` (`detect_text_language`, `language_spans`), `lexicon.py` (`CLINICAL_LEXICON`, `correct_segment`), `glossary.py` (`HOTWORDS_BY_LANG` <= 80 tokens per language, `MEDPARK_MEDICAL_VOCABULARY` for the review-flag regexes; `build_code_switch_prompt` is a deprecated stub returning `""`).
- Models: `models/transcript.py` (`LanguageSpan`, `Correction`, `TranscriptSegment.language_confidence / language_source / language_spans / corrections / window_index / asr_avg_logprob / asr_compression_ratio / asr_no_speech_prob`, all defaulted; `compute_stats` drops `und`, expands `mixed`), `models/meeting.py` (`Meeting.asr_stats`).
- Config: `WHISPER_STRATEGY`, `WHISPER_LANGUAGES`, `WHISPER_BATCH_SIZE`, `WHISPER_CHUNK_LENGTH_S`, `ASR_WINDOW_*`, `ASR_LID_RESCORE_BELOW`, `ASR_HOTWORDS_ENABLED`, `ASR_LEXICON_ENABLED`, `ASR_GARBAGE_*` in `core/config.py` and `.env.example`.
- Integration: `pipeline_orchestrator.py` copies `whisper_engine.last_run_stats` into `meeting.asr_stats` after Stage 2; `main.py` `/ready.asr_service` reports `resolved_device`, `strategy`, `languages`, `code_switching`; `documents/generator.py` prints "Limbi detectate" and per-language segment counts.
- Frontend: `types/index.ts` (optional K1 fields, `asr_stats`), `components/TranscriptViewer.tsx` (RO/RU/EN/RO·RU/?? chips, language filter from the languages present, "corrected" marker with a `was -> now` tooltip), `SettingsView.tsx` (resolved device / strategy / languages from `/ready`).
- Tests (offline, no CUDA, no `WhisperModel`): `backend/tests/test_asr_text_lid_and_windowing.py`, `backend/tests/test_asr_engine_options.py` (fake model). GPU A/B: `scripts/asr_ab_benchmark.py` (refuses to run with > 1000 MiB VRAM in use or an Ollama model loaded).
- GPU exclusivity: Whisper (~2 GB) and the Ollama LLM (~2.7 GB) do not fit together in 4 GB; never run two Whisper processes either. Check `nvidia-smi` and `curl http://127.0.0.1:11434/api/ps` before any GPU run.

Official client configuration reference: https://developers.openai.com/codex/mcp
