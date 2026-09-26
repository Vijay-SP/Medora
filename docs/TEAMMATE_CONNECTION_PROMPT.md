# Shared Processing Host Integration Prompt for Teammates

This prompt can be copied and provided directly to teammate coding assistants (e.g. Codex, Claude, ChatGPT, Cursor) to configure their PC to use the Mac mini's shared AI acceleration (ASR + LLM) over LAN.

---

```text
Configure my Medora/Medpark repository to use our shared Mac mini processing host over the LAN/Wi-Fi for both speech recognition (ASR) and extraction (LLM).

Shared Host Information:
  Hostname: Hisbaans-Mac-mini.local (or LAN IP provided by host owner)
  ASR Service (Metal GPU whisper.cpp queue): http://Hisbaans-Mac-mini.local:8001
  LLM Service (Ollama Qwen3-4B-Instruct):    http://Hisbaans-Mac-mini.local:11434
  Shared LLM Model: medpark-extractor

Roles and Boundaries:
- The Mac mini runs Whisper Large-v3-Turbo on Metal (Apple GPU) and Ollama LLM.
- Do NOT install whisper.cpp, CUDA, or download Whisper/LLM model weights on my machine.
- My machine runs the backend API and frontend UI.
- Audio normalization (ffmpeg), CAM++ speaker diarization (CPU), minutes generation (DOCX/PDF), and delivery routing (SMTP/Mailpit) continue to run locally on my machine.
- Multiple teammates share the Mac's queued services. Jobs are queued serially on the Mac so concurrent requests do not collide.

Tasks for Agent:
1. Verify Connectivity:
   - Check if Hisbaans-Mac-mini.local (or the LAN IP) is reachable on TCP 8001 and TCP 11434.
   - On Windows PowerShell:
       Test-NetConnection Hisbaans-Mac-mini.local -Port 8001
       Test-NetConnection Hisbaans-Mac-mini.local -Port 11434
       Invoke-RestMethod http://Hisbaans-Mac-mini.local:8001/ready
       Invoke-RestMethod http://Hisbaans-Mac-mini.local:11434/api/version
   - On macOS/Linux:
       curl -s http://Hisbaans-Mac-mini.local:8001/ready
       curl -s http://Hisbaans-Mac-mini.local:11434/api/version
   - If .local mDNS resolution fails, ask me for the Mac's current LAN IPv4 address (e.g. 192.168.x.x) and use that in the URLs instead.

2. Update Configuration:
   Update the repository-root .env file (preserving any other existing settings):
   ```ini
   # --- Shared Mac ASR Service (whisper.cpp queue on port 8001) ---
   ASR_PROVIDER=remote
   REMOTE_ASR_BASE_URL=http://Hisbaans-Mac-mini.local:8001
   REMOTE_ASR_API_KEY=
   REMOTE_ASR_TIMEOUT_S=3600
   REMOTE_ASR_POLL_INTERVAL_S=2

   # --- Shared Mac LLM Service (Ollama native API on port 11434) ---
   LLM_PROVIDER=ollama
   LLM_API_BASE_URL=http://Hisbaans-Mac-mini.local:11434
   LLM_MODEL_NAME=medpark-extractor
   LLM_CONTEXT_TOKENS=4096
   LLM_REQUEST_TIMEOUT_S=240
   LLM_HEALTH_TIMEOUT_S=3
   LLM_KEEP_ALIVE=10m
   REQUIRE_LOCAL_LLM=true
   LLM_FALLBACK_MODE=fail
   ```

3. Integrate Remote ASR Engine (if not already present):
   Ensure `app.services.asr.remote_engine.RemoteASREngine` is available and `get_asr_engine()` in `app.services.asr` instantiates it when `ASR_PROVIDER=remote`.
   The RemoteASREngine must:
   - POST 16kHz mono WAV to `v1/asr/jobs` with optional `language` ("auto"|"ro"|"ru"|"en") and `initial_prompt`.
   - Send an `Idempotency-Key` header with each submission.
   - Poll `v1/asr/jobs/{job_id}` until status is `completed` or `failed`.
   - Convert returned segments into native `TranscriptSegment` objects with `speaker="Speaker 1"`.
   - Never import `ctranslate2` or `faster_whisper` on the client when `ASR_PROVIDER=remote`.

4. Update Backend Readiness Probe:
   In `app/main.py`:
   - `/ready` should probe `{REMOTE_ASR_BASE_URL}/ready`.
   - Report `asr_service: {provider: "remote", endpoint: ..., connected: bool, ready: bool, device: str}`.
   - Report `ready: false` if remote ASR is unreachable or unready.

5. Test and Verify:
   - Run the backend test suite:
       PYTHONPATH=backend python backend/tests/test_remote_asr_engine.py
       PYTHONPATH=backend python backend/tests/test_asr_engine_selection.py
   - Start the backend and verify that `GET http://localhost:8000/ready` returns:
       "asr_service": {"provider": "remote", "connected": true, "ready": true}
       "llm_service": {"connected": true, "model": "medpark-extractor"}
   - Do NOT send hospital emails or test with real patient recordings.
   - Ensure Mailpit or local mock SMTP is configured (`ALLOW_SIMULATED_DELIVERY=false`, `SMTP_PORT=1025` or `9`).
```

---

## Shared ASR API Contract Reference

The shared speech server on the Mac exposes the following HTTP endpoints on port `8001`:

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | Liveness check (unauthenticated) | `200` `{"status":"ok","version":"1.0.0"}` |
| `GET` | `/ready` | Worker and Metal GPU readiness | `200` `{"ready":true,"engine":"whisper_cpp","device":"metal","queue_depth":0}` |
| `POST` | `/v1/asr/jobs` | Submit audio WAV for transcription | `202` `{"job_id":"...","status":"queued"}`<br>`413` Payload too large<br>`422` Invalid audio/params<br>`429` Queue full<br>`503` Engine not ready |
| `GET` | `/v1/asr/jobs/{job_id}` | Poll job status and retrieve segments | `200` `{"job_id":"...","status":"completed",result:{segments:[...]},error:null}`<br>`404` Not found |
| `DELETE` | `/v1/asr/jobs/{job_id}` | Clean up completed/failed job and files | `204` No content<br>`409` Active (queued/running)<br>`404` Not found |

### Headers & Security
- `Idempotency-Key: <uuid>` (recommended on `POST /v1/asr/jobs`): Prevents duplicate queue entries if network retries occur.
- `Authorization: Bearer <token>`: Required if `SPEECH_API_KEY` is configured on the host. Leave blank when running on a trusted private LAN.

---

## Starting Services on the Mac Host

On the host Mac mini:
```bash
# 1. Run Ollama LLM Service (port 11434)
# (Supervised via launchd or run directly with OLLAMA_HOST=0.0.0.0)
OLLAMA_HOST=0.0.0.0 ollama serve

# 2. Run Shared Speech Server (port 8001)
PYTHONPATH=backend .venv/bin/python backend/run_speech_server.py
```
