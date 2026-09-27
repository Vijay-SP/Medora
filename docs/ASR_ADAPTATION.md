# Medora ASR Dialect Accuracy and Controlled Adaptation Runbook

This document is the authoritative technical and operational reference for dialect adaptation, evidence preservation, and controlled Whisper fine-tuning in Medora (Medpark Hospital).

---

## 1. Engine & Provider Baselines

| Runtime / Engine | Location / Process | Compute Target | Default Model | Context & LID Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **faster-whisper** (`whisper_engine.py`) | Local PC (`F:\DEEPTECH`) | CUDA (`int8_float16`) or CPU fallback | `turbo` / `large-v3-turbo` | 12s VAD windowing, restricted LID (`ro`, `ru`, `en`), token-budgeted hotwords |
| **whisper.cpp** (`whisper_cpp_engine.py`) | Mac mini (`speech_server.py`, port 8001) | Metal GPU (`q5_0` / `q8_0`) | `ggml-large-v3-turbo-q5_0.bin` | VAD chunking, bounded `--prompt` seed, Metal acceleration |
| **RemoteASREngine** (`remote_engine.py`) | Local PC HTTP client | Network | Remote server-defined | Polled job queue, verified provenance headers, multipart context serialization |

### Verified Built-In Safeguards
- **Hotword-Echo Detection**: Re-decodes window sequentially without hotwords if decoder repeats prompt tokens.
- **Lexicon Digit Guard**: Prevents replacing abbreviations or tokens if glued to numerical values (e.g. dosages).
- **Strict Storage Isolation**: Automated tests must be launched with isolated environment variables (`DATA_DIR`, `ADAPTATION_DIR`, etc.) prior to Python module imports.

---

## 2. Evidence Preservation Contract (Milestone A)

1. **Decoder Verbatim Truth (`raw_text`)**:
   - `raw_text` holds untouched decoder hypothesis (trimmed of boundary whitespace only).
   - `raw_text_origin`:
     - `'decoder'`: Directly produced by a recognized decoder pass.
     - `'legacy_unknown'`: Stored before provenance tracking existed or from unverified sources.
2. **Normalized Variant (`normalized_text`)**:
   - Holds result of safe clinical lexicon or approved dialect rules.
   - `normalization_version`: Identifier of the rule-set applied (e.g. `lexicon_v1`, `lexicon_v1+dialect_v1`).
3. **Display Priority**:
   - `display_text` selects `corrected_text` if not `None` $\to$ `normalized_text` if not `None` $\to$ `raw_text`.
   - **Intentional Deletions**: An empty string `""` in `corrected_text` represents an intentional human removal; it renders as empty/removed and does NOT resurrect `raw_text`.
4. **Minutes Invalidation & Conflict Protection**:
   - Any transcript mutation bumps `revision` and sets `needs_transcript_review=True` on downstream minutes, blocking dispatch of stale documentation until refreshed and signed off.

---

## 3. Audio Evaluation Harness (Milestone A)

Located in `tools/eval/`:
- `asr_schema.py`: Pydantic schema for evaluation manifests, audio references, and hypothesis spans.
- `asr_metrics.py`: Rigorous offline scoring math:
  - Corpus WER using summed edit counts ($S+D+I / N$).
  - Per-language / condition WER.
  - Paired 95% recording bootstrap difference interval.
  - Entity precision, recall, and F1.
  - Critical-fact errors, silence hallucinations, and unwanted translations.
- `run_asr_eval.py`: Offline evaluation CLI.

---

## 4. Durable Correction History & Reviewer Learning Inbox (Milestone B)

Located in `backend/app/services/learning/`:
- `store.py`: Dedicated SQLite adaptation store (`ADAPTATION_DIR/adaptation_catalog.sqlite3`).
- `correction_collector.py`: Idempotent projection of human transcript corrections into catalog.
- `endpoints/learning.py`: Reviewer endpoints for learning inbox:
  - `GET /api/v1/learning/corrections`: Counts and listings.
  - `POST /api/v1/learning/corrections/{event_id}/verify`: Explicit human verification tied to exact revision, audio coordinates, and consent.
  - `POST /api/v1/learning/corrections/{event_id}/reject`: Rejects clip from dataset reuse.
- Frontend: `LearningCenter.tsx` review inbox with audio verification and consent toggles.

---

## 5. Dynamic Meeting Context (Milestone C)

Located in `backend/app/services/asr/dynamic_context.py`:
- `ContextTerm`: Typed terms with priority (`explicit_terms` > `department_terms` > `roster_names` > `learned_terms` > `site_anchors`).
- `ASRContext`: Immutable context payload with schema version and SHA-256 hash.
- Budgeting:
  - Max 40 hotword terms.
  - Token budget: capped at 80 actual Whisper tokens.
  - Fallback tokenizer handling Latin and Cyrillic subword expansion.
- Engine Plumbing:
  - `whisper_engine.py`: resolves dynamic hotwords with echo retry.
  - `whisper_cpp_engine.py`: injects bounded prompt seed into `--prompt`.
  - `remote_engine.py`: serializes context into multipart `POST /v1/asr/jobs`.

---

## 6. Conservative Dialect Normalization & Pattern Mining (Milestone D, Task 7)

Located in:
- `backend/app/services/asr/dialect_adapter.py`: Conservative normalizer.
- `backend/app/resources/language/`:
  - `ro_MD.json`: Moldovan Romanian clinical & administrative terms.
  - `ru_MD.json`: Moldovan Russian clinical & proper noun terms.
  - `code_switch.json`: Mixed-language hospital expressions.
- **Safety Guards**:
  - **Negation Guard**: If target term is within 3 tokens of a negation word (`nu`, `fără`, `не`, `нет`, `no`, `not`, etc.), mutation is blocked and downgraded to a suggestion.
  - **Dosage Guard**: If target term touches numbers or dosage units (`mg`, `ml`, `mcg`, `mmol`, `%`, etc.), mutation is blocked.
  - **Glued Digits**: Tokens containing numbers are never modified.
  - **Precedence**: Longest match first, stable spans, single-pass non-cascading replacement.
- `backend/app/services/learning/pattern_miner.py`: Mines conservative single-phrase replacements from human corrections.

---

## 7. Verified Dataset Builder & Retention Lifecycle (Milestone D, Task 8)

Located in:
- `backend/app/services/learning/dataset_builder.py`:
  - Extracts 16 kHz mono WAV clips (2.0s to 28.0s) from verified intervals.
  - Partitioning by recording groups: 70% train, 15% dev, 15% test.
  - Zero leakage between train and test recordings.
  - Constructs `speaker_disjoint_test` challenge split.
  - Path protection: output strictly within `ADAPTATION_DIR`, overwrite refused.
- `backend/app/services/learning/retention.py`:
  - `invalidate_source(meeting_id, reason)`:
    - Sets all correction events for meeting to `rejected`.
    - Marks dependent dataset manifests as `invalidated`.
    - Physically deletes derived audio clips from disk.
  - Integrated into `repository.delete_meeting()` and `audio.upload_audio()` (audio replacement).

---

## 8. Bounded LoRA Feasibility & Release Gate (Milestone D, Tasks 9 & 10)

Located in:
- `deploy/training/requirements.txt`: Isolated training dependencies.
- `deploy/scripts/fine_tune_whisper.py`:
  - Validates dataset integrity and split separation before model load.
  - Default `--dry-run` performs validation and parameter budgeting.
  - `--hardware-smoke-test` benchmarks forward/backward pass.
- `deploy/scripts/evaluate_asr.py`: Release gate evaluator with frozen criteria:
  - Relative corpus WER improvement $\ge 5.0\%$.
  - Upper bound of paired 95% bootstrap difference $< 0.0$.
  - Zero language strata regression (RO, RU, EN, mixed).
  - No increase in critical-fact errors, hallucinations, or unwanted translations.
  - Entity precision and recall $\ge$ baseline.
  - Latency RTF $\le 1.20 \times$ baseline.
- `backend/app/services/learning/model_registry.py`:
  - Immutable artifact registry (`candidate` $\to$ `evaluated` $\to$ `approved` $\to$ `active` $\to$ `retired`).
  - Cryptographic verification of weights and evaluation reports.
  - Atomic switching and instant rollback to previous active version.
- `deploy/scripts/manage_asr_model.py`: Administrative CLI for registry operations (`list`, `status`, `attach-eval`, `approve`, `activate`, `rollback`).

---

## 9. Operational Runbook for Hisbaan's Mac

This section provides the exact instructions to configure and run the high-performance `whisper.cpp` speech server on Hisbaan's Apple Silicon Mac.

### System Prerequisites on the Mac
- Apple Silicon Mac (M1/M2/M3/M4) running macOS 13+.
- Xcode Command Line Tools installed:
  ```bash
  xcode-select --install
  ```
- Python 3.10+ and `pip`.
- `git`, `cmake`.

### Step 1: Clone and Build whisper.cpp with Metal Acceleration

```bash
# In Hisbaan's home or workspace directory
cd ~
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp

# Compile with Apple Metal GPU acceleration enabled
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release

# Verify binary is executable and supports Metal
./build/bin/whisper-cli --help
```

### Step 2: Download Model Weights and Silero VAD

```bash
# From within ~/whisper.cpp:
# Download large-v3-turbo quantized model (optimal speed and accuracy for Metal GPU)
bash ./models/download-ggml-model.sh large-v3-turbo-q5_0

# Ensure Silero VAD model is present (or copy from repository assets)
# Model will be at: ~/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin
```

### Step 3: Set Up Medpark Speech Server

```bash
# Clone or copy the Medora backend to the Mac
git clone https://github.com/Vijay-SP/Medora_official.git ~/medora
cd ~/medora

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install backend dependencies
pip install -r backend/requirements.txt
```

### Step 4: Configure Environment Variables on the Mac

Create `~/medora/.env.speech`:
```ini
# Mac Speech Server Configuration
ASR_PROVIDER=whisper_cpp
WHISPER_CPP_BINARY_PATH=/Users/hisbaan/whisper.cpp/build/bin/whisper-cli
WHISPER_CPP_MODEL_PATH=/Users/hisbaan/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin
WHISPER_CPP_VAD_MODEL_PATH=/Users/hisbaan/whisper.cpp/models/silero-vad.bin
WHISPER_CPP_THREADS=4
WHISPER_CPP_DEVICE=metal

# Network & Authentication
SPEECH_SERVER_HOST=0.0.0.0
SPEECH_SERVER_PORT=8001
SPEECH_SERVER_BEARER_TOKEN=medpark_secure_lan_token_2026
DATA_DIR=/Users/hisbaan/medora_data
```

### Step 5: Start the Speech Server Daemon

```bash
cd ~/medora
export $(cat .env.speech | xargs)
export PYTHONPATH=backend

# Run speech server via uvicorn
python3 -m uvicorn app.speech_server:app --host 0.0.0.0 --port 8001
```

### Step 6: Configure the Main PC to use Hisbaan's Mac

On the main Windows workstation (`F:\DEEPTECH\.env`):
```ini
# Remote ASR delegation to Hisbaan's Mac
ASR_PROVIDER=remote
REMOTE_ASR_BASE_URL=http://<HISBAAN_MAC_IP>:8001
REMOTE_ASR_BEARER_TOKEN=medpark_secure_lan_token_2026
REMOTE_ASR_POLL_INTERVAL_S=0.5
REMOTE_ASR_TIMEOUT_S=300
```

Verify connection from Windows PC:
```powershell
curl http://<HISBAAN_MAC_IP>:8001/ready
```
Output will return `ready: true`, reporting `whisper_cpp` running on Apple Metal GPU.

---

## 10. Automated Test Verification

All 14 test suites are executed in an isolated environment without network or hospital mail transmission:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\test_asr_adaptation.ps1
```

Verified Test Suites (100% Passing):
1. `backend/tests/test_transcript_text_provenance.py`
2. `backend/tests/test_asr_evaluation.py`
3. `backend/tests/test_correction_collection.py`
4. `backend/tests/test_learning_review.py`
5. `backend/tests/test_dynamic_asr_context.py`
6. `backend/tests/test_context_engine_plumbing.py`
7. `backend/tests/test_asr_engine_options.py`
8. `backend/tests/test_whisper_cpp_engine.py`
9. `backend/tests/test_remote_asr_engine.py`
10. `backend/tests/test_asr_engine_selection.py`
11. `backend/tests/test_dialect_normalization.py`
12. `backend/tests/test_adaptation_dataset.py`
13. `backend/tests/test_training_manifest_validation.py`
14. `backend/tests/test_asr_release_gate.py`
