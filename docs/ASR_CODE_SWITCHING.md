# ASR code-switching: what changed, why, what was measured, what is not claimed

Last revised: 26 September 2026 (code-switching pass, contracts K1-K6). Written against the contracts
and the research probe; re-check `backend/app/services/asr/whisper_engine.py` before relying on a detail.

## 1. The bug this pass fixes

`FasterWhisperEngine._run_transcription` used to call `model.transcribe(path, language=None)` **once over
the whole file**. faster-whisper then detects a single language from the first 30 s of audio and stamps it on
every segment. On the real 703 s audit recording (`.audit/real-run`, Romanian/Russian hospital meeting) the
result was:

- 222 of 248 segments tagged `ru`;
- Romanian clinical speech decoded through the Russian language token and rendered as Cyrillic nonsense, e.g.
  `Хемодинамик, инстабил` for *hemodinamic instabil*;
- a 27.7 s hallucinated opening segment;
- 37 of 57 sampled segments with integer-second durations and zero gaps between them.

Each symptom had a verified cause in the faster-whisper 1.2.1 source, listed in section 3.

## 2. What the engine does now (contract K3)

`FasterWhisperEngine.transcribe(audio_path, initial_prompt=None, language=None)` keeps its public signature and
still returns `list[TranscriptSegment]`, but internally:

1. **VAD windows** (`services/asr/windowing.py`): Silero VAD via `faster_whisper.vad.get_speech_timestamps`
   with `VadOptions(threshold=0.5, neg_threshold=0.35, min_speech_duration_ms=250, max_speech_duration_s=20,
   min_silence_duration_ms=400, speech_pad_ms=200)`. Speech chunks are packed into decode windows: chunks
   shorter than `ASR_WINDOW_MIN_S` (1.5 s) merge into the previous window, packing aims at
   `ASR_WINDOW_TARGET_S` (12 s), never exceeds `ASR_WINDOW_MAX_S` (20 s), and a single chunk longer than
   `ASR_WINDOW_HARD_CAP_S` (28 s) is cut. Windows never overlap: the encoder consumes 30 s regardless, so an
   overlap is pure waste and cross-language seam de-duplication is unreliable.
2. **Per-window restricted language identification**: one encoder pass per window
   (`model.encode(pad_or_trim(model.feature_extractor(pcm)))`), `model.model.detect_language(enc)` gives the
   full distribution, and the argmax is taken **only over `WHISPER_LANGUAGES`** (`["ro","ru","en"]`). The
   same encoder output is reused for the decode (`generate_segments(..., encoder_output=enc)`; honoured while
   the window is <= 30 s). Windows shorter than ~4 s carry no usable LID signal and inherit the neighbouring
   window's language. `language="ro"` (or `ru`/`en`) forces that language on every window.
3. **Forced-language decode with hotwords** instead of a prompt: `Tokenizer(hf_tokenizer, True,
   task="transcribe", language=lang)` and `TranscriptionOptions(**DECODE_OPTIONS, hotwords=HOTWORDS_BY_LANG[lang])`.
   `initial_prompt` is accepted for compatibility but **ignored** (logged once at WARNING).
4. **Text/script check** (`services/asr/text_lid.py`): Cyrillic ratio > 0.60 -> `ru`, 0.15-0.60 -> `mixed`,
   otherwise Romanian vs English by stop-words with diacritics weighted twice. This is free and cannot repair a
   wrong decode (Romanian forced through `ru` comes out Cyrillic), so it only **gates a re-decode**.
5. **Rescoring queue**: windows whose top restricted probability is below `ASR_LID_RESCORE_BELOW` (0.70), or
   where the text LID disagrees with the acoustic LID with confidence >= 0.7, are decoded a second time with the
   runner-up language and the hypothesis with the better `avg_logprob` is kept. Nothing else is rescored.
6. **Absolute time stitching**: `generate_segments` returns times relative to the window; the engine adds the
   window start to every segment and every word before it builds `TranscriptSegment`s.
7. **Lexicon correction** (`services/asr/lexicon.py`): near-miss clinical/drug names are corrected in
   `raw_text`; every change is recorded in `corrections[] = {was, now, score}` so the original is recoverable.
   Tokens containing digits are never touched.
8. **Garbage filter**: `compression_ratio > 2.4`, `avg_logprob < -1.5`, `no_speech_prob > 0.85` or no
   alphabetic character -> the segment is **kept** with `is_flagged=True, flag_reason="low_confidence_asr"`.
   The reviewer transcript keeps everything; nothing is deleted.
9. **Run statistics** in `whisper_engine.last_run_stats` (strategy, device, compute type, windows, per-language
   window counts, rescored windows, garbage flags, integer-second durations, zero gaps, VAD / decode / total
   seconds, audio seconds, RTF), copied by the orchestrator into `Meeting.asr_stats` and reported by `/ready`.

New segment fields (K1, all additive with defaults so every stored transcript still validates):
`language_confidence`, `language_source` (`acoustic|text|rescored|manual|legacy`), `language_spans`,
`corrections`, `window_index`, `asr_avg_logprob`, `asr_compression_ratio`, `asr_no_speech_prob`.
`Transcript.compute_stats()` now excludes `und`, expands `mixed` into its span languages and only falls back to
`["ro"]` when nothing was detected.

## 3. Decode options and the reason for each

| Option | Value | Why (verified in faster-whisper 1.2.1 `transcribe.py`) |
|---|---|---|
| `beam_size` / `best_of` / `patience` | 5 / 5 / 1.0 | Unchanged beam search; `best_of` only applies at temperature > 0 |
| `length_penalty` | 1.0 | Default |
| `repetition_penalty` | 1.1 | The repetition loop survived because this and `no_repeat_ngram_size` were off |
| `no_repeat_ngram_size` | 4 | Same |
| `temperatures` | `[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]` | Standard fallback ladder |
| `compression_ratio_threshold` | 2.0 | The loop had compression ratio 2.16, below the default 2.4, so no fallback triggered |
| `log_prob_threshold` | -1.0 | Default |
| `no_speech_threshold` | 0.6 | Default |
| `prompt_reset_on_temperature` | 0.5 | Default |
| `condition_on_previous_text` | **False** | With `True`, the truncated term list stayed in the decoder context for the whole file and the model continued the comma-list |
| `initial_prompt` | **None** | The old 257-token prompt overflowed the 223-token slot; the trilingual framing sentence was the part cut off, leaving only a bare term list, which is what got hallucinated for 27.7 s |
| `prefix` | None | Default |
| `hotwords` | per window, per language, <= 80 tokens | Same mechanism as the prompt but bounded; the full 318-token `MEDPARK_MEDICAL_VOCABULARY` is never sent because it would be truncated |
| `word_timestamps` | **True** | With `False`, segment bounds come only from timestamp tokens (integer seconds, zero gaps: 37/57 sampled). With `True`, bounds are rewritten from the DTW word alignment (1/27) |
| `hallucination_silence_threshold` | 2.0 | Silently a no-op unless `word_timestamps=True` |
| `without_timestamps` | False | Needed for segment boundaries |
| `max_initial_timestamp` | 1.0 | Default |
| `suppress_blank` / `suppress_tokens` | True / `[-1]` | Defaults (non-speech tokens suppressed) |
| `multilingual` | **False** | See section 5: unrestricted LID chose `en` on Romanian speech and Whisper *translated* it |
| `max_new_tokens` / `clip_timestamps` | None / `"0"` | Defaults; windows are cut by VAD, not by clip timestamps |

## 4. What was measured (before / after)

All numbers below are from this machine (RTX 3050 4 GB, faster-whisper 1.2.1, CTranslate2 4.8.2, model
`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, cached snapshot `0a363e91...`).

**Before (single whole-file pass, GPU, int8_float16, beam 5)** on the 703 s audit recording:
transcription 134 s (RTF 0.19), end-to-end 201 s. 222/248 segments tagged `ru`; Romanian passages decoded as
Cyrillic; 27.7 s hallucinated opening; integer-second durations and zero gaps on most segments.

**Research probe (CPU, first 180 s of `normalized_16k.wav` from the audit run)** with VAD-packed ~12 s windows,
per-window LID restricted to `{ro, ru, en}` and forced-language decode: 13 windows, 11 `ru` + 2 `ro`. Window 4
(56.5-79 s) flipped from Cyrillic gibberish to *"Asa, transferat acolo, acolo continuo a fost descărcat volemic"*
(`avg_logprob` -0.48 vs -0.83 for the Cyrillic decode of the same audio). The text/script check caught 5 of 27
acoustic-vs-text disagreements across probe variants; the rescoring rule queued ~6 of 13 windows, i.e. one
extra decode each.

**After (windowed strategy, GPU, first 180 s of the same recording)** — `scripts/asr_ab_benchmark.py --strategy
windowed --seconds 180`, one run on 26 Sep (`%TEMP%/asr_ab_windowed_180.json`, CUDA, int8_float16, turbo, VRAM peak
1,738 MiB):

| Metric | Value |
|---|---|
| wall / RTF | 15.3 s / **0.085** (projected 5.1 min of ASR per 60 min of audio; the budget needs <= 9 min) |
| windows / languages | 15 windows: ru 12, ro 2, en 1; 2 inherited (< 4 s), 4 rescored |
| segments | 23; integer-second durations **0** (was 37/57 sampled); zero gaps 4; consecutive duplicate texts 0 |
| first segment | 3.96 s long (the old run opened with a 27.7 s hallucinated term list) |
| text/acoustic agreement | 0.93 of decided windows; mean `avg_logprob` -0.60; garbage-flagged 0 |
| the demo window | 56.5-74.6 s decoded as Romanian: *"Așa, a transferat acolo, acolo în continuă el a fost descărcat volemic și acum au jocs pe motivul de instabilitate hemodinamică, tensiunele 80x40 cu dozele 0.22 de nor și DOBOI cu 4"*; 79-99 s likewise readable Romanian |

The before and after columns are **not the same audio length** (703 s whole-file single pass vs a 180 s excerpt of
it), so the RTFs compare a full run with an excerpt; the `baseline` strategy of the benchmark exists to produce the
like-for-like column and had not been run at the time of writing. The `batched` strategy is likewise unmeasured.

**Failure modes visible in that same run (read the JSON before quoting the numbers above):**

- **Hotword echo.** Three Russian windows (107.7-117.8 s, 120.7-131.6 s, 162.8-177.5 s) came out as the Russian
  hotword list itself — *"ИВЛ, Кишинёв, реанимация, ИВЛ."*, *"Медпарк, Кишинёв, реанимация, ИВЛ, КТ, МРТ, ЭКГ,
  норадреналин, …"* — and the 24-40.6 s window is a similar comma-list. This is the old prompt pathology
  re-entering through `hotwords` (same decoder mechanism, shorter list). The garbage filter does not catch it
  (compression ratio and `avg_logprob` look normal). Open item for the engine: an echo detector (segment mostly
  made of hotword entries and commas -> `low_confidence_asr`), or no hotwords on low-speech windows.
- **Whisper's YouTube hallucination** *"Субтитры создавал DimaTorzok"* appears as a 0.14 s `ru` segment at
  40.6 s, unflagged.
- **Romanian labelled `en`.** 4.8-23.7 s is Romanian clinical speech (*"El a fost pe data de … ajuns la noi cu
  infarct miocardic…"*) but carries `language="en"`, `language_source="rescored"`, confidence 0.68: the English
  hypothesis won the logprob comparison over the Romanian one even though the text is Romanian. The benchmark
  counts these as `translated_english_segments: 2`. The restricted LID prevents *translation* here (the words are
  Romanian), but the label and the hotword hint were wrong for that window.

None of this is hidden by the tests: they prove the mechanism, not the transcript quality (section 6).

## 5. Things that were tried or considered and rejected

- `multilingual=True` (faster-whisper's own per-segment LID): the LID is unrestricted across 99 languages;
  on Romanian speech it picked `en` and the decoder **translated** ("And how do you deal with this? Do you agree
  with the transfer?"). 1.2.1 offers no public way to restrict it and `Segment` has no language field.
- `large-v3` instead of `large-v3-turbo`: does not fit the ~3 GB of free VRAM next to the CUDA context.
- Overlapping windows: the encoder always consumes 30 s, so overlap doubles compute for nothing, and
  de-duplicating a seam that changes language is unreliable.
- Sending the full 318-token vocabulary as hotwords or prompt: it gets truncated at the prompt slot.
- `services/audio/vad.py` for windowing: an energy threshold that one cough resets. Left alone with its test.
- `BatchedInferencePipeline` as-is: ~4x faster on CPU, but no temperature fallback, hardcoded
  `hallucination_silence_threshold` and `condition_on_previous_text`, and unrestricted LID (translation risk).
  Usable only through a subclass that overrides `generate_segment_batched` with the restricted argmax; whether
  it beats the windowed sequential path **on GPU** is unmeasured. `WHISPER_STRATEGY` defaults to `windowed`.

## 6. What is NOT claimed

- **No clean transcript.** The 180 s GPU run above contains hotword echoes, one YouTube-style hallucination and
  a Romanian window labelled `en`; the windowed decode removes the single-language stamping and the hallucinated
  opening, it does not make the ASR output trustworthy without review.
- **No word-error rate.** There is no annotated reference transcript for any hospital recording, so RO/RU/EN
  accuracy on real meeting audio is not quantified. The "before/after" above is a qualitative reading of one
  window plus decoder statistics (`avg_logprob`, integer-second durations, zero gaps, language counts).
- **No language-identification accuracy.** The per-window language counts are what the restricted LID
  produced, not what a human labelled. The text/script check is a consistency gate, not ground truth.
- **No 60-minute GPU run** of the windowed path at the time of writing; the 15-minute end-to-end target remains a
  projection.
- The lexicon corrects a bounded list of near-miss clinical names; it is not a spell-checker and it never
  edits tokens with digits (doses, dates).
- The text LID's `mixed` label only means "both scripts appear in one segment"; word-level `language_spans`
  are heuristic runs of script, not acoustic evidence.

## 7. Tests (offline, no CUDA, no `WhisperModel`)

- `backend/tests/test_asr_text_lid_and_windowing.py` (18 tests, **17 pass**): text LID on RO / RU / EN / mixed /
  `und`, word-level spans (forward/backward fill, equal-language merge), `pack_windows` on synthetic VAD regions
  (blip merged into the previous window, 12 s target packing, 20 s max stretch, 3 s gap rule, 28 s hard-cap split
  with exact coverage, absolute monotonic times, contiguous indexes, `slice()`), `lexicon.correct_segment` (exact
  variants score 1.0, fuzzy proper nouns score = similarity, per-language gating, original recoverable from
  `was`), `HOTWORDS_BY_LANG` measured with the cached snapshot's `tokenizer.json` through
  `faster_whisper.tokenizer.Tokenizer` (ro 78 / ru 73 / en 74 tokens, full vocabulary 318), the deprecated prompt
  stub, all 248 stored `.audit` segments still validating as `language_source="legacy"`, `compute_stats` semantics.
  **The one failure is real**: `test_lexicon_never_touches_tokens_with_digits` shows `"Metpark2024"` becoming
  `"Medpark2024"` because the fuzzy pass in `lexicon.py` substitutes on `WORD_RE` without a digit guard (the exact
  variant pass is word-bounded and correct). Fix belongs in `lexicon.py`: use `(?<!\w)…(?!\w)` around the fuzzy
  word pattern so a token glued to a digit is skipped.
- `backend/tests/test_asr_engine_options.py` (14 tests, **14 pass**): the contract `DECODE_OPTIONS` verbatim,
  `restrict_language_probs` (en 0.9 / ro 0.4 with `["ro","ru"]` -> ro 0.8), `needs_rescoring` (below 0.70, or a
  text disagreement with confidence >= 0.70), `garbage_reason` thresholds, `stitch_segments` (words too); then a
  `FakeModel` (feature_extractor / encode / model.detect_language / hf_tokenizer = the cached snapshot's tokenizer /
  generate_segments) driven through the real `transcribe()` with scripted VAD regions: one encoder pass and one
  LID call per window, the language token forced on the tokenizer, absolute stitching (10.5 + 0.3 -> 10.8), a
  window queued at p1 0.53 and won by the better-logprob hypothesis (`language_source="rescored"`), a 2 s window
  inheriting its neighbour's language (first decode in the inherited language, `inherited_windows=1`), four
  garbage segments kept and flagged `low_confidence_asr` (compression / no letters / logprob / no_speech),
  a mixed RO/RU window with absolute `language_spans`, per-language hotwords and `initial_prompt=None` on every
  `TranscriptionOptions`, the "initial_prompt is ignored" WARNING logged once across three calls, forced language
  (no LID call, no rescoring), a language outside `WHISPER_LANGUAGES` refused with a Romanian message, `en` allowed
  under the default list, empty audio -> no segments, and `last_run_stats` keys/values. `WHISPER_STRATEGY=batched`
  is not covered offline (it drives `BatchedInferencePipeline.transcribe`, which needs a real model).

Run each with the isolated environment described in `README.md` section 5.
