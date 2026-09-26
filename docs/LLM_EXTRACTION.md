# Local LLM extraction (Stage 4)

Last revised: 26 September 2026. Numbers marked *measured* were taken on the development laptop
(RTX 3050, 4 GB VRAM, Windows 11) against Ollama 0.34.4; everything else is either a contract in
code or an estimate and is labelled as such.

## 1. Architecture

```
Transcript.to_indexed_lines()            "0 S1: Bună dimineața ..." / "1 Да, я ..." (index = only citation key)
        │
        ▼
chunker.build_chunks()                    ≤ LLM_CHUNK_TOKENS per chunk, never splits a line,
        │                                 prefers a speaker-turn cut, 200-token overlap re-shown
        ▼  (sequential, never concurrent)
OllamaClient.complete_json(MAP_SCHEMA)    POST /api/chat, stream:false, format:<JSON Schema>,
        │                                 temperature 0, top_k 1, seed 1234, num_predict 1100
        ▼
filter_chunk_items() -> merge_items()     drop out-of-range / overlap-only items; fold duplicates
        │                                 (evidence intersects OR ratio ≥ 0.82 within 12 lines)
        ▼
OllamaClient.complete_json(SYNTHESIS)     ONE call over the merged item list (not the transcript):
        │                                 summary_ro, summary_en, agenda_topics
        ▼
evidence_idx -> EvidenceQuote             quote/start/end/speaker COPIED from the cited segment
resolve_owner() / audit_free_prose()      name guard (section 4) -> needs_name_review
evidence_validator.validate_and_enrich()  verbatim check + deadline_phrase -> ISO deadline_date
        │
        ▼  finally:
OllamaClient.unload()                     keep_alive:0 so the next meeting's Whisper has the VRAM
```

Files: `backend/app/services/extraction/{llm_client,chunker,merge,schemas,prompt_templates,llm_engine,validator,heuristic_extractor}.py`.
Config keys: `LLM_*`, `REQUIRE_LOCAL_LLM`, `LLM_FALLBACK_MODE` in `backend/app/core/config.py` (mirrored in `.env.example`).

### Why Ollama, why Qwen3-4B-Instruct-2507 Q4_K_M

- Ollama's native API gives grammar-constrained decoding (`"format": <JSON Schema>`) that is
  **honoured exactly** (verified: `type/properties/required`, `enum`, `integer`, `["string","null"]`,
  `minItems/maxItems`). `message.content` is therefore always valid JSON; there is no repair
  parser for malformed output, only for *semantic* failures.
- The 4B model is the largest RO/RU/EN instruction model that fits **fully** in the ~3 GB of
  VRAM left on a 4 GB card (weights 2.33 GiB + KV cache at ctx 4096). A partially offloaded
  model (Ollama's own estimate put 34 % on the CPU) decodes ~5x slower and would break the
  15-minute budget for a 60-minute meeting. A 7B/14B model does not fit; the 16 GB hospital
  server profile in `setup_ollama.ps1` swaps in Qwen3-14B with ctx 12288 and nothing else changes.
- `deploy/ollama/Modelfile` pins `num_gpu 37` (all 36 blocks + head on GPU), `num_ctx 4096`,
  `temperature 0`, `top_k 1`, `seed 1234`, `num_predict 1100`, and the stop tokens.

### Why the ChatML `TEMPLATE` override must stay

Ollama auto-assigns its thinking-aware "qwen3" template to this GGUF, which force-opens a
`<think>` block in the assistant turn. The *Instruct-2507* variant was never trained on think
tags and answers that block with an immediate EOS (verified: `eval_count=1`, empty content).
The plain ChatML template in the Modelfile makes the same prompt answer normally. **Do not
remove it.**

### Why map/reduce is mandatory

A 60-minute meeting is ~20k transcript tokens even in the compact indexed format (measured:
4,380 tokens for the 703 s audit recording vs 7,757 in the old timestamped format). At
`num_ctx 4096` single-shot extraction is impossible, so chunks of `LLM_CHUNK_TOKENS=2300`
(estimated at `LLM_CHARS_PER_TOKEN=2.0`) are mapped sequentially and merged in Python.

## 2. Index grounding

The LLM never sees timestamps, segment ids, the roster, the meeting date or the title. It cites
integer line indices (`evidence_idx`, 1-3 per item); the engine copies `quote`, `start`, `end`
and `speaker` from the cited `TranscriptSegment`. An index outside the chunk is dropped, an item
with no index left is dropped, and `evidence_validator` re-checks every quote verbatim. Nothing
the model *writes* can become a citation.

## 3. Failure policy (contract C14)

| Event | Handling |
|---|---|
| Ollama/model missing at start | `extraction_engine.preflight()` raises `LLMUnavailable` **before** Stage 1; the meeting is `FAILED` in ~3 s instead of after minutes of ASR. |
| Transport error / 404 / 503 mid-run | `LLMUnavailable` (one 2 s retry on 503) -> extraction aborts; `unload()` still runs. |
| Schema/semantic failure of a chunk | one Romanian repair turn (seed+1); second failure -> ordinal appended to `failed_chunks`, run continues. |
| `failed/total > LLM_MAX_FAILED_CHUNK_RATIO` (0.20) | `ExtractionError`. Otherwise a high-severity "NOTĂ AUDIT: n din m fragmente nu au putut fi procesate ..." item names the time ranges. |
| `REQUIRE_LOCAL_LLM=false` and `LLM_FALLBACK_MODE=heuristic` | `heuristic_extractor` produces the minutes with `is_degraded=True`, `model_version="DEGRADED-heuristic-no-LLM"`. `delivery_router.assert_dispatchable()` refuses to email it (auto-pilot holds at `PENDING_REVIEW`; reviewer approval raises `DeliveryError`). PDF/DOCX carry a red "DRAFT NEVALIDAT — LLM LOCAL INDISPONIBIL" banner. |
| `LLM_FALLBACK_MODE=fail` (default) | there is **no** path to the heuristic extractor. |

Kill-switch summary: with the defaults (`REQUIRE_LOCAL_LLM=true`, `LLM_FALLBACK_MODE=fail`) the
system either produces LLM-grounded minutes or a clearly failed meeting. The degraded draft path
exists only for offline tests and for a deliberately configured demo, and it can never send email.

## 4. Name guard

`resolve_owner(owner_mention, owner_speaker, cited_segments, attendees)` in `validator.py`:

1. normalise (NFKD, no diacritics, casefold); a bare pronoun (`I`, `eu`, `я`, `we`, `noi`, ...) or
   anything shorter than 3 chars is treated as no mention;
2. a mention that is not a substring of the cited segments' text is **discarded** (logged
   "owner mention fabricated") - this is the enforcement point;
3. surviving tokens fuzzy-match the roster (difflib ≥ 0.85 on a token ≥ 4 chars) -> `(name, "roster")`;
4. else `(mention, "mention")` and `needs_name_review=True`;
5. else `owner_speaker` matching `S\d+` -> `("Speaker N", "speaker")`, never a person name;
6. else `("Unassigned", "unassigned")`.

`audit_free_prose()` scans summaries, agenda topics and item texts for capitalised token runs that
appear neither in the transcript, nor in the roster, nor in a whitelist (Medpark, ATI, RMN, CT,
EKG, UPU, month/weekday names, sentence-initial common words). A hit adds ONE high-severity
`RiskOrQuestionItem` naming the tokens and sets `needs_name_review=True`; documents then show
"Verificare nume necesară".

Known wart (Track A): an English first-person speaker yields `owner_mention="I"`, which the
pronoun rule maps to the anonymous `Speaker N` label - verbatim, but useless until a reviewer
confirms the speaker identity.

## 5. VRAM sequencing

Whisper turbo (~1.8 GB in use, ~0.66 GB after `release_model()`) and the LLM (2.70 GiB) cannot
coexist in 4 GB. The orchestrator runs preflight (no model load: `/api/version` + `/api/tags`
only), ASR, `release_model()`, then extraction; the engine unloads the LLM in a `finally`. Never
run two GPU jobs concurrently. Manual unload:

```
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"medpark-extractor","keep_alive":0}'
```

## 6. Provisioning

```powershell
$env:OLLAMA_FLASH_ATTENTION = "1"      # required: without it num_gpu 37 does not fit in 4 GB
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"   # halves the KV cache at ctx 4096
ollama serve                            # in its own window; the tray app is the only updater - close it for the demo
powershell -ExecutionPolicy Bypass -File deploy\scripts\setup_ollama.ps1          # pulls the GGUF, creates 'medpark-extractor', checks 100% GPU
```

The script pulls `hf.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` (sha256 of the blob is
in the Modelfile), renders the Modelfile, creates the alias and prints `ollama ps`; it warns when
the model is not "100% GPU". It never starts, restarts or kills a server.

App-side `.env`: `LLM_PROVIDER=ollama`, `LLM_API_BASE_URL=http://127.0.0.1:11434`,
`LLM_MODEL_NAME=medpark-extractor`, `REQUIRE_LOCAL_LLM=true`. `GET /ready` reports
`llm_service: {engine, model, connected, loaded, mode}` where `loaded` comes from `/api/ps`.

## 7. Measured numbers (development laptop, 26 Sep 2026)

| Quantity | Value | How |
|---|---|---|
| Residency | 100 % GPU, 2.70 GiB VRAM | `ollama ps` / `/api/ps` with the two env vars set |
| Load from disk | 3.5 s (warm page cache) | `load_duration`; a cold start on 26 Sep made the first Track-A map call take 94 s wall, so budget for a slow first call after a reboot |
| Prefill | 1,332 tok/s | `prompt_eval_count / prompt_eval_duration` |
| Decode | ~31 tok/s | `eval_count / eval_duration` |
| 2,612-token chunk round trip | 2.9 s | prefill-dominated map call with an empty answer |
| 314-token structured answer | 11 s | decode-dominated map call |
| Indexed transcript, 703 s recording | 4,380 tokens (vs 7,757 timestamped) | tokenised prompt |

Estimate (not measured): a 60-minute meeting is ~20k tokens -> ~9 map chunks; with ~300-token
answers each that is roughly 9 x (2 s prefill + 10 s decode) + one synthesis call ≈ 2 minutes of
LLM time. This has not been run end-to-end on a real 60-minute recording.

Track-A behaviour on the 11-line RO/RU/EN fragment (`tools/eval/gold/synthetic_trackA.json`): one
decision citing lines [4,5] in Romanian; the "poate ar fi bine..." proposal not extracted; verbatim
`owner_mention "doctorul Popescu"`, verbatim deadline phrases `până luni` / `by Friday`; the risk
line found. The raw ASR of the real audit recording (248 segments, mostly repetition loops)
correctly yields **zero** items - that is the expected result, not an extraction bug.

## 8. Tests and evaluation

- `backend/tests/test_llm_extraction_pipeline.py` - offline unit tests (FakeClient injected via
  `LocalLLMExtractor(client=...)`): indexed lines, chunker, merge, `resolve_owner`,
  `audit_free_prose`, full `extract_minutes` incl. failed-chunk accounting and the ratio abort.
- `backend/tests/test_llm_extraction_live.py` - runs Track A through the real engine; prints
  "SKIPPED: Ollama not reachable" when `/api/version` fails. Never runs Whisper.
- `backend/tests/test_extraction_and_grounding.py`, `test_end_to_end_pipeline.py` - heuristic
  path only (`REQUIRE_LOCAL_LLM=false LLM_FALLBACK_MODE=heuristic`, LLM URL pointed at a dead
  port), assert `is_degraded=True` and that a degraded draft is never dispatched.
- `tools/eval/run_extraction_eval.py` - stdlib scorer (P/R/F1, false-decision rate, owner
  accuracy/fabrication, deadline recall, evidence validity); gold format in `tools/eval/README.md`.

Run any of them with isolated storage and a dead SMTP port, e.g.

```
DATA_DIR=%TEMP%\mp\data UPLOADS_DIR=%TEMP%\mp\uploads EXPORTS_DIR=%TEMP%\mp\exports FIXTURES_DIR=%TEMP%\mp\fixtures
SMTP_HOST=127.0.0.1 SMTP_PORT=9 ALLOW_SIMULATED_DELIVERY=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
PYTHONPATH=backend .venv\Scripts\python.exe backend\tests\test_llm_extraction_pipeline.py
```
