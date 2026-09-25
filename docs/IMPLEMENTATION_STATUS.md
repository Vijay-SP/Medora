# Medpark implementation audit — 25 September 2026

## Outcome

The application starts and the frontend builds. It is a working prototype shell with real Whisper inference and document generation, but the current code does not establish production-pilot readiness. Local LLM extraction, trustworthy speaker identity, approval enforcement, factual grounding, and confirmed delivery need work.

Application source was not changed during this audit. Added project context/index configuration and this report; rebuilt frontend output. Tests and the supplied-recording run use separate `.audit` storage instead of the existing meeting store.

## Verified execution

| Check | Result |
|---|---|
| VS Code | Project open in `F:\DEEPTECH` |
| PyCharm Community 2024.3.4 | Project open; window title `DEEPTECH – README.md` |
| Frontend | `npm.cmd run build` passed TypeScript and Vite |
| Backend packages | Existing Python 3.13 virtual environment; `pip check` passed |
| Running application | `http://127.0.0.1:8000/`, `/health`, and `/ready` returned HTTP 200 |
| Browser smoke check | React interface loads; a completed sample meeting visibly shows speaker/timestamps but blank transcript text, confirming the API/UI mismatch |
| Supplied test scripts | All five passed: models, audio processing, extraction/grounding, documents, end-to-end |
| Runtime dependencies | No local LLM on 8080, Mailpit on 1025/8025, or n8n on 5678 at audit start |
| Local mail catcher | Subsequently started `medpark-audit-mailpit` with Podman, bound only to `127.0.0.1:1025` and `127.0.0.1:8025`; no hospital messages were sent |
| CodeGraph | Installed 0.20.1; MCP handshake, eight core tools, backend and frontend symbol lookup verified |

The test pass result is NOT evidence of valid end-to-end AI output. The end-to-end test feeds a four-second sine wave. The app invents a transcript segment when recognition returns nothing, falls back to regex extraction with no LLM, simulates SMTP success, and still passes.

The API probe also confirmed unauthenticated meeting access (HTTP 200), missing serialized `display_text`, and public-CDN URLs in Swagger UI. These are separate from the frontend build result.

To stop the started mail catcher: `podman stop medpark-audit-mailpit`. The app process ID and logs are recorded in `.audit/server.pid`, `.audit/server.stdout.log`, and `.audit/server.stderr.log`.

Audit logs and data are under `.audit`; they are intentionally excluded from the code index and version control. Final supplied-recording measurements are recorded separately in the measured-run section below.

## P0 — Fix before presenting output as trustworthy

1. **Never invent transcription when there is no speech.** `backend/app/services/asr/whisper_engine.py:154-167` inserts a Romanian sentence with confidence 1.0 after empty recognition. Reproduced by the existing end-to-end test. Return a no-speech result and prevent decision extraction/delivery from fabricated input.
2. **Provision and require the actual local LLM.** `backend/app/services/extraction/llm_engine.py:38-50` silently switches to regex on any local LLM failure. There is no deployed llama server or GGUF in the project. Add model provisioning, readiness checks, schema-constrained output, chunked long-transcript extraction, and explicit failure/degraded-state behavior. Do not label regex/template output as model inference.
3. **Enforce the user's review-before-email requirement.** Backend default `backend/app/models/meeting.py:62` and UI default `frontend/src/components/MeetingIntakeModal.tsx:19` select auto-pilot. `pipeline_orchestrator.py:96-111` approves and sends without review. Use supervised default and server-enforced approval of an exact revision.
4. **Do not report failed SMTP as delivered.** `services/delivery/smtp_service.py:97-101` returns SIMULATED on failure; `pipeline_orchestrator.py:111` and `api/v1/endpoints/review.py:102` still set DELIVERED. Reproduced in the test log. Track failed/unknown/accepted delivery accurately, implement outbox retry/idempotency, and separate demo simulation from real results.
5. **Remove guessed speaker identities.** `services/diarization/speaker_engine.py:97-115` assigns attendee names by acoustic cluster ordinal. There is no enrolled voiceprint comparison or identity confirmation. Keep anonymous speaker labels until confirmed; implement actual diarization and optional enrollment/matching.
6. **Validate claims, not just overlapping words.** `services/extraction/validator.py:24-45,58-73` checks quoted text anywhere or 70% word overlap, ignores timestamp/speaker agreement, and retains claims with zero evidence. A runtime probe confirmed an unsupported decision survives. Reject/flag unsupported claims and validate source IDs, ranges, values, owner/deadline evidence, and revisions.

## P1 — Complete the functional workflow

| Remaining work | Evidence / required change |
|---|---|
| Visible transcript text | `models/transcript.py:28-31` uses a plain property; it is absent from serialized API JSON, while `frontend/src/components/TranscriptViewer.tsx:164` requires `display_text`. A serialization probe reproduced the missing field. Serialize the field or derive text consistently in the UI. |
| Correct deadlines | `services/extraction/validator.py:83-86` tests tomorrow before day-after-tomorrow. Both `poimâine` and `послезавтра`, anchored to 2026-09-25, incorrectly return 2026-09-26. Test longer/specific phrases first and handle ambiguity. |
| Real code-switch strategy | `services/asr/whisper_engine.py:120-148` performs whole-file recognition and assigns the same detected language to every segment; custom pause chunking is not used by the orchestrator. Add measured chunk/span processing, overlap reconciliation, medical-term checks, and real multilingual evaluation. |
| GPU execution | Actual supplied-recording run failed to load `cublas64_12.dll` and fell back to CPU. Provision compatible CUDA/cuBLAS/cuDNN libraries and verify before publishing GPU timing. |
| Editable minutes | The backend supports `PUT /minutes`, but the UI does not expose summary/decision/action editing. Render risks/questions and agenda sections too. |
| Reliable UI errors/progress | `frontend/src/App.tsx:131-147` swallows intake failures, so the modal closes; status polling omits `generating_docs` at line 107. Add visible errors, retry/recovery, and all processing states. |
| Meeting-switch correctness | `App.tsx:102-129` applies late responses without checking selected meeting identity. Cancel/guard stale requests so meeting A's transcript cannot appear under B's audio. |
| Evidence playback | Evidence buttons seek to start but ignore end time; stop at the cited range. |
| Recording lifecycle | `AudioRecorder.tsx:22` hardcodes WebM; check MIME support and stop tracks on cancellation/unmount. |
| Speaker review/enrollment | No voice-enrollment flow, confirmed speaker mapping, or identity uncertainty queue exists. |
| Action follow-up | Current table is limited to a selected meeting. No cross-meeting action dashboard, update API, or completion controls. |
| n8n delivery | Workflow JSON is present but not imported/activated and SMTP credentials are not provisioned. Current app sends directly and then triggers n8n, risking duplicate sends. Select one delivery owner. |
| Revision consistency | Transcript/audio/minutes changes do not invalidate prior approval. Historical outbox downloads resolve latest exports instead of the sent revision. Tie all artifacts and delivery records to immutable revisions. |
| Linux PDF fonts | `services/documents/generator.py:24-30` only loads Unicode Arial from a Windows path. The Docker image does not bundle/register a Unicode font; fallback text sanitization loses Cyrillic/diacritics. Bundle a redistributable Unicode font and test rendered Linux documents. |

## P1 — Hospital pilot foundations

- **Authentication and permissions:** no login/RBAC or meeting-level authorization. Approval trusts client-supplied reviewer identity; CORS additionally allows `*`. Restrict access and derive reviewer identity server-side.
- **Durable jobs:** API `BackgroundTasks` owns heavy inference; no queue, restart recovery, cancellation, heartbeat, or duplicate-run prevention. Move inference to a worker and persist stage transitions.
- **Durable storage:** JSON collections and per-process locks do not provide multi-process transactions. `_read_json` returns `{}` on read/parse failure, allowing silent overwrite. Add transactional storage, migrations, backups, recovery tests, and retention/deletion.
- **Offline enforcement:** flags currently describe intent rather than enforcing policy. Cached ASR DID load in this audit with explicit Hugging Face offline environment variables; uncached startup, browser resources, telemetry, and network egress still need validation. Self-host API docs assets: the default Swagger page loads a public CDN.
- **Deployment:** Docker entrypoint binds Uvicorn to container `127.0.0.1` with reload enabled, preventing normal published-port access. Use container `0.0.0.0`, production process settings, local network isolation, pinned images/packages/models, model mounts, and health/readiness checks for actual dependencies.
- **Readiness:** `/ready` reports true based on directory existence even when LLM and delivery services are unavailable.
- **Auditability:** protect approved revisions, keep reviewer/change/recipient history, distinguish service metadata from meeting contents, and verify backups and deletion.

## Evaluation still required

- Annotated RO/RU/EN recordings, sentence-level code switching, speaker identity, medical terminology, numeric values, negation, cancellations, and ambiguous dates.
- Decision/action precision and recall, explicit owner/deadline correctness, unsupported-claim rate, ASR errors, and diarization errors.
- A measured 60-minute run on declared hardware. README timing is a short-file projection and does not prove the target, especially with regex extraction and simulated mail.
- Meaningful negative tests: no speech must not generate transcript; missing LLM must not look successful; SMTP failure must not mean delivered; unauthorized/stale/repeated approval must fail; mismatched evidence must be rejected.

## Suggested execution order

1. Fix false-success paths, no-speech behavior, transcript serialization, and deadline resolution.
2. Provision local LLM/GPU runtime and make dependency readiness truthful.
3. Enforce supervised revision approval, reliable local mail, and one n8n delivery route.
4. Replace speaker-name guessing; implement identity review/enrollment and test multilingual speech accuracy.
5. Complete review/action UX, durable worker/storage, access controls, offline proof, and benchmark evidence.

Use `docs/CODE_CONTEXT.md` and `AGENTS.md` for compact future-session navigation. The earlier broad architecture plan is not a description of this code.

## Verification update — September 2026

The following audit findings were addressed and verified with tests:

1. **P0.1 No-speech fabrication eliminated:** `services/asr/whisper_engine.py` returns `[]` on empty audio; `pipeline_orchestrator.py` marks `PENDING_REVIEW` with 0 decisions/actions and skips delivery. Verified by `test_end_to_end_no_speech_behavior` in `backend/tests/test_end_to_end_pipeline.py`.
2. **P0.3 Review before email enforced:** Default `workflow_mode` changed to `supervised` in `models/meeting.py` and `MeetingIntakeModal.tsx`; sign-off requires reviewer name and role.
3. **P0.4 Truthful delivery state:** `services/delivery/smtp_service.py` records `FAILED` when SMTP connection fails; `pipeline_orchestrator.py` and `review.py` only mark `DELIVERED` when delivery status is `DISPATCHED`.
4. **P0.5 Neutral speaker labels:** `services/diarization/speaker_engine.py` uses anonymous cluster labels (`Speaker 1`, `Speaker 2`) and places attendee mentions in `suggested_identity` rather than guessing attendee mappings.
5. **P0.6 Evidence grounding & claim rejection:** `services/extraction/validator.py` strictly validates segment IDs, quoted text, and timestamps; unsupported claims are downgraded to `risks_and_questions` as `unresolved_question`.
6. **P1.45 Serialized display text:** Added `@computed_field` to `TranscriptSegment.display_text` in `models/transcript.py` and added resilient UI fallback in `TranscriptViewer.tsx`.
7. **P1.46 Relative deadlines resolved:** `validator.py` evaluates `poimâine`/`послезавтра` (2-day offset) before `mâine`/`завтра` (1-day offset).
8. **P1.49 Editable minutes & section UX:** Added `PUT /meetings/{id}/minutes` client binding, inline executive summary editing with revision tracking, agenda topics rendering, and `RisksQuestionsTable.tsx`.
9. **P1.50 UI errors and progress polling:** Added `generating_docs` stage to polling in `App.tsx`; added dismissible error banner for intake and approval failures.
10. **P1.51 Meeting-switch race condition protection:** Added `selectedMeetingIdRef` guards in `loadMeetingData` to ignore stale async responses, and instant state clearing on meeting switch.
11. **P1.52 Bounded evidence playback:** Added `playRange(startSec, endSec)` to `WaveformPlayer.tsx` with automatic pause at range end; wired evidence buttons in `DecisionsTable` and `ActionItemsTable`.
12. **P1.53 Audio recorder lifecycle & cross-browser MIME:** `AudioRecorder.tsx` uses `MediaRecorder.isTypeSupported` across WebM/MP4/OGG/WAV and stops all audio tracks on unmount/cleanup.
13. **P1.56 Exclusive delivery owner:** Router and orchestrator enforce single delivery channel (n8n OR direct SMTP) based on `DELIVERY_CHANNEL` setting to prevent duplicate sends.
14. **P1.57 Revision consistency & historical attachments:** Updating minutes bumps revision and invalidates prior approval; added `/meetings/{id}/export/pdf?revision=X`, `/export/docx?revision=X`, and `/deliveries/{id}/attachment/pdf` for exact sent revisions.
15. **P1.58 Cross-platform Unicode PDF fonts:** Bundled `fonts-dejavu-core` in `deploy/Dockerfile`; `services/documents/generator.py` registers cross-platform Unicode font paths (`AppUnicode`).
16. **Frontend English localization:** Translated all UI components, headers, buttons, badges, modals, forms, tables, and empty states to English, adhering to professional clinical and hospital terminology.

All 5 backend test scripts (`test_models.py`, `test_audio_processing.py`, `test_extraction_and_grounding.py`, `test_document_generation.py`, `test_end_to_end_pipeline.py`) pass 100%. Frontend builds cleanly with Vite/TypeScript (`npm run build` verified).

