# Medpark - one-time local LLM provisioning for Ollama (Windows)
#
# Run ONCE on a networked machine during development. Afterwards the model lives in
# %USERPROFILE%\.ollama\models and inference is 100% local: no request ever leaves 127.0.0.1.
#
#   powershell -ExecutionPolicy Bypass -File deploy\scripts\setup_ollama.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\scripts\setup_ollama.ps1 -Profile server16gb
#
# For the air-gapped demo: run this beforehand, then close the Ollama tray app (it is the only
# component that checks for updates) and start the server explicitly with `ollama serve`.
#
# The server MUST run with these two environment variables, otherwise the Modelfile's
# `num_gpu 37` does not fit in 4 GB and Ollama silently offloads layers to the CPU (~5x slower):
#   $env:OLLAMA_FLASH_ATTENTION = "1"
#   $env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
#   ollama serve
# This script only checks the running server; it never starts, restarts or kills one.

param(
    [ValidateSet("laptop4gb", "server16gb")]
    [string]$Profile = "laptop4gb"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollama)) { $ollama = "ollama" }   # fall back to PATH

# Exact GGUF per hardware profile. Both are ungated, permissively licensed, and pulled straight
# from the bartowski HuggingFace repos so the quant is deterministic rather than whatever a
# library tag happens to point at this week.
$profiles = @{
    laptop4gb  = @{ Base = "hf.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"; Ctx = 4096;  Note = "fits fully in ~3 GB free VRAM on an RTX 3050 (4 GB)" }
    server16gb = @{ Base = "hf.co/bartowski/Qwen_Qwen3-14B-GGUF:Q4_K_M";              Ctx = 12288; Note = "the brief's single-16GB-GPU reference server" }
}
$p = $profiles[$Profile]

Write-Host "==> Profile: $Profile  ($($p.Note))"
Write-Host "==> Pulling $($p.Base) ..."
& $ollama pull $p.Base
if ($LASTEXITCODE -ne 0) { throw "ollama pull failed" }

# Materialise the Modelfile for this profile from the checked-in template.
$template = Get-Content (Join-Path $repoRoot "deploy\ollama\Modelfile") -Raw
$rendered = $template -replace "FROM hf\.co/\S+", "FROM $($p.Base)" -replace "PARAMETER num_ctx \d+", "PARAMETER num_ctx $($p.Ctx)"
$tmp = Join-Path $env:TEMP "medpark-extractor.Modelfile"
Set-Content -Path $tmp -Value $rendered -Encoding UTF8

Write-Host "==> Creating alias 'medpark-extractor' (num_ctx=$($p.Ctx)) ..."
& $ollama create medpark-extractor -f $tmp
if ($LASTEXITCODE -ne 0) { throw "ollama create failed" }
Remove-Item $tmp -ErrorAction SilentlyContinue

Write-Host "==> Warm-up + GPU residency check ..."
if (-not $env:OLLAMA_FLASH_ATTENTION -or -not $env:OLLAMA_KV_CACHE_TYPE) {
    Write-Warning "OLLAMA_FLASH_ATTENTION / OLLAMA_KV_CACHE_TYPE are not set in THIS shell. They must be set in the"
    Write-Warning "environment of the ollama serve process (measured: without them the 4B model is only 66% on GPU)."
}
& $ollama run medpark-extractor 'Răspunde doar cu JSON: {"ok": true}' | Out-Null
$ps = & $ollama ps | Out-String
Write-Host $ps
if ($ps -match "100%\s+GPU") {
    Write-Host "==> Residency OK: 100% GPU (expected ~2.7 GiB VRAM, ~31 tok/s decode on an RTX 3050 4 GB)."
} else {
    Write-Warning "Model is NOT fully on the GPU. Decode drops ~5x and the 15-minute budget will not hold."
    Write-Warning "Set OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 for the server, close other GPU apps, re-run."
}

Write-Host ""
Write-Host "Done. The app expects:"
Write-Host "  LLM_PROVIDER=ollama"
Write-Host "  LLM_API_BASE_URL=http://127.0.0.1:11434"
Write-Host "  LLM_MODEL_NAME=medpark-extractor"
Write-Host "  REQUIRE_LOCAL_LLM=true   (pipeline fails at preflight in ~3 s when the model is not serving)"
Write-Host "Server environment (required for 100% GPU residency): OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0"
Write-Host "If 'ollama ps' does not report 100% GPU, decode speed drops ~5x and the 15-minute"
Write-Host "target will not hold - close other GPU applications and re-run."
