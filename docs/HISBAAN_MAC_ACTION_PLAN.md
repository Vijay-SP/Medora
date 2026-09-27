# Hisbaan's Mac Action Plan & Setup Guide

This guide contains the exact steps and terminal commands for **Hisbaan's Mac mini** to support the new dialect adaptation features, dynamic meeting context, and remote ASR acceleration for the team.

---

## 1. Quick Summary of What Changed
The codebase now includes:
1. **Dynamic ASR Context**: Injects departmental vocabulary, meeting agenda items, and participant names into the decode prompt seed (under 80 tokens).
2. **Context-Aware Speech Server**: The Mac speech server on port `8001` now accepts and forwards context seeds into `whisper-cli --prompt`.
3. **Dialect Normalization & Evidence Separation**: Verbatim decoder outputs are strictly preserved in `raw_text`, while conservative clinical/regional normalizations are stored in `normalized_text`.
4. **LoRA Fine-Tuning Feasibility on Apple Silicon**: Scripts and training manifests supporting Mac Metal Performance Shaders (`mps`).

---

## 2. Immediate Steps for Hisbaan to Run on the Mac

### Step 1: Pull the New Branch
On the Mac mini, navigate to the Medora repository and switch to the new branch:

```bash
cd ~/medora   # (or path to the repository on your Mac)

# Fetch latest branches and check out the fine-tuning branch
git fetch origin
git checkout feat/fine-tuning
git pull origin feat/fine-tuning
```

### Step 2: Update Python Dependencies
Activate the virtual environment and ensure requirements are current:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### Step 3: Verify whisper.cpp and Metal GPU Acceleration
Ensure `whisper.cpp` is built with Metal support:

```bash
cd ~/whisper.cpp   # (or your whisper.cpp directory)

# Compile with Metal enabled (if not done already)
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release

# Verify whisper-cli binary
./build/bin/whisper-cli --help
```

Ensure the model weights are present in `~/whisper.cpp/models/`:
- `ggml-large-v3-turbo-q5_0.bin` (or `ggml-large-v3-turbo.bin`)
- `silero-vad.bin` (VAD model for whisper.cpp)

If you need to download the quantized model:
```bash
bash ./models/download-ggml-model.sh large-v3-turbo-q5_0
```

### Step 4: Configure Environment & Launch the Speech Server
In `~/medora`, create or update `.env.speech`:

```ini
# Medora Mac Speech Server
ASR_PROVIDER=whisper_cpp
WHISPER_CPP_BINARY_PATH=/Users/hisbaan/whisper.cpp/build/bin/whisper-cli
WHISPER_CPP_MODEL_PATH=/Users/hisbaan/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin
WHISPER_CPP_VAD_MODEL_PATH=/Users/hisbaan/whisper.cpp/models/silero-vad.bin
WHISPER_CPP_THREADS=4
WHISPER_CPP_DEVICE=metal

# Network & Service Binding
SPEECH_SERVER_HOST=0.0.0.0
SPEECH_SERVER_PORT=8001
SPEECH_SERVER_BEARER_TOKEN=medpark_secure_lan_token_2026
DATA_DIR=/Users/hisbaan/medora_data
```
*(Adjust paths if your home folder is named differently)*.

Now start the speech server:
```bash
cd ~/medora
source .venv/bin/activate
export $(cat .env.speech | xargs)
export PYTHONPATH=backend

python3 -m uvicorn app.speech_server:app --host 0.0.0.0 --port 8001
```

### Step 5: Verify the Server is Ready Over LAN
From a browser or terminal on your Mac (or another team PC):
```bash
curl http://localhost:8001/ready
```
Expected output:
```json
{
  "ready": true,
  "engine_ready": true,
  "provider": "whisper_cpp",
  "device": "metal",
  "model_name": "ggml-large-v3-turbo-q5_0.bin",
  "active_jobs": 0,
  "queued_jobs": 0
}
```

---

## 3. (Optional) Testing LoRA Fine-Tuning Feasibility on Apple Silicon

If you want to run or test the LoRA fine-tuning feasibility benchmark on the Mac's unified memory / Metal (MPS):

### Setup Isolated Training Environment:
```bash
cd ~/medora
python3 -m venv .venv-training
source .venv-training/bin/activate
pip install -r deploy/training/requirements.txt
```

### Run Hardware Smoke Test on MPS:
```bash
python deploy/scripts/fine_tune_whisper.py \
    --dataset data/adaptation/datasets/v1 \
    --base-model openai/whisper-small \
    --output-dir data/adaptation/experiments/exp_mps_smoke \
    --device mps \
    --hardware-smoke-test
```
This tests PyTorch MPS tensor allocation, forward/backward pass, and peak unified memory usage on your Mac without modifying production weights.
