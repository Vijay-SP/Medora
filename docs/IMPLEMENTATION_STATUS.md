# Medpark / Medora implementation status

Last revised: 26 September 2026, after the speaker-identity pass (CAM++ voiceprints, four-state attribution, contracts V1-V10) on top of the local-LLM extraction pass (contracts C1-C16).
This document describes only what was checked against current source. It is not a plan.

## How this was verified

| Check | Result |
|---|---|
| `backend/tests/test_voice_models_and_storage.py` (new, offline) | 14/14: four attribution states and every illegal combination raise, legacy rows (`speaker="Dr. Ceban"`, stale `speaker_id`) migrate to anonymous idempotently, `display_speaker` honours the printable floor, all 248 segments of the `.audit/real-run` transcript load anonymous, people / speaker-map CRUD, biometric path validation, purge cascades (`delete_meeting` removes cached embeddings), no JSON store contains a float vector |
| `backend/tests/test_delivery_body_has_no_names.py` (new, offline, `aiosmtplib.send` + `httpx` mocked) | 6/6: `build_body` and the subject carry no roster / confirmed / mentioned / suggested name; the real SMTP path puts names only in the attachments (DOCX checked); a title with a name is refused (`FAILED`, send never called); the n8n payload carries no name and no `summary_ro` |
| `backend/tests/test_speaker_confirmation_flow.py` (new, offline TestClient, synthetic embedding cache) | 7/7 after two fixture corrections (noise scale, duplicate people between scenarios): GET /speakers cards, 409 on wrong `expected_revision` / blocked cluster / same person without `correct`, 400 without `profile_id`, happy confirm writes segments + evidence + owners + event and regenerates Rev1 in place, APPROVED -> Rev2 with sign-off cleared, a delivery record for the current revision -> Rev3, reject reverses, correct replaces, `unknown` anonymises, rematch keeps confirmations and re-suggests from the cache |
| `backend/tests/test_speaker_diarization_groundtruth.py` (new, SAPI voices, CPU) | 6/6: 12/12 segments in the right cluster (accuracy 1.000), two dominant clusters hold > 90% of speech, the standalone 1.0 s turn becomes its own `short_suspect` cluster (over-split by design), both voices enrolled from separate prompts yield suggestions with cosine 0.954-0.974 and margin >= 0.08, an unenrolled voice gets none, confirming cluster A through the API prints the name only on turns >= 2.0 s and leaves cluster B byte-identical |
| `backend/tests/test_voice_profiles_api.py` (new, SAPI voice, CPU) | 3/3: 422 before consent, 1 s / silent / 40x-clipped clips rejected with nothing stored, `.txt` -> 400, three ~15 s prompts -> `enrolled` (one `.npy`, three WAVs), status endpoint truthful, no vector in any store, wipe -> `not_enrolled`, consent withdrawal and delete purge the files, no route enrols from meeting audio, a child process with a missing ONNX returns 503 and `/ready.voice_id.enabled=false` with reason "missing" |
| `scripts/voice_e2e_gpu.py` (new, GPU-gated) | **Not run** (GPU reserved during the build phase). Only its PDF text extractor was exercised on an existing export (1,839 chars, names and `Vorbitor N` labels recovered) |
| `npm.cmd run build` in `frontend` | Passed (tsc + vite), re-run 26 Sep after the extraction pass |
| `backend/tests/test_llm_extraction_pipeline.py` (new, offline, FakeClient) | 15 tests passed: indexed lines, chunker, merge, `resolve_owner`, `audit_free_prose`, full `extract_minutes`, failed-chunk accounting, ratio abort, mid-run outage, kill switch |
| `backend/tests/test_llm_extraction_live.py` (new, real Ollama) | Passed in 29-39 s wall: one decision on lines 4/5, roster owner from "doctorul Popescu", `până luni`/`by Friday` resolved, risk found, `needs_name_review=False`; prints `SKIPPED` when `/api/version` fails. Re-run 26 Sep (critic pass): same items, but 102 s wall because the first map call took 94 s including a cold model load (the second call took ~7 s); `/api/ps` was empty afterwards, so `unload()` in the `finally` works |
| `backend/tests/test_speech_server.py` (new, offline) | 4/4 passed: durable SQLite queue, idempotency, byte limit (413), queue capacity limit (429), engine unready (503), bearer token auth, job lifecycle (GET/DELETE with 204/404/409), restart recovery |
| `backend/tests/test_whisper_cpp_engine.py` (new, offline) | 5/5 passed: CLI argument construction (--vad, --max-context 0, --output-json-full), monotonic timestamps, token confidence parsing, timeout termination, Metal/CPU device provenance |
| `backend/tests/test_remote_asr_engine.py` (new, offline) | 1/1 passed: polls opaque job URL, converts to anonymous TranscriptSegments, discards server speaker metadata, raises on network error/timeout |
| `backend/tests/test_asr_engine_selection.py` (new, offline) | 5/5 passed: factory provider switching (faster_whisper, whisper_cpp, remote), /ready probe reporting truthful connectivity and queue metrics |
| Live ASR verification (native Mac M4 Metal) | whisper-cli + large-v3-turbo (1.5GB) + Silero VAD (864KB) executed on Metal GPU; transcribed 5-second Romanian sample in 2.5s with timestamps and language detection (`ro`) |
| Storage during tests | `DATA_DIR`/`UPLOADS_DIR`/`EXPORTS_DIR`/`FIXTURES_DIR`/`VOICEPRINTS_DIR` set as **environment variables** to a temp directory before import; each test script now sets them itself when absent. `VOICEPRINTS_DIR` must be set separately: its default is the class-time `DATA_DIR/"voiceprints"` and does not follow a `DATA_DIR` override |
| SMTP during tests | `SMTP_HOST=127.0.0.1 SMTP_PORT=9`, `ALLOW_SIMULATED_DELIVERY=false`, `aiosmtplib.send` mocked; no mail left the host |
| `tools/eval/run_extraction_eval.py` on `tools/eval/gold/synthetic_trackA.json` | FakeClient minutes and live minutes both score P/R/F1 1.00 on decisions and actions, 0.00 false-decision rate, 0.00 owner fabrication, 1.00 deadline recall, 1.00 evidence validity |

Passing tests still do not demonstrate ASR quality or real delivery. The end-to-end test mocks
`whisper_engine.transcribe` and `aiosmtplib.send`; the live LLM test covers an 11-line synthetic
fragment, not a 60-minute recording. See `docs/LLM_EXTRACTION.md` for the measured LLM numbers.

## Fixed and verified in source

Storage and API
- `repository._read_json` no longer swallows errors; corrupt or non-object store files raise instead of silently returning `{}`.
- `repository._write_json` uses a unique temp filename per writer.
- `save_meeting` refreshes `updated_at`; `delete_meeting` now cascades to transcript, minutes, deliveries, and on-disk artifacts via `file_manager.purge_meeting_artifacts`.
- `file_manager` validates `meeting_id` against `^[A-Za-z0-9_-]{1,64}$` before joining it into any path.
- Domain exceptions are mapped to HTTP status codes in `main.py`, so a rejected upload returns 400 and an unknown/unsafe id returns 404 instead of 500.
- CORS no longer appends `"*"` alongside `allow_credentials=True`.
- `/ready` reports `llm_service: {endpoint, engine, model, connected, loaded, mode}` via `llm_client.health()` (`/api/version` + `/api/tags`, never loads the model) and `/api/ps` for `loaded`; `ready` is false when `REQUIRE_LOCAL_LLM` and the LLM is not connected. Lifespan logs CRITICAL (does not exit) in that case.
- `/docs` and `/redoc` no longer reference a CDN: they render from bundles vendored under `backend/app/static/docs` when present, otherwise from a self-contained offline route table. No bundle is vendored today, so the interactive Swagger UI is not available, only the offline reference.
- `/audio/stream` returns the real container MIME type; upload is non-blocking, rejects replacement during an active run, deletes the previous recording, and resets `normalized_audio_path`, duration, error and review state.

Pipeline
- Every blocking stage (normalize, transcribe, diarize, document generation) runs via `asyncio.to_thread`; the event loop is no longer held for the whole run.
- `POST /pipeline/start` persists `PREPROCESSING`/5 before scheduling the background task, so an immediate `/status` poll cannot return the previous run's result and a second start is rejected.
- Concurrency guard uses `ACTIVE_PROCESSING_STATUSES`, derived from the terminal states.
- A re-run bumps the revision (`_next_revision`) instead of overwriting Rev1 exports; `error_message` is cleared at the start of a run.

Extraction (local LLM, 26 Sep)
- `services/extraction/llm_client.py`: Ollama native API client (`health` never loads the model; `assert_ready` returns the provenance string; `complete_json` uses `format:<JSON Schema>`; `unload` frees VRAM). Config keys `LLM_*`, `REQUIRE_LOCAL_LLM=true`, `LLM_FALLBACK_MODE=fail` in `core/config.py`; the old llama.cpp `:8080/v1` keys are gone.
- `llm_engine.py`: `preflight()` runs before Stage 1 in the orchestrator (3 s failure instead of after ASR); `extract_minutes` renders `Transcript.to_indexed_lines()`, chunks (`chunker.py`, budget floored at 256 tokens, never splits a line), maps sequentially, merges (`merge.py`), one synthesis call, copies evidence from the cited segments, then `validate_and_enrich`, `resolve_owner`, `audit_free_prose`; `unload()` in a `finally`. `LocalLLMExtractor(client=...)` accepts a fake client for tests.
- Failure policy: one repair turn per chunk (seed+1), `failed_chunks` + "NOTĂ AUDIT" item, `ExtractionError` above `LLM_MAX_FAILED_CHUNK_RATIO`, `LLMUnavailable` aborts. Verified offline in `test_llm_extraction_pipeline.py`.
- Heuristic parser moved to `heuristic_extractor.py`; stamps `is_degraded=True`, `model_version="DEGRADED-heuristic-no-LLM"`; `delivery_router.assert_dispatchable` refuses it at both dispatch sites (auto-pilot holds at `PENDING_REVIEW` with `error_message`; approval returns 409). Verified in `test_end_to_end_pipeline.py`.
- Name guard: a fabricated `owner_mention` is discarded (must be a substring of the cited lines); non-roster names and unknown capitalised runs set `needs_name_review`. Known wart: an English first-person speaker yields `owner_mention="I"` -> anonymous `Speaker N`.
- Earlier fixes retained: the evidence check requires timestamp overlap for any match against the cited segment (word-overlap escape hatch 0.90); multi-word temporal phrases are matched before day names, and day names use word boundaries, so "sfârșitul lunii" no longer resolves to next Monday.

Speaker identity (26 Sep, contracts V1-V10; details in `docs/VOICE_PROFILES.md`)
- `models/transcript.py`: four-state attribution (`anonymous` / `suggested` / `confirmed` / `corrected`) enforced by validators; `speaker` is always `Speaker N`; `display_speaker` prints a name only when `printable_name` (confirmed/corrected **and** >= 2.0 s of VAD speech); legacy rows migrate on load. `to_indexed_lines()` (the LLM prompt) and `to_full_text()` never carry a name; `to_full_text(use_display_names=True)` is the only named rendering.
- `models/person.py`, `repository.py` (`people.json`, `speaker_maps.json`), `file_manager.py` (voiceprint / sample / segment-embedding paths under `VOICEPRINTS_DIR`, purge helpers): vectors live only in `.npy` files; `delete_meeting` and a new upload purge the cached segment embeddings.
- `services/diarization/`: the at-chance `AcousticDiarizer` is replaced by `EmbeddingDiarizer` (Silero VAD -> windows <= 8 s -> CAM++ embeddings -> deterministic average-linkage AHC at cosine distance 0.45 -> per-cluster 2-means / region-count probes -> largest-overlap labelling, straddling segments flagged). Suggestions come from `matching.py` (independent open-set scoring, no forced assignment, merge suggestions); the diarizer only ever writes `anonymous` / `suggested`. Without the ONNX every segment stays `Speaker 1` with a WARNING.
- API: `/api/v1/voice-profiles` (consented enrollment with verbatim `SampleQuality`, rebuild from all stored samples, wipe / withdraw / delete purge files, 503 without the embedder, nothing enrols from meeting audio) and `/api/v1/meetings/{id}/speakers` (`GET`, `rematch` from the cache, `{cluster}/confirm` = the only write path: 409 on revision mismatch / blocking reasons / same person without `correct`, snapshot name, `printable_name` per segment, evidence and owner rewrite only for printable segments, audit event, revision bump when approved/delivered). `PUT /transcript/segments/{id}` rejects non-anonymous `speaker` values.
- Orchestrator passes `meeting_id` and `repository.list_people()` to the diarizer and raises `DiarizationError` in `AUTO_PILOT` if any segment leaves diarization confirmed. `/ready` reports `voice_id` (enabled only when the flag is on **and** the ONNX loads; a missing model reports `reason="embedder model missing"` instead of crashing).
- Documents: evidence speakers and owners are re-checked against the stored transcript at render time; a legend with the confirmed names, reviewer and time prints only when a printable segment exists; no suggestion, score or unconfirmed name is ever printed. Email: `build_body` (counts + attachments only) and `assert_no_person_names` on subject and body for both channels.
- Frontend: `components/voice/` (PeoplePage, EnrollmentDrawer, VoiceProfileCard, ConsentNotice, SpeakerConfirmationPanel), "People & Voices" navigation and a `speakers` tab, both hidden when `/ready.voice_id.enabled` is false; `npm run build` passes. No browser walkthrough was recorded. Known break: the client calls `/api/v1/voice-profiles` without the trailing slash `people.py` registers, and the SPA mount at `/` returns 404/405 instead of redirecting, so listing/creating profiles from the UI fails (see `docs/VOICE_PROFILES.md`, Known gaps).

Review and delivery
- `DeliveryStatus` is imported in `review.py`; approval no longer raises `NameError`.
- Approval requires `processing_status == COMPLETED`, refuses an already-`DELIVERED` meeting, and accepts an optional `expected_revision` precondition.
- `PUT /minutes` rejects a write whose revision is behind the stored revision.
- Both channels address one recipient list resolved by `delivery_router`; `n8n_service` always returns a `DeliveryRecord`, recording `FAILED` with a reason instead of returning `None`.
- A custom `distribution_list` is an exclusive override of the department policy.
- Approval and SMTP timestamps are timezone-aware UTC.
- Added `GET /deliveries/{id}/attachment/docx` so the outbox can serve the exact dispatched revision.

Frontend
- Approval toast reports the real delivery outcome; `approved`-but-not-delivered is a distinct state in the KPI row, the status filter, the meeting header and the chips.
- `error_message` is rendered for both pipeline failure and delivery failure.
- Outbox downloads are delivery-scoped, show `error_message`, distinguish a fetch failure from an empty outbox, and have a refresh control and a race guard.
- Global `Space` no longer calls `preventDefault` on a focused button/link; single-letter shortcuts are suppressed while any overlay is open; `Escape` closes the topmost overlay.
- All five overlays have `role="dialog" aria-modal="true"`, a label, initial focus, a Tab trap and backdrop handling.
- The audio file input is `sr-only`, not `display:none`, so it is keyboard reachable.
- The sign-off modal no longer pre-fills a clinician's name, and shows what is being signed.
- API calls are bounded by an `AbortController` timeout.
- `ActionItemsTable` resyncs from props; the completion toggle is now labelled as a local view aid because it is still not persisted.
- `medpark-200/300/800` usages were removed; those shades are still absent from the theme, which is now consistent.

## Not done

These were in scope for the fix pass and are unchanged in source.

| Area | What remains |
|---|---|
| Test isolation | `test_extraction_and_grounding.py`, `test_end_to_end_pipeline.py`, `test_llm_extraction_pipeline.py` and `test_llm_extraction_live.py` now set the storage/SMTP/LLM env vars themselves before importing `app`, and the E2E suite calls `repository.reconfigure()`. The E2E suite also isolates `VOICEPRINTS_DIR` (env before import plus `settings.VOICEPRINTS_DIR` per test) and asserts that `file_manager.get_segment_embedding_paths(meeting.id)` resolves inside the temp tree and that `data/voiceprints/meetings/<id>` never appears; before this it only escaped a write into the repository store because the noise fixture carries no VAD speech. `test_models.py`, `test_audio_processing.py` and `test_document_generation.py` are unchanged and still need the env vars set by the caller. |
| ASR | `whisper_engine` stamps `info.language` on every segment (no per-utterance detection); `_check_review_flags` substring-matches `ATI`/`CT`, flagging ordinary sentences; the decoder prompt ignores agenda and attendees. |
| Glossary | `glossary.py` slices `[:25]`/`[25:40]` do not match the language blocks; the "Термины" section is part Romanian, and 13 Russian plus all 17 English terms are never used. |
| Diarization | The acoustic-feature diarizer is gone (replaced by the CAM++ embedding diarizer). Open: no diarization error rate exists for the real far-field recording (only cosine ranges and the 0.45 distance that separates two alternating speakers); a person's Romanian and Russian turns may form separate clusters (reported as a merge suggestion, never merged automatically); `scripts/voice_e2e_gpu.py` has not been run. |
| Voice privacy preconditions | Design §7 is not implemented: voiceprints are plain `.npy` files, there is no authentication, RBAC, app-layer encryption or DPIA hash check; `VOICE_ID_ENABLED` is a plain config flag (default `true`). Consent is a checkbox stored in `people.json`. |
| VAD | `max_chunk_duration` is only a merge guard; long utterances are never split. The comment above the merge loop still claims splitting happens. |
| Documents | Only the fixed-string section headers (`REZUMAT EXECUTIV`, `DECIZII ADOPTATE (n)`, the date/type/revision line, the empty-section notes) still use `cell()`; harmless because their length is bounded. Variable-length content (title, decisions, owners, evidence, legend) uses `multi_cell`, `truncate_quote` appends `"..."` only when it cuts, and bold/italic faces are registered per Unicode family via `PDFReport._register_style` (falling back to plain when the bold/italic file is absent). |
| Logging | `PrivacyFilter` truncates everything after `Bearer ` rather than redacting the token. |
| API docs | Interactive Swagger UI / ReDoc need the bundles copied into `backend/app/static/docs`; until then the offline route table is served (no CDN request either way). |
| Frontend stale copy | `SettingsView.tsx` still advertises "Qwen-2.5-7B-Instruct (GGUF / Local)" and "Fallback Semantic Engine: Regex & Grammar Grounding Active"; neither exists. `SessionWorkspaceView.isFallbackExtraction` keys on a `fallback` substring, so its amber banner never fires for `DEGRADED-heuristic-no-LLM` (the `App.tsx` banner keyed on `is_degraded` covers it). `RisksQuestionsTable` prefixes every `NOTĂ AUDIT` row with "the neural model did not run", which is wrong for the LLM path's own audit notes (failed chunks, unverified names, failed synthesis). `ActionItemsTable` does not yet show `owner_source`. |
| Review edit bypass | `PUT /minutes` re-validates the whole `MinutesOfMeeting` from the payload: a payload without `is_degraded` (or with `model_version` changed) resets the flag to `False`, and `POST /review/approve` then passes `assert_dispatchable` (verified with `TestClient` 26 Sep: 409 before the PUT, 200 after). The UI spreads the fetched minutes so it keeps the flag, but the server must carry `is_degraded`, `model_version`, `extraction_stats`, `failed_chunks` over from the stored revision. |
| Tailwind | Six `shadow-xs`/`shadow-2xs` (Tailwind v4 names) remain in `TranscriptViewer.tsx` and `WaveformPlayer.tsx`; `animate-in` and its 10 companion `fade-in`/`zoom-in-95`/`slide-in-from-right*` classes across 6 components are dead without `tailwindcss-animate` (`plugins: []`), so all four modals, the drawer and every toast appear with no transition. |
| Accessibility | No `<h1>`, no skip link, `<main>` has no accessible name. |
| Deployment | `.dockerignore`, `RELOAD=false`, the HF offline variables, loopback-only Mailpit/n8n ports, n8n basic auth and a consistent `DELIVERY_CHANNEL=smtp`/`N8N_ENABLED=false` pair are now in place. Still open: `docker-compose.yml` has no Ollama service and does not set `LLM_API_BASE_URL`, so inside the container the default `http://127.0.0.1:11434` is the container itself and, with `REQUIRE_LOCAL_LLM=true`, every pipeline run fails at preflight; the image is `python:3.12-slim` with no CUDA and no GPU reservation, so Whisper runs on CPU; `mailpit:latest` / `n8n:latest` / base images are unpinned; the Whisper weights volume is `../data`, the Ollama store is not mounted at all. |
| n8n workflow | `deploy/n8n/medpark_routing_workflow.json` has three `emailSend` nodes with no credentials, no attachments and no fallback branch. It cannot deliver. |
| Benchmark | `deploy/scripts/benchmark_speed.py` now builds a `SUPERVISED` meeting with `@benchmark.invalid` attendees, so it never dispatches. It still writes to whatever `DATA_DIR` the environment resolves (the real `data/` by default) and has not been run with the LLM path. |
| Tests | Assertions in `test_audio_processing.py`, `test_models.py` and `test_document_generation.py` are too weak to detect the failures they claim to cover. `test_extraction_and_grounding.py` deliberately exercises the heuristic fallback and now asserts `is_degraded`; extraction quality is covered by `test_llm_extraction_live.py` and the eval tool instead. |
| Eval data | Gold annotations live in `tools/eval/gold/` (format in `tools/eval/README.md`), which is not git-ignored; the earlier `data/eval/` location was excluded by the `data/` rule and a `!data/eval/` negation cannot re-include it (git does not descend into an excluded directory; verified in a scratch repo). Only one gold fragment (Track A, 11 lines) exists; no raw-ASR (Track B) gold. |
| README | §B, §1 and §6 now describe the built-in Silero VAD filter (the standalone `vad.py` slicer is unwired) and once-per-recording language detection. The non-LLM rows of the §6 table are pre-LLM short-file measurements and have not been re-measured with the current pipeline. |
| Config | `LLM_PROVIDER` accepts `llama_cpp_server` but nothing reads the key: setting it silently keeps talking to Ollama. `json_first_pass_rate` divides by map calls including repairs. |
| Repo hygiene | `tools/eval/` (scorer, gold fixture, README) is new and untracked but not ignored; it must be added in the next commit or the offline test suite fails with `FileNotFoundError` on a clean checkout. `data/eval/` still holds an ignored copy of the fixture (never committed) that can be deleted. |

## Still not established

- Local LLM extraction on a real 60-minute recording: only the 11-line Track-A fragment and the (garbage) raw ASR of the 703 s audit recording have been run; throughput numbers in `docs/LLM_EXTRACTION.md` are measured per call, the 60-minute total is an estimate.
- `json_first_pass_rate` in `extraction_stats` divides by map calls including repair attempts (10/12 after one repair over 11 chunks), not by chunks.
- Speaker identity on real audio: the diarizer, enrollment, suggestion and confirmation paths are verified only with the two clean Windows SAPI voices (which prove the wiring, not meeting-room accuracy). No same-gender, cross-language or channel-mismatch test exists; the GPU end-to-end script (`scripts/voice_e2e_gpu.py`) is written but has not been executed.
- Delivery to a real hospital SMTP host has never been exercised, and must not be during development.
- Authentication, RBAC, durable jobs and transactional storage do not exist.
- No measured 60-minute run on declared hardware; README timings are short-file projections.

Use `docs/CODE_CONTEXT.md` and `AGENTS.md` for navigation.
