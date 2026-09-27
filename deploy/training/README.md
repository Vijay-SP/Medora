# Medpark ASR LoRA Fine-Tuning Guide

This runbook guides running bounded Low-Rank Adaptation (LoRA) experiments for Whisper models on hospital meeting speech.

## Principles & Safety Constraints

1. **Complete Environment Isolation**: Training frameworks (`peft`, `accelerate`, PyTorch CUDA/MPS wheels) belong in an isolated virtual environment (`.venv-training`), NOT in the backend runtime.
2. **Explicit Human Consent**: Only clips from verified correction events with explicit `training_reuse_allowed=true` and verbatim labels can be included.
3. **No Split Leakage**: Splits are grouped by recording (meeting). No meeting or speaker may leak between `train` and `test`.
4. **Locked Test Set Protected**: The `test` and `speaker_disjoint_test` splits must NEVER be used for training, hyperparameter tuning, or vocabulary mining. They are reserved strictly for final release gate evaluation.
5. **No Automatic Promotion**: Training produces an experimental candidate checkpoint. It is never activated automatically in the meeting pipeline.

## Environment Setup

```bash
# Create dedicated virtual environment
python3 -m venv .venv-training
source .venv-training/bin/activate  # Or .venv-training\Scripts\activate on Windows

# Install pinned dependencies
pip install -r deploy/training/requirements.txt
```

## CLI Usage

### Dry-Run Validation (Default)
Validates dataset integrity, split boundaries, and checksums without loading model weights:

```bash
python deploy/scripts/fine_tune_whisper.py \
    --dataset data/adaptation/datasets/v1 \
    --base-model openai/whisper-large-v3-turbo \
    --output-dir data/adaptation/experiments/exp_01 \
    --device cpu
```

### Hardware Smoke Test
Runs a 1-step forward/backward pass on MPS or CUDA to verify memory availability and numerical stability:

```bash
python deploy/scripts/fine_tune_whisper.py \
    --dataset data/adaptation/datasets/v1 \
    --base-model openai/whisper-small \
    --output-dir data/adaptation/experiments/exp_smoke \
    --device mps \
    --hardware-smoke-test
```

### Actual Training Execution
Requires `--train` flag:

```bash
python deploy/scripts/fine_tune_whisper.py \
    --dataset data/adaptation/datasets/v1 \
    --base-model openai/whisper-large-v3-turbo \
    --output-dir data/adaptation/experiments/exp_lora_v1 \
    --device cuda \
    --train \
    --epochs 5 \
    --learning-rate 1e-4 \
    --lora-rank 16
```
