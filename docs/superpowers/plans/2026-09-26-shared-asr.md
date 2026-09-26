# Shared Mac ASR Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans task by task.

Goal: Serve Apple-accelerated Whisper transcription from this Mac to existing Medpark backends over LAN, with durable queued jobs, a compatible remote engine, verified deployment, and a teammate integration prompt.

Architecture: A separate lightweight FastAPI speech entrypoint in this repository runs one durable SQLite-backed worker. It uses a whisper.cpp CLI adapter, retaining the original faster-whisper engine as the default. Backends choose ASR_PROVIDER=remote and submit/poll opaque job IDs; existing downstream diarization, review, extraction and delivery remain unchanged. Native Whisper and Ollama each have one inference slot; they may overlap (not a global all-model queue). This is bounded concurrency on the 16 GB Mac, to be measured rather than claimed production capacity.

Tech stack: Python/FastAPI, stdlib SQLite, httpx, native whisper.cpp/Metal, local predownloaded large-v3-turbo and Silero VAD.

Global constraints:
- Preserve existing work and default faster-whisper behavior; work on codex/shared-asr in current checkout.
- No hospital email, patient data, cloud inference, automatic speaker confirmation or frontend rewrite.
- Local weights only; no model downloads during inference. No external URLs accepted for audio input.
- One ASR worker; persistent jobs survive service restart. Bound upload bytes, queue, inference duration and retention.
- Wi-Fi-address supervision and stable .local URL; local-only demo mode also documented.
- Remote ASR uses native TranscriptSegment shape, reports actual engine/device, never falls back locally silently.
- Tests isolate DATA_DIR/UPLOADS_DIR/EXPORTS_DIR/FIXTURES_DIR/VOICEPRINTS_DIR/MODELS_DIR before app import.

API contract (v1):
- GET /health: liveness {status, version}.
- GET /ready: {ready, engine:whisper_cpp, model, device, queue_depth, max_pending_jobs}.
- POST /v1/asr/jobs: multipart file, optional language=auto|ro|ru|en, initial_prompt; optional Idempotency-Key. Returns 202 {job_id,status,status_url}; 413 upload cap, 422 bad audio/options, 429 queue full, 503 missing runtime/model. Optional Bearer auth when SPEECH_API_KEY configured; never return/log keys.
- GET /v1/asr/jobs/{uuid}: {job_id,status:queued|running|completed|failed,created_at,updated_at,result:null|{segments:[TranscriptSegment],engine,model,device,duration_seconds},error:null|string}.
- DELETE /v1/asr/jobs/{uuid}: delete terminal job and files; 409 while queued/running.
- Store UUID directories only; filenames never determine server paths. Completed/failed artifacts expire after configured TTL; failed staging uploads are removed.
- Client polls the stored job ID on transient GET failures, never blindly resubmits; preserves segments through model validation. Total deadline includes queue wait.

Tasks:
- [x] 1. WhisperCppEngine + unit tests: CLI model/VAD configuration, no translation/context carryover, JSON parsing/timestamp/flag validation, timeout/error cleanup, device provenance. Agent owns new adapter/test files only.
- [x] 2. Durable speech queue + FastAPI entrypoint/tests: upload validation, single worker, restart recovery, idempotency, errors, retention, limits, optional auth.
- [x] 3. ASR engine selection/remote client/readiness integration + tests. Keep default engine compatibility and avoid importing CUDA dependencies for remote/cpp modes.
- [x] 4. Install native runtime/weights, configure launch agent and Wi-Fi recovery, verify real synthetic speech plus remote client and queue behavior.
- [x] 5. Review changes, run affected regression scripts, update implementation status/README/LAN documentation and shareable prompt. Report real limitations (no 60-minute benchmark, no verified hospital code-switch quality).

Review focus: concurrent submissions, interrupted uploads and processes, invalid/infinite timestamps, server restart mid-job, .local resolution in client containers.
