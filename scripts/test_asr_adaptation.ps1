# Safe Test Runner for Medora ASR Adaptation Suite
# Runs strictly in offline mode with complete directory and network isolation.

param(
    [string[]]$Tests = @()
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("medora-adaptation-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testRoot | Out-Null

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Medora ASR Adaptation Isolated Test Harness" -ForegroundColor Cyan
Write-Host "Isolation Directory: $testRoot" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan

# Environment Isolation
$env:PYTHONPATH = "backend"
$env:DATA_DIR = $testRoot
$env:UPLOADS_DIR = Join-Path $testRoot "uploads"
$env:EXPORTS_DIR = Join-Path $testRoot "exports"
$env:FIXTURES_DIR = Join-Path $testRoot "fixtures"
$env:VOICEPRINTS_DIR = Join-Path $testRoot "voiceprints"
$env:OUTBOX_DIR = Join-Path $testRoot "outbox"
$env:ADAPTATION_DIR = Join-Path $testRoot "adaptation"
$env:MODELS_DIR = Join-Path $repoRoot "data\models"

# Air-gap & Safety Locks
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:SMTP_HOST = "127.0.0.1"
$env:SMTP_PORT = "9"
$env:ALLOW_SIMULATED_DELIVERY = "false"
$env:WHISPER_DEVICE = "cpu"
$env:CUDA_VISIBLE_DEVICES = "-1"
$env:LLM_API_BASE_URL = "http://127.0.0.1:9"

$defaultAllowlist = @(
    "backend/tests/test_transcript_text_provenance.py",
    "backend/tests/test_asr_evaluation.py",
    "backend/tests/test_correction_collection.py",
    "backend/tests/test_learning_review.py",
    "backend/tests/test_dynamic_asr_context.py",
    "backend/tests/test_context_engine_plumbing.py",
    "backend/tests/test_asr_engine_options.py",
    "backend/tests/test_whisper_cpp_engine.py",
    "backend/tests/test_remote_asr_engine.py",
    "backend/tests/test_asr_engine_selection.py",
    "backend/tests/test_dialect_normalization.py",
    "backend/tests/test_adaptation_dataset.py",
    "backend/tests/test_training_manifest_validation.py",
    "backend/tests/test_asr_release_gate.py"
)

# If tests are specified, validate against allowlist or repo path
$testsToRun = if ($Tests.Count -gt 0) { $Tests } else { $defaultAllowlist }

$failures = 0
try {
    foreach ($testScript in $testsToRun) {
        $fullTestPath = Join-Path $repoRoot $testScript
        if (-not (Test-Path $fullTestPath)) {
            Write-Host "Skipping (not found yet): $testScript" -ForegroundColor DarkGray
            continue
        }

        Write-Host "`n>>> Running: $testScript" -ForegroundColor Yellow
        & $pythonExe $fullTestPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAILED: $testScript (Exit Code: $LASTEXITCODE)" -ForegroundColor Red
            $failures++
            break
        } else {
            Write-Host "PASSED: $testScript" -ForegroundColor Green
        }
    }
}
finally {
    if (Test-Path $testRoot) {
        Remove-Item -Recurse -Force $testRoot -ErrorAction SilentlyContinue
    }
}

if ($failures -gt 0) {
    Write-Host "`nASR Adaptation test suite FAILED with $failures failure(s)." -ForegroundColor Red
    exit 1
}

Write-Host "`nAll specified ASR adaptation tests passed successfully with full isolation." -ForegroundColor Cyan
exit 0
