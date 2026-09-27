# Medora Dialect Accuracy and Controlled Adaptation Implementation Plan

> **For agentic workers:** Implement task-by-task using `superpowers:executing-plans` if available, or the equivalent native Antigravity workflow. Track the checkboxes. This is a handoff plan, not evidence that the feature or its accuracy has been verified. Do not require a particular agent plugin to execute it.

**Goal:** Improve recognition of Moldovan regional Romanian, Russian, English, and mixed-language hospital meetings without silently changing meaning, while building a verified correction corpus for later model adaptation.

**Architecture:** Preserve decoder output, apply versioned conservative normalization, and keep human edits separate. Collect explicitly verified audio/text pairs, evaluate every change against held-out audio, and release approved vocabulary/model versions deliberately. Extend the existing application and its two ASR runtimes; do not replace the pipeline.

**Tech stack:** Existing FastAPI/Pydantic backend, JSON meeting repository, React/TypeScript frontend, faster-whisper/CTranslate2 locally, whisper.cpp on the Mac speech server, and its existing SQLite job queue. Add a small SQLite adaptation catalog for deduplication and dataset provenance; do not migrate application storage. Training dependencies belong in a separate environment.

**Spec:** The self-contained design brief and contracts below incorporate the user's dialect-adaptation proposal and the accuracy review. Proposed defaults are engineering starting points, not measured accuracy guarantees.

## Global constraints

- Read `AGENTS.md`, `docs/IMPLEMENTATION_STATUS.md`, and affected source before implementation. Source wins when older status notes disagree.
- Preserve current user changes. Inspect the working tree before edits; do not touch unrelated files or the existing untracked `medora_codebase.zip`.
- Never send hospital email during development or evaluation. Use supervised meetings, fake recipients, local dead SMTP, and mocked delivery. Preserve human approval before every email.
- No automatic vocabulary promotion, automatic training, or automatic deployment. An ordinary transcript edit is not approval to reuse audio for training.
- Do not upload recordings, names, datasets, or model artifacts to external services. Real recordings and derived labels stay outside tracked fixtures.
- Do not import model runtimes in remote-provider or unit-test paths. Do not run two inference processes on the existing GPU or run Whisper alongside Ollama without checking memory availability.
- Do not add PostgreSQL, Redis, a new job service, broad authentication changes, or unrelated UI redesign. The learning view is for the existing trusted local prototype; a typed reviewer name is not authenticated clinician authorization.
- New learning and dynamic-context features default off. Original ASR and review remain usable with them disabled.
- Run tests with all storage paths isolated through environment variables before importing `app`; do not rely on assigning `settings.DATA_DIR` later.
- Missing real annotations/hardware may block accuracy claims or model release, but must not block implementing and testing the offline plumbing. Report those gates honestly.

## Review focus

1. Legacy text already normalized by the old engine must never be relabeled as pristine decoder evidence (Task 1).
2. An intentional empty reviewer edit must not resurrect the original utterance (Tasks 1 and 4).
3. Retried saves, stale revisions, and interrupted collection must not duplicate examples or train on obsolete text (Tasks 3 and 4).
4. Context arriving at an older or unsupported remote engine must never silently claim to have affected recognition (Task 6).
5. A model with better average WER but worse negation, dose, or language fidelity must not pass the release gate (Tasks 2 and 10).

## Design brief and non-negotiable contracts

### Text and evidence

- For new decodes, `raw_text` means untouched decoder text, apart from the existing boundary whitespace trim. Record that convention. Audio remains the underlying evidence; ASR text is a hypothesis.
- Add `normalized_text: str | None`, `raw_text_origin: Literal['decoder', 'legacy_unknown'] = 'legacy_unknown'`, and `normalization_version: str | None` to `TranscriptSegment`.
- `display_text` selects `corrected_text` when it is not `None`, then `normalized_text` when it is not `None`, then `raw_text`. Use explicit null checks in Python and `??` in TypeScript. An empty string is a valid reviewed removal, but not a training label.
- Keep the existing `corrections` field for compatibility. Extend `Correction` with optional rule ID, source/target spans, stage, and rule-set version. Preserve existing `was`, `now`, and `score`; score is a matching score, not probability of correctness.
- Do not reverse substitutions to fabricate old raw text. Old rows retain their saved content and become `legacy_unknown`. Only a new decode from source audio can supply new decoder evidence.
- Normalization never translates, expands abbreviations into assumed clinical statements, removes negation, changes numeric values/units, or establishes speaker identity. Mixed spans keep their original scripts.
- Add a transcript `revision` independent of meeting/minutes revision. Every accepted text/speaker change increments it; a no-op does not.

### Reviewer edits and training eligibility

- Record edit kind: `transcription`, `normalization`, `translation`, `redaction`, or `editorial`; default `editorial` for existing clients.
- Each correction event has a UUID, meeting/segment IDs, transcript revision, previous displayed text, new text, reviewer label, UTC time, and verification status. Retain history of successive edits rather than overwriting it.
- A separate verification action ties approval to one exact event and audio interval. Require `verified_against_audio`, explicit permitted training reuse, and a nonempty verbatim transcription. Corrections to legacy-origin segments require complete re-listening and relabeling of the clip.
- Store original source text, normalized text, and training label separately. Never use machine-normalized text as an acoustic training label merely because it looks correct.
- Training records carry audio checksum, sample rate, start/end sample offsets, model/decoder/context versions, pseudonymous speaker group, language spans, review provenance, and dataset eligibility reason. Do not store email addresses or voiceprints.
- No edits are automatically promoted. Candidate counts represent distinct accepted events, recordings, and speakers, not repeated saves.

### Scope of context

- Use approved department vocabulary, meeting agenda terms, and attendee names as optional recognition hints. A roster name is never proof of who spoke.
- The current meeting model lacks a meeting-level department field. Add optional `asr_department: str | None` as ASR-only context; it must not change delivery routing. Do not infer a department from the first attendee.
- Treat agenda text as data: tokenize/filter it into bounded terms; never pass the whole agenda as instructions.
- Keep per-language hints and the existing default cap of 80 actual Whisper tokens. Budget at the engine using its tokenizer; validate again on the remote worker.
- Reuse the existing echo detection and retry-without-hotwords implementation. Do not reinstate the deprecated long trilingual `initial_prompt`.
- Context is immutable per job. Record a context hash and actual applied/ignored capability status in results.

### Evaluation and release

- Maintain independent train, development, and locked test manifests. A recording or overlapping audio region cannot appear in multiple splits. Include a speaker-disjoint evaluation subset and explicitly report speakers that recur across recordings.
- A proposed initial allocation is 70/15/15 by recording groups, adjusted only before freezing to obtain coverage. Ratios alone do not establish sufficient test size.
- Annotate verbatim RO/RU/EN speech, within-utterance switches, silence, overlap, uncertain/inaudible spans, and speaker turns. Resolve disputed critical annotations with a second qualified reviewer.
- Evaluate raw recognition and normalized presentation separately; use one published scoring policy for all candidates. Never translate references or normalize away dose/negation errors to improve scores.
- Use the existing synthetic text extraction fixture only for downstream extraction regression. It is not an ASR gold dataset.
- Learning-data consent and retention are explicit. Deleting a meeting or withdrawing reuse removes eligibility and invalidates dependent datasets/artifacts. This cannot undo learning already embedded in weights; affected models require replacement/retraining or retirement.

## Delivery milestones

| Milestone | Tasks | Independently useful result |
|---|---|---|
| A: Trustworthy evidence and measurement | 0–2 | Preserved original text and reproducible audio scorer |
| B: Verified feedback | 3–4 | Auditable corrections and a reviewable learning inbox |
| C: Context and normalization | 5–7 | Optional, measured meeting hints and conservative rules |
| D: Experimental adaptation | 8–10 | Reproducible datasets, trained candidates, controlled release |

Complete in order. Do not wait for enough training data to ship A–C. Do not claim D is validated from synthetic fixtures.

## Task 0: Establish the baseline and safe test harness

**Read:** `backend/app/services/asr/{base,whisper_engine,whisper_cpp_engine,remote_engine,glossary,lexicon}.py`, `backend/app/speech_server.py`, `backend/app/services/speech/queue.py`, `backend/app/models/{transcript,meeting}.py`, `backend/app/api/v1/endpoints/transcript.py`, `tools/eval/README.md`.

**Create:** `docs/ASR_ADAPTATION.md` as a concise implementation/runbook record, and `scripts/test_asr_adaptation.ps1` as an explicit safe test runner.

- [ ] Record current engine/provider/model identities, enabled features, relevant test outcomes, and dirty files without loading real recordings or credentials.
- [ ] Inspect the existing engine tests and run them using the isolation block below. Record skipped model-dependent cases separately from passing tests.
- [ ] Confirm current source already contains hotword-echo retries and lexicon digit guards. Do not implement them again from stale status notes.
- [ ] Add the test runner with an explicit script allowlist, stopping on a nonzero exit. It must not launch inference, training, live LLM tests, or email benchmarks by default.

**Acceptance:** Baseline failures are attributed; tests cannot create meeting state or exports in the real `data/` tree.

## Task 1: Preserve evidence across every ASR provider

**Modify:** `backend/app/models/transcript.py`, `backend/app/services/asr/{base,whisper_engine,whisper_cpp_engine,remote_engine}.py`, `frontend/src/types/index.ts`, `frontend/src/components/TranscriptViewer.tsx`.

**Create/test:** `backend/tests/test_transcript_text_provenance.py`; extend `backend/tests/test_{asr_engine_options,whisper_cpp_engine,remote_asr_engine}.py`.

**Interface:** `TranscriptSegment.display_text` follows the contract above. Every new local decoder sets `raw_text_origin='decoder'`; an older remote response defaults to `legacy_unknown`. Remote validation must preserve supported provenance fields without trusting identity fields.

- [ ] Write failing cases asserting `raw_text == decoder_text`, `normalized_text == corrected_variant`, unchanged speaker state, legacy migration, round-trip serialization, and explicit `corrected_text=''` producing `display_text=''`.
- [ ] Separate decoder text from the result of `correct_segment()` in both local engines. Preserve existing visible output when normalization is enabled.
- [ ] Update consumers to use null-safe display selection, including transcript search, copy, edit initialization, extraction, and evidence quotes. Keep raw text available in an expandable original-text view.
- [ ] Run the new script and affected provider tests. Build the frontend. Verify legacy transcript load, human edits, and language badges manually with synthetic data.

**Acceptance:** New raw evidence is preserved on all supported paths; existing transcripts remain readable; empty reviewer deletions stay empty. Do not backfill invented raw evidence.

## Task 2: Build the audio evaluation harness before adaptation

**Create:** `tools/eval/asr_schema.py`, `tools/eval/asr_metrics.py`, `tools/eval/run_asr_eval.py`, `tools/eval/ASR_README.md`, `tools/eval/fixtures/asr_synthetic.json`, `backend/tests/test_asr_evaluation.py`.

**Interfaces:** `score_asr(reference: dict, hypothesis: dict) -> dict`; CLI `python tools/eval/run_asr_eval.py --manifest <path> --hypotheses <path> --output <path>`. These score saved hypotheses without invoking the meeting pipeline. Add a separate explicit `--run-inference` mode only after offline scoring works.

- [ ] Test known substitution/insertion/deletion counts; empty/silence references; RO diacritics; Cyrillic; mixed-script text; entity false positives; decimal/unit changes; negation reversals; missing hypothesis segments; and a better-WER candidate with worse critical errors.
- [ ] Define manifest schema: recording/checksum, duration, pseudonymous speaker groups, split, annotated intervals/verbatim text, language spans, entity spans, critical facts, acoustic condition, annotation status. Reject overlap across splits, duplicate checksums, and inconsistent timestamps.
- [ ] Report corpus WER using summed edit counts, per-language/condition WER, mixed-utterance WER, entity precision/recall/F1, critical-fact errors, silence insertions, unwanted translation, timing, and reviewer effort where measured. Report speaker metrics only when gold and hypothesis speaker timelines exist. Missing annotations produce `not_measured`, never zero error.
- [ ] Freeze tokenizer/scoring normalization and retain scoring-policy version. Add deterministic paired bootstrap intervals clustered by recording; record seed, recording counts, and word counts.
- [ ] Specify a first annotation pilot of approximately 2–3 hours across multiple meetings, speakers, microphones, and language mixtures as a planning target, not a sufficiency guarantee. Keep corpus collection external to tracked code; issue coverage reports for missing slices.
- [ ] Run synthetic metric tests. Once authorized annotated audio is available, save a baseline report and manifest checksum before tuning.

**Acceptance:** Scorer math is verified offline. No accuracy claim or promotion is possible from missing gold or the 11-line extraction fixture.

## Task 3: Add durable correction history and collection

**Create:** `backend/app/models/adaptation.py`, `backend/app/services/learning/{__init__,store,correction_collector}.py`, `backend/tests/test_correction_collection.py`.

**Modify:** `backend/app/models/transcript.py`, `backend/app/api/v1/endpoints/transcript.py`, `backend/app/core/config.py`, `.env.example`.

**Interfaces:** `CorrectionEvent` implements the edit contract; transcript stores `correction_events: list[CorrectionEvent]` and `revision: int = 1`. `collect_event(event_id: str, meeting_id: str) -> CollectionResult`, where status is `collected`, `ineligible`, or `retry_required`. Adaptation catalog is SQLite under `ADAPTATION_DIR`; event UUID is unique.

- [ ] Write cases for repeated request IDs, same-ID/different-body conflicts, stale revision returning 409 without writes, multiple successive edits, no-op saves, deletion text, and collector failure after a successful transcript save.
- [ ] Extend the existing route `/api/v1/meetings/{meeting_id}/transcript/segments/{segment_id}` with optional expected revision, request ID, edit kind, and reviewer metadata. Keep old callers functional but ineligible for verified training until the separate verification flow supplies missing evidence.
- [ ] Save text, new transcript revision, and correction event together inside the existing repository lock and single transcript JSON write. Treat this saved event as the durable source for collection; no successful transcript save depends on a second SQLite write succeeding.
- [ ] Project eligible events into the adaptation catalog idempotently. Add `python -m app.services.learning.correction_collector --reconcile` to retry saved-but-uncollected events. Never report collection success before durable storage.
- [ ] Add `ASR_LEARNING_ENABLED=false` and `ADAPTATION_DIR` resolved from configured `DATA_DIR` only when not explicitly set. Disabling learning disables derived collection, not ordinary reviewer edits/history.
- [ ] Run collection tests against fresh temporary stores, including simulated interruption/restart and concurrent duplicate submissions.

**Acceptance:** A saved correction survives collector failure, is collected once on retry, and retains its full edit history. Unverified edits do not create training-ready clips.

## Task 4: Verify corrections in the UI and invalidate stale minutes

**Create:** `backend/app/api/v1/endpoints/learning.py`, `frontend/src/components/learning/LearningCenter.tsx`, `backend/tests/test_learning_review.py`.

**Modify:** `backend/app/api/v1/api_router.py`, `frontend/src/{api/client.ts,types/index.ts}`, `frontend/src/components/{TranscriptViewer,SettingsView}.tsx`, `backend/app/models/extraction.py`, `backend/app/services/pipeline_orchestrator.py`, `backend/app/api/v1/endpoints/{transcript,review}.py`, and the existing delivery dispatchability check in `backend/app/services/delivery/router.py`.

**Interfaces:** `GET /api/v1/learning/corrections`; `POST /api/v1/learning/corrections/{event_id}/verify` with exact revision, audio interval, edit kind, reviewer label, `verified_against_audio`, and `training_reuse_allowed`; `POST .../{event_id}/reject`. All mutation requests use conflict protection. Minutes gain `source_transcript_revision: int | None` and a server-owned `needs_transcript_review` flag.

- [ ] Test that verification of obsolete text returns 409; redactions/translations/editorial edits remain excluded; empty text is excluded; missing reuse permission is excluded; verification metadata cannot claim authenticated clinical authority.
- [ ] Show original decoder text, normalized text, reviewer text, audio playback, and edit history together. Provide an explicit verify action; do not precheck audio verification or training reuse.
- [ ] Show counts for pending/verified/rejected corrections and eligible audio duration. Avoid claims of accuracy improvement based on counts.
- [ ] Stamp the source transcript revision on newly generated minutes. A subsequent transcript text/speaker change marks minutes stale and invalidates approval; retain immutable delivered artifacts. Block approval and every dispatch path for stale minutes. Protect these fields against client overwrite through `PUT /minutes`.
- [ ] Provide an explicit refresh-minutes action through the existing extraction flow, followed by human review. Do not silently overwrite edited minutes or automatically send them. For legacy minutes without provenance, require refresh if the transcript is edited.
- [ ] Run learning-review tests plus existing extraction, speaker, review, and delivery regression tests selected from affected code. Build and walk through the frontend with fake recordings.

**Acceptance:** Reviewers understand what becomes training data, and corrected transcripts cannot coexist with dispatchable stale minutes.

## Task 5: Build deterministic meeting context

**Create:** `backend/app/services/asr/dynamic_context.py`, `backend/tests/test_dynamic_asr_context.py`.

**Modify:** `backend/app/models/{adaptation,meeting}.py`, `backend/app/core/config.py`, `.env.example`, and meeting intake/types where needed to expose optional `asr_department`.

**Interfaces:** `ContextTerm(text, language, source, priority)`; `ASRContext(schema_version=1, terms, context_hash)`; `build_context(meeting: Meeting, approved_terms: list[ContextTerm]) -> ASRContext`; `budget_hotwords(context: ASRContext, language: str, encode: Callable[[str], list[int]], max_tokens: int = 80) -> str | None`.

- [ ] Test deterministic ordering/hash, duplicate spellings, Cyrillic token costs, empty metadata, unsupported languages, very long names, oversized agendas, and a term that would cross the token cap.
- [ ] Use deterministic priority: explicitly supplied meeting terms, approved department terms, attendee names, approved learned vocabulary, then site anchors. Limit the incoming context payload to 200 terms, 128 characters per term, and 32 KiB serialized. Reject oversized remote payloads instead of silently changing them.
- [ ] Extract agenda terms using an approved vocabulary match and bounded token extraction; do not add an LLM or send instructions to the decoder. Skip whole terms that cannot fit; never slice through a token or term.
- [ ] Add `ASR_DYNAMIC_CONTEXT_ENABLED=false`; when disabled retain existing static hotword behavior. When enabled count all static/dynamic hints together within 80 tokens.
- [ ] Run context tests without importing inference engines.

**Acceptance:** Identical inputs produce identical hints/hash, each engine budgets with its actual tokenizer, and ASR department selection never changes recipients.

## Task 6: Carry context through local and remote engines honestly

**Modify:** `backend/app/services/asr/{base,whisper_engine,whisper_cpp_engine,remote_engine}.py`, `backend/app/services/pipeline_orchestrator.py`, `backend/app/speech_server.py`, `backend/app/services/speech/queue.py`, `backend/app/main.py`.

**Tests:** Extend `backend/tests/test_{asr_engine_options,whisper_cpp_engine,remote_asr_engine,speech_server,asr_engine_selection}.py`.

**Interface:** Extend every engine's `transcribe(..., *, context: ASRContext | None = None)` consistently. Remote jobs carry validated context JSON; readiness/results expose `context_schema_versions`, `dynamic_hotwords_supported`, applied context hash, engine/model identity, and an explicit unsupported reason when applicable.

- [ ] Test no-context backward compatibility, unknown schema rejection, context persistence across queue restart, malformed JSON, retry conflicts, echo fallback, and old-worker capability handling.
- [ ] Feed language-specific budgeted hints into the existing faster-whisper decode path and preserve its echo retry. Test windowed and batched strategies separately.
- [ ] Add a backward-compatible SQLite queue migration for context and request fingerprint. The fingerprint includes audio checksum, language, context hash, and inference configuration; same idempotency key with different effective input returns 409. Preserve queue authentication and existing upload limits.
- [ ] Inspect the installed whisper.cpp version and tokenizer/prompt capabilities. Do not pretend faster-whisper `hotwords` exists there. Default Mac dynamic hints to unsupported until an engine-specific bounded implementation and audio A/B check pass. Do not map hints silently into the deprecated unrestricted prompt.
- [ ] With unsupported remote context, continue baseline transcription only when explicitly configured to allow fallback; report `context_applied=false` and the reason in the UI/result. Otherwise return an actionable capability error. Default fallback is baseline with visible status.
- [ ] Run fake-engine/transport tests; then an explicitly invoked synthetic LAN smoke test. Recheck that remote selection never imports CUDA/Whisper into the backend process.

**Acceptance:** The app can explain whether hints were actually applied. Mac baseline remains functional even before engine-specific contextual biasing is validated.

## Task 7: Add conservative, versioned normalization and rule review

**Create:** `backend/app/services/asr/dialect_adapter.py`, `backend/app/resources/language/{ro_MD,ru_MD,code_switch}.json`, `backend/app/services/learning/pattern_miner.py`, `backend/tests/test_dialect_normalization.py`.

**Modify:** `backend/app/services/asr/lexicon.py`, `backend/app/models/adaptation.py`, learning endpoints/view from Task 4, and shared normalization calls in the two local engines.

**Interfaces:** `NormalizationRule(id, language, variants, canonical, scope, action, version, approval)` where action is `safe_replace` or `suggest_only`; `normalize_dialect(text: str, language: str, rules: list[NormalizationRule]) -> NormalizationResult(text, corrections, suggestions)`; `mine_candidates() -> list[RuleCandidate]`.

- [ ] Test exact variants, Unicode boundaries, glued digits, negation, units, ambiguous department expressions, overlapping rules, rule chaining, mixed-language spans, and disabled/rolled-back rules.
- [ ] Start with a minimal clinician-reviewed spelling set; ship no invented dialect dictionary. Ambiguous examples such as “a dat la analiză” remain suggestion-only. Existing lexicon behavior is regression-tested before any rule is moved.
- [ ] Apply approved replacements using stable original-source spans, longest-match precedence, no cascading replacement, and a deterministic rule-set version. No clinical stem/fuzzy replacement. Apply mixed-language rules only to validated spans; otherwise suggest without mutation.
- [ ] Mine only eligible reviewed transcription edits with a conservative token diff. Multi-edit or paraphrased sentences go to manual inspection rather than generating broad substitutions.
- [ ] Three distinct approved events may make a candidate visible; they never approve it. Show recording/speaker diversity and contradictory examples. Store separate decisions for recognition hints and automatic replacements; clinical candidates require recorded clinician review in this trusted prototype.
- [ ] Keep packaged seed rules in source and approved local rule versions in `ADAPTATION_DIR`; do not write learned patient/participant vocabulary into tracked JSON. Persist approval/rejection/rollback history.
- [ ] Run normalization tests and Task 2 A/B scoring of baseline, context-only, normalization-only, and combined outputs on the same audio.

**Acceptance:** Rules cannot silently alter critical facts; measured effects distinguish recognition gains from presentation changes.

## Task 8: Build verified datasets and enforce lifecycle rules

**Create:** `backend/app/services/learning/{dataset_builder,retention}.py`, `deploy/scripts/build_asr_dataset.py`, `backend/tests/test_adaptation_dataset.py`.

**Modify:** `backend/app/storage/{repository,file_manager}.py` and audio replacement path to invalidate adaptation records when source audio changes.

**Interfaces:** `build_dataset(output_dir: Path, seed: int = 42) -> DatasetManifest`; `invalidate_source(meeting_id: str, reason: str) -> InvalidationReport`. Dataset manifest records eligible event IDs, checksums, grouping, split assignment, label policy, and manifest version.

- [ ] Test incorrect sample rate, missing audio, invalid interval, clipped word boundaries, overlap exclusions, redacted labels, duplicate audio under different paths, speaker/recording leakage, revoked permission, and changed source checksums.
- [ ] Export 16 kHz mono clips with complete labels; split only at verified boundaries, normally 2–28 seconds. Longer/shorter cases require relabeling or explicit exclusion. Do not add unlabeled boundary padding. Verify exact sample offsets and that uncertain spans are either represented by the documented label policy or excluded.
- [ ] Mix verified error examples with verified correct representative speech. Never assume an untouched segment is correct. Balance/report language, speakers, department, and acoustic conditions without promising universal target hours.
- [ ] Create train/dev/test manifests by recording groups and construct a speaker-disjoint challenge subset. Freeze the locked test set before training; do not use it for selecting hyperparameters or mined vocabulary.
- [ ] Store reproducible dataset versions under `ADAPTATION_DIR`, outside Git. Validate output paths stay inside the configured root and refuse overwrite of an existing version.
- [ ] On source deletion/replacement/withdrawal, immediately exclude affected examples, invalidate dependent manifests/models, and schedule/retry physical deletion of derived clips including exported copies tracked in the catalog. Surface locked-file cleanup failures. Do not promise model unlearning.
- [ ] Run dataset/lifecycle tests using generated synthetic WAVs; inspect a small authorized export manually before training.

**Acceptance:** Every audio/text pair is traceable and permissioned, splits cannot leak by recording, and deletion cannot leave a dataset silently eligible.

## Task 9: Run a bounded LoRA feasibility experiment

**Create:** `deploy/scripts/fine_tune_whisper.py`, `deploy/training/requirements.txt`, `deploy/training/README.md`, `backend/tests/test_training_manifest_validation.py`.

**Interface:** CLI requires explicit `--dataset`, `--base-model`, `--output-dir`, and `--device`; defaults to `--dry-run`. Actual training requires `--train`. Do not launch training from the UI or correction endpoint.

- [ ] Validate dataset eligibility, split separation, label policy, base-model revision, compatible tokenizer, available disk, and output destination before loading model weights. Add offline tests for these validations.
- [ ] Pin a compatible training stack in an isolated environment after checking current official upstream documentation. Keep it out of backend runtime requirements and preserve the existing Python environment.
- [ ] Run a short hardware smoke test on the chosen Mac/GPU: forward/backward pass, checkpoint save/reload, sample decode, peak memory, elapsed time. Start with a small multilingual model to test feasibility; compare production candidates against the actual current baseline. Do not call a small-model result an improvement over turbo without measurement.
- [ ] Configure LoRA target modules/rank explicitly, log actual trainable parameter count, use fixed seeds, evaluate on development data, and retain the best eligible checkpoint. Do not assume 1–2% parameters or a particular memory requirement.
- [ ] Record training config, data/model hashes, library versions, device, loss curves, dev metrics, and early-stop decision. Keep RO/RU/EN representative examples to assess forgetting; exclude the locked test set.
- [ ] If MPS cannot train the chosen configuration reliably, record the failure and use a supported GPU environment only when available. Do not install or rent infrastructure implicitly.

**Acceptance:** A reproducible experimental checkpoint and hardware report exist, or feasibility is explicitly blocked with the rest of the feature still usable. No model is activated here.

## Task 10: Convert, evaluate, register, and release candidates

**Create:** `deploy/scripts/{export_asr_model,evaluate_asr,manage_asr_model}.py`, `backend/app/services/learning/model_registry.py`, `backend/tests/test_asr_release_gate.py`.

**Interfaces:** Registry entries include immutable artifact ID/checksum, base/adapter/dataset versions, target runtime, quantization, evaluation report hash, approval, lifecycle status, and previous active artifact. Status is `candidate`, `evaluated`, `approved`, `active`, `retired`, or `invalidated`. `evaluate_asr.py --baseline ... --candidate ... --manifest ... --output ...` produces pass/fail/insufficient-evidence.

- [ ] Test missing strata, fake/mismatched report hashes, baseline-equal results, critical regressions, missing labels, engine mismatch, revoked data, failed model load, and rollback.
- [ ] Merge LoRA into the exact base model using the supported training framework, then export for the actual runtime. For faster-whisper, convert to CTranslate2. For Mac, verify the installed whisper.cpp converter supports the merged architecture and create its required artifact; if unsupported, keep that target blocked rather than activating a CTranslate2 artifact there.
- [ ] Evaluate the final converted/quantized artifact, not just the training checkpoint. Pin decoding/context/normalization settings and identical audio for comparisons. Include no-hints and realistic-hints runs.
- [ ] Use these initial release-policy defaults, frozen before looking at locked-test results: at least 5% relative corpus WER improvement; upper bound of the paired 95% recording-bootstrap WER-difference interval below zero; no worse point-estimate WER for RO, RU, EN, or mixed speech; no increase in annotated critical-fact errors, silence hallucinations, or unwanted translations; entity precision and recall each no lower than baseline; target-hardware runtime no more than 20% slower and within measured memory capacity. Missing coverage/metrics means insufficient evidence, not pass. These are proposed product gates, not clinical certification.
- [ ] Require separate human approval tied to the exact report/artifact hash. Passing a numerical gate does not activate a model. Reusing the locked set for repeated selection requires a new independently held-out confirmation set before making a final quality claim.
- [ ] Implement explicit `register`, `approve`, `activate`, and `rollback` commands. Use a maintenance boundary: finish/stop queued work safely, load and smoke-test the candidate, switch the active version atomically, preserve the previous artifact. Do not hot-swap during a meeting or auto-send any resulting output.
- [ ] Verify baseline rollback after simulated candidate load failure. Record actual target-hardware and real-audio outcomes, or leave the artifact as an unverified candidate.

**Acceptance:** Only an approved, compatible, evaluated artifact can become active; every meeting records the model actually used; failure returns to the previous working version.

## Verification commands and isolation

Run from `F:\DEEPTECH` in a dedicated PowerShell process. The runner must set these before any application import:

```powershell
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('medora-adaptation-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$env:PYTHONPATH = 'backend'
$env:DATA_DIR = $testRoot
$env:UPLOADS_DIR = Join-Path $testRoot 'uploads'
$env:EXPORTS_DIR = Join-Path $testRoot 'exports'
$env:FIXTURES_DIR = Join-Path $testRoot 'fixtures'
$env:VOICEPRINTS_DIR = Join-Path $testRoot 'voiceprints'
$env:OUTBOX_DIR = Join-Path $testRoot 'outbox'
$env:ADAPTATION_DIR = Join-Path $testRoot 'adaptation'
$env:MODELS_DIR = 'F:\DEEPTECH\data\models'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:SMTP_HOST = '127.0.0.1'
$env:SMTP_PORT = '9'
$env:ALLOW_SIMULATED_DELIVERY = 'false'
$env:WHISPER_DEVICE = 'cpu'
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:LLM_API_BASE_URL = 'http://127.0.0.1:9'
& .\.venv\Scripts\python.exe backend/tests/test_transcript_text_provenance.py
if ($LASTEXITCODE -ne 0) { throw 'Transcript provenance tests failed' }
```

Each new test file must be executable with the repository's existing script convention, return nonzero on failure, and print explicit skips. Run the corresponding new script after each task and the affected existing scripts. Hardware tests are separate, deliberate invocations with the real device configuration; the CPU isolation block is not an inference benchmark.

Frontend verification: run `npm.cmd run build` in `frontend`, then inspect the affected UI flows with synthetic data. Do not add tests solely to mirror implementation; focus on the behavioral contracts listed per task.

## Final handoff from Antigravity

- Provide changed files, milestone completion, exact passing/failing/skipped checks, and any deviations from this plan.
- Link saved evaluation reports and state which use synthetic versus real annotated audio. Separate plumbing correctness, recognition accuracy, extraction accuracy, and runtime performance.
- State current feature flags, active model/rule versions, rollback procedure, data deletion behavior, and remaining blocked gates.
- Update `docs/IMPLEMENTATION_STATUS.md` and `docs/CODE_CONTEXT.md` only for newly verified facts. Keep the additions concise.
- Review the diff for unrelated edits, raw audio/identifiers in tracked files, and any email side effects. Keep changes in reviewable milestone commits when commits are part of the execution workflow; never include unrelated working-tree files.
- Do not report “self-learning complete,” a percentage accuracy gain, production readiness, or clinical reliability without the corresponding evidence.

## Official implementation references

Recheck the installed versions and these primary references before training/conversion; this plan does not pin future compatibility:

- [faster-whisper implementation and conversion](https://github.com/SYSTRAN/faster-whisper)
- [Hugging Face PEFT LoRA](https://huggingface.co/docs/peft/developer_guides/lora)
- [CTranslate2 Transformers conversion](https://opennmt.net/CTranslate2/guides/transformers.html)
- [whisper.cpp runtime and model tooling](https://github.com/ggml-org/whisper.cpp)
