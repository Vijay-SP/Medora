# Medpark Offline Meeting Intelligence System

> **100% On-Premise, Air-Gapped AI Pipeline for Multilingual Hospital Meetings (Romanian / Russian / English) with Evidence-Linked Minutes and Automated Routing.**

Developed for **Medpark International Hospital (Chișinău, Moldova)**.

---

## 1. System Architecture & Workflow

```
[ Internal Browser: Upload / Mic ]
              │
              ▼
    ┌──────────────────┐
    │  FastAPI Backend │ ◄──── Serves React + WaveSurfer.js UI
    └─────────┬────────┘
              │
    ┌─────────▼─────────────────────────────────────────────────────┐
    │              Sequential AI Worker Pipeline                    │
    │  1. Audio Normalizer (FFmpeg 16kHz mono PCM)                  │
    │  2. Silero VAD -> 12 s decode windows (no overlap)            │
    │  3. ASR per window: restricted RO/RU/EN LID + forced decode   │
    │  4. Embedding Diarizer (VAD + CAM++, anonymous 'Speaker N')   │
    │  5. Local LLM Extractor (Ollama, Qwen3-4B, map/reduce)        │
    │  6. Index Grounding + Name Guard + Evidence Validator         │
    │  7. Document Engine (Immutable PDF & DOCX generation)         │
    └─────────────────────────┬─────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    [ Challenge Auto-Pilot ]       [ Supervised Medical Gate ]
    Zero-click immediate delivery   Interactive Review Workspace
    to internal hospital list       Human clinical sign-off
              │                               │
              └───────────────┬───────────────┘
                              ▼
        ┌───────────────────────────────────────────┐
        │  Local Delivery Outbox (Direct SMTP/Mailpit)│
        │  Optional n8n Hospital Routing Webhook    │
        └───────────────────────────────────────────┘
```

---

## 2. Repository Structure

The repository is organized following clean domain-driven design principles so that every module has a single, well-defined responsibility:

```
f:\DEEPTECH\
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── endpoints/
│   │   │       │   ├── meetings.py       # Meeting CRUD, listing, deletion
│   │   │       │   ├── audio.py          # Audio upload and WaveSurfer streaming
│   │   │       │   ├── pipeline.py       # Trigger processing, live progress status
│   │   │       │   ├── transcript.py     # Transcripts, utterances, reviewer edits
│   │   │       │   ├── review.py         # Human approval sign-off gate
│   │   │       │   ├── delivery.py       # Outbox records & PDF/DOCX downloads
│   │   │       │   ├── people.py         # /voice-profiles: consented enrollment (never from meeting audio)
│   │   │       │   └── speakers.py       # /meetings/{id}/speakers: the only path that names a speaker
│   │   │       └── api_router.py         # Consolidated API v1 router
│   │   ├── core/
│   │   │   ├── config.py                 # Pydantic BaseSettings, offline flags, paths
│   │   │   ├── logging.py                # Redacted, privacy-aware structured logging
│   │   │   └── exceptions.py             # Custom domain exceptions
│   │   ├── models/
│   │   │   ├── meeting.py                # Meeting domain schemas, types, workflow modes
│   │   │   ├── transcript.py             # Segments, four-state speaker attribution, printable floor
│   │   │   ├── person.py                 # People, consent, voiceprint descriptors, speaker maps
│   │   │   ├── extraction.py             # Decisions, Actions, Evidence citations, MoM
│   │   │   └── delivery.py               # Delivery outbox, routing policies, SMTP status
│   │   ├── services/
│   │   │   ├── audio/
│   │   │   │   ├── preprocessor.py       # FFmpeg audio normalization (16kHz mono)
│   │   │   │   └── vad.py                # Standalone pause slicer (not wired; ASR uses Whisper's VAD filter)
│   │   │   ├── asr/
│   │   │   │   ├── base.py               # Abstract Base ASR Engine
│   │   │   │   ├── whisper_engine.py     # faster-whisper: VAD windows, per-window restricted LID, forced decode
│   │   │   │   ├── windowing.py          # Silero VAD chunks packed into 1.5-28 s decode windows
│   │   │   │   ├── text_lid.py           # Script/stop-word language check that gates a re-decode
│   │   │   │   ├── lexicon.py            # Near-miss clinical-name correction, recorded in corrections[]
│   │   │   │   └── glossary.py           # HOTWORDS_BY_LANG (<= 80 tokens) + review-flag vocabulary
│   │   │   ├── diarization/
│   │   │   │   ├── base.py               # Abstract Base Diarizer
│   │   │   │   ├── fbank.py              # Exact Kaldi fbank + CMN front-end (never swap it)
│   │   │   │   ├── embedder.py           # WeSpeaker CAM++ ONNX speaker embedder (CPU)
│   │   │   │   ├── clustering.py         # Deterministic average-linkage AHC + mixed-voice probes
│   │   │   │   ├── matching.py           # Open-set voiceprint scoring (no forced assignment)
│   │   │   │   ├── enrollment.py         # Sample quality verdicts and voiceprint building
│   │   │   │   └── speaker_engine.py     # Silero VAD + embedding diarizer, anonymous labels
│   │   │   ├── extraction/
│   │   │   │   ├── base.py               # Abstract Base Extractor
│   │   │   │   ├── prompt_templates.py   # Map / synthesis prompts (Romanian, no roster/date/title)
│   │   │   │   ├── schemas.py            # JSON Schemas for Ollama constrained decoding
│   │   │   │   ├── llm_client.py         # Ollama native API client (health, chat, unload)
│   │   │   │   ├── chunker.py            # Token-budgeted chunks over the indexed transcript
│   │   │   │   ├── merge.py              # Deterministic de-duplication across chunks
│   │   │   │   ├── llm_engine.py         # Map/reduce extraction engine (preflight, unload)
│   │   │   │   ├── heuristic_extractor.py# Rule fallback; stamps is_degraded (never emailed)
│   │   │   │   └── validator.py          # Verbatim citations, owner resolution, name guard, deadlines
│   │   │   ├── documents/
│   │   │   │   └── generator.py          # Versioned PDF and DOCX reports
│   │   │   └── delivery/
│   │   │       ├── router.py             # Meeting-type distribution rules
│   │   │       ├── smtp_service.py       # Air-gapped SMTP client (Mailpit / Hospital)
│   │   │       └── n8n_service.py        # Self-hosted n8n webhook dispatcher
│   │   ├── storage/
│   │   │   ├── repository.py             # Thread-safe persistent JSON atomic store
│   │   │   └── file_manager.py           # Audio/document storage with SHA-256 integrity
│   │   ├── services/pipeline_orchestrator.py  # End-to-end pipeline coordinator (preflight -> ASR -> extraction)
│   │   └── main.py                       # FastAPI application, /ready probe & static UI mount
│   ├── run_server.py                     # Convenience launcher for backend
│   ├── requirements.txt                  # Pinned backend dependencies
│   └── tests/
│       ├── test_models.py                # Contracts & validation unit tests
│       ├── test_audio_processing.py      # Normalization & VAD tests
│       ├── test_extraction_and_grounding.py # Multilingual extraction & evidence tests
│       ├── test_document_generation.py   # PDF & DOCX export tests
│       ├── test_end_to_end_pipeline.py   # Full integration test (heuristic path, no LLM)
│       ├── test_llm_extraction_pipeline.py # Offline unit tests with a fake LLM client
│       ├── test_llm_extraction_live.py   # Track-A run against a live Ollama (skips if absent)
│       ├── test_speaker_embedder.py      # Kaldi fbank + embedder wrapper unit tests
│       ├── test_voice_models_and_storage.py   # Attribution invariants, migration, stores, purge cascades
│       ├── test_voice_profiles_api.py    # Enrollment flow through the API (SAPI samples)
│       ├── test_speaker_confirmation_flow.py  # /speakers confirm / correct / reject, 409s, revisions
│       ├── test_speaker_diarization_groundtruth.py # SAPI two-voice meeting recovered by the diarizer
│       ├── test_delivery_body_has_no_names.py # Email body/subject/payload carry no person names
│       ├── test_asr_text_lid_and_windowing.py # Text LID, window packing, lexicon, hotword token budget (offline)
│       └── test_asr_engine_options.py    # Engine decode options / restricted LID against a fake model (no CUDA)
│
├── frontend/                             # React + Vite + TypeScript + Tailwind UI
│   ├── src/
│   │   ├── api/client.ts                 # Type-safe API client
│   │   ├── components/
│   │   │   ├── Navbar.tsx                # Brand header with offline status
│   │   │   ├── AudioRecorder.tsx         # In-browser microphone recorder
│   │   │   ├── WaveformPlayer.tsx        # WaveSurfer.js player with interactive seek
│   │   │   ├── TranscriptViewer.tsx      # Code-switching transcript with edit capability
│   │   │   ├── DecisionsTable.tsx        # Decisions with clickable audio quotes
│   │   │   ├── ActionItemsTable.tsx      # Actions with owner, deadline, and audio seek
│   │   │   ├── ReviewApprovalModal.tsx   # Clinical sign-off gate modal
│   │   │   ├── MeetingIntakeModal.tsx    # New meeting modal (upload/record, mode toggle)
│   │   │   └── DeliveryOutboxDrawer.tsx  # Outbox log & artifact download drawer
│   │   ├── types/index.ts                # TypeScript domain models
│   │   ├── App.tsx                       # Main application workspace
│   │   └── main.tsx                      # Root mount
│   ├── package.json
│   └── vite.config.ts
│
├── deploy/                               # Deployment & Benchmarking
│   ├── docker-compose.yml                # Offline multi-container stack (App, Mailpit, n8n)
│   ├── Dockerfile                        # Multi-stage production container build
│   ├── n8n/
│   │   └── medpark_routing_workflow.json # Exported n8n workflow for meeting routing
│   ├── ollama/
│   │   └── Modelfile                     # medpark-extractor alias (ChatML template, num_gpu 37)
│   └── scripts/
│       ├── setup_ollama.ps1              # One-time model pull + alias + 100%-GPU check
│       └── benchmark_speed.py            # Latency benchmark measuring <15m budget
│
├── tools/eval/run_extraction_eval.py     # Stdlib scorer: minutes JSON vs tools/eval/gold
├── scripts/
│   ├── verify_speaker_embedder.py        # Embedder separation gate (two SAPI voices; --real for the audit recording)
│   ├── verify_gpu.py                     # Proves Whisper really runs on CUDA
│   ├── asr_ab_benchmark.py               # baseline vs windowed vs batched ASR on the audit wav (GPU-gated)
│   └── voice_e2e_gpu.py                  # GPU-gated end-to-end voice proof through the HTTP API
├── docs/ASR_CODE_SWITCHING.md            # Per-window RO/RU/EN decode: options, measured before/after, non-claims
├── docs/LLM_EXTRACTION.md                # LLM architecture, provisioning, measured numbers
├── docs/VOICE_PROFILES.md                # Speaker identity: safety architecture, measured numbers, non-claims
│
├── data/                                 # Local isolated storage (zero cloud)
│   ├── uploads/                          # Raw & normalized 16kHz audio recordings
│   ├── exports/                          # Generated PDF and DOCX reports
│   ├── models/                           # Whisper weights + speaker/campplus ONNX (the LLM lives in Ollama's own store)
│   ├── voiceprints/                      # Biometric .npy files and enrollment WAVs only (never JSON)
│   ├── eval/                             # Text-only gold annotations for extraction scoring
│   └── fixtures/                         # Test multilingual audio recordings
│
└── run.bat                               # One-click Windows runner
```

---

## 3. Key Design Highlights & Challenge Compliance

### A. 100% Offline Air-Gapped Operation
- **Zero External API Calls:** No OpenAI, Google, Anthropic, or external cloud telemetry.
- **Model Weights:** `faster-whisper` weights live in `data/models/`; the extraction LLM is a GGUF served by a local Ollama on `127.0.0.1:11434` (see §E).
- **Local Mail Catcher:** Connects to **Mailpit** on `127.0.0.1:1025` with zero data leaving the host.
- **Self-Contained Fonts:** Document rendering supports Romanian diacritics (`ș`, `ț`, `ă`, `î`, `â`) and Cyrillic without hosted Google Fonts.

### B. Romanian / Russian / English Code-Switching (measured, not marketed)
Details, every decoder option with its reason, and the non-claims: [`docs/ASR_CODE_SWITCHING.md`](docs/ASR_CODE_SWITCHING.md).
- **The problem it replaces:** the previous engine ran one `model.transcribe(language=None)` pass over the whole file, so faster-whisper picked one language from the first 30 s and stamped it everywhere. On the real 703 s audit recording 222/248 segments came out `ru`, Romanian clinical speech was rendered as Cyrillic nonsense (`Хемодинамик, инстабил` for *hemodinamic instabil*), the opening 27.7 s was a hallucinated term list, and most segments had integer-second bounds with zero gaps.
- **What runs now:** Silero VAD chunks packed into non-overlapping decode windows (1.5 s min, 12 s target, 20 s max, 28 s hard cap); one encoder pass per window; language identification restricted to `WHISPER_LANGUAGES` (`ro`, `ru`, `en`) and forced into the decoder; short windows (< ~4 s) inherit the neighbour's language; a script/stop-word text check gates a second decode with the runner-up language when the acoustic probability is below 0.70 or the text disagrees; per-language hotwords (<= 80 tokens) replace the 257-token prompt that overflowed Whisper's 223-token slot; `word_timestamps=True` so bounds come from the word alignment; garbage decodes are kept and flagged `low_confidence_asr`, never deleted. `multilingual=True` was rejected because its unrestricted LID chose English on Romanian speech and Whisper translated it.
- **Measured:** research probe (CPU, first 180 s of the audit recording): 13 windows, 11 `ru` + 2 `ro`; the window at 56.5-79 s flipped from Cyrillic gibberish to *"Asa, transferat acolo, acolo continuo a fost descărcat volemic"* (`avg_logprob` -0.48 vs -0.83). One GPU run of `scripts/asr_ab_benchmark.py --strategy windowed --seconds 180` (26 Sep): wall 15.3 s, **RTF 0.085** (projects to ~5 min of ASR per hour of audio), 15 windows (ru 12 / ro 2 / en 1), 0 integer-second durations, first segment 3.96 s instead of a 27.7 s hallucination, and the 56.5-74.6 s window decoded as readable Romanian (*"… a fost descărcat volemic și acum … instabilitate hemodinamică, tensiunele 80x40 cu dozele 0.22 de nor …"*). The same run also shows what is still wrong: three Russian windows echo the hotword list as if spoken, one segment is Whisper's *"Субтитры создавал DimaTorzok"* hallucination, and 4.8-23.7 s is Romanian speech labelled `en` after rescoring. The single-pass baseline on the full 703 s file was 134 s (RTF 0.19); a like-for-like `--strategy baseline` run on the same excerpt has not been recorded yet.
- **Not quantified:** there is no annotated reference transcript for any hospital recording, so RO/RU/EN word accuracy and language-identification accuracy on real meeting audio are unknown. The per-language counts and `language_confidence` values in the transcript are model outputs, not ground truth. The standalone slicer in `backend/app/services/audio/vad.py` remains unwired (energy threshold, one cough resets it).

### C. 100% Evidence Grounding (Anti-Hallucination)
- **Index Grounding:** The LLM only ever sees numbered transcript lines and cites line indices; the engine copies the quote, timestamps and speaker from the cited segment. The model cannot author a citation.
- **Clickable Audio Citations:** Every extracted decision and action item cites the exact verbatim spoken sentence and start/end audio timestamps.
- **Verification Pass:** The `evidence_validator` verifies that every quote actually exists in the spoken transcript before approving the Minutes of Meeting.
- **Name Guard:** An owner mention that does not occur verbatim in the cited lines is discarded; non-roster names and unexplained proper nouns set `needs_name_review` and are flagged in the documents.
- **Interactive Playback:** Clicking any quote in the UI immediately seeks the **WaveSurfer.js** audio player to that exact millisecond.

### D. Dual Workflow Modes
1. 🚀 **Challenge Auto-Pilot Mode (Hackathon / Demonstration):**
   - Audio is uploaded $\to$ Pipeline processes all stages $\to$ Automatically marks as approved $\to$ Dispatches email directly to Mailpit.
2. 🛡️ **Supervised Clinical Review Mode (Hospital Production Gate):**
   - Audio is uploaded $\to$ Pipeline extracts draft $\to$ Holds at `PENDING_REVIEW` $\to$ Reviewer inspects audio evidence and signs off $\to$ Triggers delivery.

### E. Local LLM Extraction (Ollama + Qwen3-4B-Instruct-2507, Q4_K_M)
Details, rationale and the failure policy are in [`docs/LLM_EXTRACTION.md`](docs/LLM_EXTRACTION.md).
- **Engine:** Ollama 0.34.4 native API on `http://127.0.0.1:11434`, model alias `medpark-extractor` built from `deploy/ollama/Modelfile` (plain ChatML template override, `num_gpu 37`, `num_ctx 4096`, `temperature 0`, `top_k 1`, `seed 1234`). Provision once with `deploy/scripts/setup_ollama.ps1`; run the server with `OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0`.
- **Map/reduce:** the compact indexed transcript is chunked at ~2,300 tokens (a 60-minute meeting is ~20k tokens, so single-shot extraction is impossible at ctx 4096), mapped sequentially with JSON-Schema-constrained decoding, merged deterministically in Python, then one synthesis call writes the summaries.
- **Kill switch:** `REQUIRE_LOCAL_LLM=true` (default) fails a run at preflight in ~3 s when the model is not serving. The heuristic parser only runs when `LLM_FALLBACK_MODE=heuristic` is set explicitly; its output is stamped `is_degraded` and can never be emailed.
- **VRAM:** Whisper (~2 GB) and the LLM (2.7 GB) do not fit together in 4 GB; the pipeline releases Whisper before extraction and unloads the LLM afterwards.

### F. Speaker Identity (Voice Profiles, human-confirmed only)
Details, thresholds, measured numbers and what is not claimed: [`docs/VOICE_PROFILES.md`](docs/VOICE_PROFILES.md).
- **Diarization:** Silero VAD + WeSpeaker CAM++ embeddings (ONNX, CPU, 512-d) clustered by deterministic
  average-linkage AHC at cosine distance 0.45 (measured on the real far-field recording; 0.55 merges speakers).
  Labels are anonymous `Speaker N`; the LLM prompt and every stored transcript never contain a person's name.
- **Enrollment is explicit and consented:** staff record prompted samples in "People & Voices"; each sample gets a
  verbatim quality verdict; a voiceprint exists only as a `.npy` under `data/voiceprints/`. Nothing enrols from
  meeting audio. Consent withdrawal and profile deletion purge the files.
- **A match is a question, not an answer:** the Speakers tab shows "Is this Dr. X?" with a cosine similarity
  (never a percentage). Only a reviewer's decision names a cluster, bound to the meeting revision and audited.
  A name prints on a segment only with >= 2.0 s of speech; short "Da." / "Окей." turns stay anonymous even in a
  confirmed cluster. Bulk confirmation is refused for mixed, too-short or straddling clusters.
- **Documents and email:** the PDF/DOCX print confirmed names with a legend and the reviewer; suggestions,
  scores and unconfirmed names never appear. Email bodies carry counts and attachment names only.
- **Honest scope:** accuracy is proven on the two Windows SAPI voices (12/12 turns, suggestion cosine 0.95-0.97);
  far-field meeting-room accuracy is unmeasured, and the GPU end-to-end script has not been run yet.

---

## 4. Quickstart Guide

### Prerequisites
- Python 3.12 or 3.13
- FFmpeg installed (available automatically via WinGet or PATH)
- Node.js v18+ (for frontend development)

### Launching the Application
Simply double-click:
```bat
run.bat
```
Or run manually from the terminal:
```bash
# In terminal 1: Start Backend (serves both API and compiled UI)
python backend/run_server.py
```
Open your browser at:
👉 **`http://127.0.0.1:8000`**

### Running the Frontend in Dev Mode (Hot Reload)
```bash
cd frontend
npm run dev
```
Open **`http://127.0.0.1:5173`**

### Running with Docker Compose (Fully Isolated)
```bash
cd deploy
docker compose up -d
```
- Web Application: `http://localhost:8000`
- Mailpit Webmail: `http://localhost:8025`
- n8n Workflow: `http://localhost:5678`

The compose stack does **not** include Ollama and does not pass a GPU through. The app container
defaults to `LLM_API_BASE_URL=http://127.0.0.1:11434`, which inside the container is the container
itself, so with `REQUIRE_LOCAL_LLM=true` every pipeline run fails at preflight until
`LLM_API_BASE_URL` points at the host's Ollama (for example `http://host.docker.internal:11434`);
Whisper runs on CPU there. The measured numbers in §6 are from the native Windows setup.

---

## 5. Verification & Automated Test Suite

All domain models, audio preprocessors, VAD chunkers, multilingual extraction engines, and document generators are covered by unit and integration tests:

```powershell
# Isolate storage and mail first: the repository singleton binds DATA_DIR at import and
# derived dirs do not follow it, so every path is set explicitly; SMTP points at a dead port.
$t = "$env:TEMP\medpark-tests"
$env:DATA_DIR="$t\data"; $env:UPLOADS_DIR="$t\uploads"; $env:EXPORTS_DIR="$t\exports"; $env:FIXTURES_DIR="$t\fixtures"
$env:SMTP_HOST="127.0.0.1"; $env:SMTP_PORT="9"; $env:ALLOW_SIMULATED_DELIVERY="false"
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_DISABLE_TELEMETRY="1"
$env:PYTHONPATH="backend"
.venv\Scripts\python.exe backend/tests/test_models.py
.venv\Scripts\python.exe backend/tests/test_audio_processing.py
.venv\Scripts\python.exe backend/tests/test_extraction_and_grounding.py   # heuristic path, no LLM
.venv\Scripts\python.exe backend/tests/test_document_generation.py
.venv\Scripts\python.exe backend/tests/test_end_to_end_pipeline.py        # Whisper and SMTP mocked
.venv\Scripts\python.exe backend/tests/test_llm_extraction_pipeline.py    # fake LLM client, offline
.venv\Scripts\python.exe backend/tests/test_llm_extraction_live.py        # real Ollama; skips when absent
.venv\Scripts\python.exe backend/tests/test_speaker_embedder.py            # fbank + CAM++ wrapper (skips without the ONNX)
.venv\Scripts\python.exe backend/tests/test_voice_models_and_storage.py    # attribution invariants, stores, purge cascades
.venv\Scripts\python.exe backend/tests/test_delivery_body_has_no_names.py  # email carries no names (transports mocked)
.venv\Scripts\python.exe backend/tests/test_speaker_confirmation_flow.py   # /speakers confirm flow through TestClient
.venv\Scripts\python.exe backend/tests/test_speaker_diarization_groundtruth.py # SAPI two-voice meeting (skips without SAPI/ONNX)
.venv\Scripts\python.exe backend/tests/test_voice_profiles_api.py          # enrollment API flow (SAPI samples)
.venv\Scripts\python.exe backend/tests/test_asr_text_lid_and_windowing.py  # text LID, window packing, lexicon, hotword budget (offline)
.venv\Scripts\python.exe backend/tests/test_asr_engine_options.py          # engine options vs a fake model, restricted LID (no CUDA)
```
The voice tests set their own isolated `DATA_DIR`/`UPLOADS_DIR`/`EXPORTS_DIR`/`FIXTURES_DIR`/`VOICEPRINTS_DIR`
before importing `app`. `scripts/voice_e2e_gpu.py` is the only voice script that touches the GPU and refuses to
run while `nvidia-smi` shows >= 1000 MiB in use.
The offline suite passes without Ollama. Passing tests do not demonstrate ASR quality or real
delivery: the end-to-end test mocks `whisper_engine.transcribe` and `aiosmtplib.send`. Extraction
quality is scored separately with `tools/eval/run_extraction_eval.py` against `tools/eval/gold`.

---

## 6. Performance Benchmark (<15 Min Target)

To benchmark real-time factor (RTF) on hospital test recordings:
```bash
python deploy/scripts/benchmark_speed.py data/fixtures/Medpark_audio.m4a
```

| Pipeline Stage | 12-min Audio Benchmark (pre-LLM run, not re-measured) | Projected 60-min Meeting |
|---|---|---|
| Audio Normalization (16kHz mono) | 1.8s | ~9.0s |
| VAD (Silero, window packing) | included in ASR | included in ASR |
| Multilingual Speech-to-Text | old single whole-file pass, GPU: 134 s for the 703 s audit recording (RTF 0.19); windowed per-language path, GPU, first 180 s of the same recording: 15.3 s (RTF 0.085, one run, `scripts/asr_ab_benchmark.py`) | RTF 0.085 -> ~5 min (projection from a 180 s excerpt); the budget needs <= ~9 min |
| Speaker Diarization (Silero VAD + CAM++ embeddings, CPU) | ≈ 11 s for the 703 s audit recording (VAD + embedding, 4 threads; not this file) | ~1 min (projection) |
| LLM Minutes & Evidence Extraction | not measured on this file (the earlier 2.5s was the heuristic parser) | ~2 min (estimate, see below) |
| PDF & DOCX Generation | 0.8s | ~4.0s |
| SMTP Delivery | 0.2s | ~0.5s |
| **Total End-to-End Processing** | **not measured with the LLM** | **~4-8 minutes (estimate)** |

**Measured LLM throughput** (RTX 3050 4 GB, Ollama 0.34.4, `medpark-extractor` at 100% GPU, 2.70 GiB VRAM):
prefill 1,332 tok/s, decode ~31 tok/s, model load 3.5 s. A 2,612-token chunk round-trips in 2.9 s;
a 314-token structured answer takes 11 s. A 60-minute meeting (~20k indexed tokens, ~9 chunks)
is therefore **estimated** at ~2 minutes of LLM time; that end-to-end run has not yet been
performed on a real 60-minute recording, so the 15-minute target is a projection, not a result.
