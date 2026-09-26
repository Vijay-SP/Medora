# Voice profiles and speaker attribution

Last revised: 26 September 2026. Describes what is in source and what was measured; nothing here is a plan.
Design and its adversarial corrections: `docs/SPEAKER_IDENTITY_DESIGN.md` (read-only). Model provenance:
`data/models/speaker/campplus/MODEL_CARD.md`.

## What it is

The pipeline labels every transcript segment with an anonymous cluster label (`Speaker 1`, `Speaker 2`, ...)
produced by a CPU-only embedding diarizer (Silero VAD + WeSpeaker CAM++ ONNX, `backend/app/services/diarization/`).
Hospital staff who **enrol themselves** (explicit consent, prompted recordings, `/api/v1/voice-profiles`) get a
voiceprint stored as a `.npy` file under `VOICEPRINTS_DIR`. After a meeting is processed, each cluster is scored
against the enrolled voiceprints; a match is shown to the reviewer as a **question** ("Is this Dr. X?") in the
Speakers tab. Only a reviewer's explicit decision (`POST /api/v1/meetings/{id}/speakers/{cluster}/confirm`)
puts a name on segments, and only on segments that carry enough speech.

There is no code path that names a speaker without a human. `ALLOW_AUTO_CONFIRM_SPEAKERS` exists only to
document that refusal and must stay `false`.

## Safety architecture (what is enforced in source)

**Four attribution states, enforced by Pydantic invariants** (`models/transcript.py`):

| state | meaning | invariant |
|---|---|---|
| `anonymous` | no identity | `speaker_id`, `confirmed_display_name`, `confirmed_by` must be `None`; `printable_name` must be `False` |
| `suggested` | a voiceprint match to ask the reviewer about | requires `suggestion`; same `None` rules as anonymous |
| `confirmed` | reviewer said "yes, this is X" | requires `speaker_id` **and** `confirmed_display_name` (a snapshot of the name) |
| `corrected` | reviewer picked somebody else | same as confirmed |

`segment.speaker` is **always** the anonymous label (`^Speaker \d+$`); the LLM prompt (`Transcript.to_indexed_lines()`)
and `to_full_text()` never see a name. `PUT /transcript/segments/{id}` rejects any other `speaker` value (422),
so free-text renaming cannot launder a name into the document. Rows persisted before this feature migrate on
load: a free-text speaker becomes `legacy_speaker_label`, an old attendee `speaker_id` becomes `legacy_speaker_id`,
and the row is `anonymous` (verified on every transcript in `.audit/real-run`).

**The printable floor.** A name renders on a segment only when `printable_name` is true, which the confirm
handler sets **iff** the segment is confirmed/corrected **and** `speech_seconds >= SPEAKER_MIN_PRINTABLE_SPEECH_S`
(2.0 s of VAD speech, measured by the diarizer). `display_speaker` is the only accessor renderers use: it returns
the confirmed name when printable, else the anonymous label. On the real recording 49% of Whisper segments carry
under 2.0 s of speech and 12% under 1 s ("Да.", "Окей."); those stay `Speaker N` even inside a confirmed cluster.
An action item whose owner is an anonymous speaker label becomes `owner_source="confirmed_speaker"` only when
**every** cited evidence segment is printable; an evidence quote carries the name only when its own segment is.

**Documents fail closed.** `services/documents/generator.py` prints an evidence speaker or an owner name only after
re-checking the stored transcript (`repository.get_transcript`); with no transcript or no printable segment nothing
is named. When at least one segment is printable, the PDF and DOCX carry a legend listing the confirmed names with
`confirmed_by` / `confirmed_at`, plus the sentence "Vorbitorii neidentificați sunt marcați ca «Vorbitor N».
Identificarea vocală este propusă automat și validată de un revizor uman." A suggestion, a score, a band or an
unconfirmed name is never printed anywhere.

**Email never carries a name.** `services/delivery/smtp_service.build_body(meeting, minutes)` renders counts and
attachment names only; both channels run `assert_no_person_names` over subject and body (roster, named owners,
confirmed evidence speakers) and record `FAILED` instead of sending when a name is found. The n8n payload no
longer contains `summary_ro`.

**Revision binding.** A decision is stored with `confirmed_for_revision`. If the meeting is `APPROVED`/`DELIVERED`
or a `DeliveryRecord` exists for the current revision, the decision bumps `current_revision`, resets the review
status to `PENDING_REVIEW`, clears `approved_by/approved_at` and regenerates the PDF/DOCX at the new revision;
otherwise the current revision is redrawn in place. `expected_revision` in the request must equal
`meeting.current_revision` (409 otherwise). Every decision appends a `SpeakerAttributionEvent` to the meeting's
speaker map (`speaker_maps.json`).

**Bulk confirmation is refused (409) when the cluster cannot be trusted**: `mixed_suspect` (a deterministic
2-means split yields two halves each holding >= 30% of the cluster's speech whose centroids agree below 0.55
cosine), `short_suspect` (fewer than 3 distinct VAD regions), or any segment flagged "Speaker change mid-segment"
(>= 30% of its speech in a second cluster). The card offers the **lowest**-scoring turns against the candidate
voiceprint for listening (up to 5), never the longest, and states how many seconds were sampled out of the total.

**No forced assignment.** `services/diarization/matching.py` scores each cluster independently against every
active voiceprint of the active embedding space: no Hungarian solver, no one-to-one constraint, no dummy
"nobody" column. A suggestion requires `score >= SPEAKER_MATCH_MIN_SCORE` (0.50) and `top1 - top2 >=
SPEAKER_MATCH_MIN_MARGIN` (0.08); bands are strong >= 0.80, moderate 0.65-0.80, weak 0.50-0.65. Two clusters
matching one person is reported as a merge suggestion, never resolved by pushing one onto someone else. Confirming
the same person on a second cluster requires the explicit action `correct` (409 with `confirm`).

**No retro-enrollment.** The only route that accepts a voice sample is `POST /voice-profiles/{id}/samples` with a
prompted recording; nothing enrols from meeting audio or from a confirmed cluster (design §5.5). Verified by
`test_voice_profiles_api.py::test_no_endpoint_enrolls_from_meeting_audio`.

**What auto-pilot can never do.** In `AUTO_PILOT` the orchestrator raises `DiarizationError` before extraction if
any segment leaves diarization confirmed/corrected (there is no human), and the diarizer itself only ever writes
`anonymous`/`suggested`. `scripts/voice_e2e_gpu.py` additionally runs the meeting in `SUPERVISED` mode with a
dead SMTP port so no email can be sent.

**Confusability rules in the UI** (`frontend/src/components/voice/`): a suggested name appears only inside the
question "Is this {name}?" in a dashed amber card; confirmed is a filled emerald pill prefixed "Confirmed —";
corrected is blue with "Corrected —"; anonymous is "Speaker N · not identified". Similarity is shown as
"moderate (0.71 cosine — a similarity score, not a probability)", never as a percentage. The three decision
buttons are equally sized and disabled with the verbatim `blocking_reasons` when any exist.

## Enrollment, consent and deletion

- `POST /voice-profiles` creates a person (`not_enrolled`). Samples are refused with 422 until
  `POST /voice-profiles/{id}/consent {"granted": true}`; 503 when the embedder is unavailable.
- Each sample is assessed (`services/diarization/enrollment.assess_sample`): duration, VAD speech seconds, mean
  dBFS, clipped fraction (|x| > 0.99), and a two-voice check (AHC over the sample's windows). `reject` stores
  nothing (speech < 4 s, mean dBFS < -45 or > -6, clipping > 2%, or two voices). `usable` covers 4-10 s of speech
  or -45..-35 dBFS; `good` is above that. The verdict and its plain-English reasons are shown verbatim.
- Accepted samples are stored as 16 kHz WAV under `VOICEPRINTS_DIR/people/<id>/samples/` and the person's single
  active voiceprint is rebuilt from **all** stored samples (`build_voiceprint`: per-sample embedding over the
  sample's VAD speech, mean, L2; `cohesion` = mean pairwise cosine). The person is `enrolled` only when total
  speech >= 20 s and cohesion >= 0.55; otherwise the summary stays `not_enrolled` with `quality_warnings`
  explaining what is missing.
- `needs_reenrollment` means the person's voiceprints were produced by a different embedder space
  (`campplus-LM@<sha256[:12]>/d512/p1`); they are never compared.
- `DELETE /voice-profiles/{id}/samples` wipes samples and voiceprints (re-enrol from scratch).
  `POST .../consent {"granted": false}` sets `withdrawn_at` and purges every biometric file.
  `DELETE /voice-profiles/{id}` removes the row and purges files; names already confirmed on past meetings are
  **kept** as snapshots (`confirmed_display_name`), because the reviewed document must not change retroactively.
- Nothing biometric ever goes into a JSON store: `people.json` holds only descriptors (`artifact_path`, counts,
  cohesion); vectors live in `.npy` files. `test_voice_models_and_storage.py` and `test_voice_profiles_api.py`
  grep every store file for float arrays after an enrollment.
- Per-meeting segment embeddings are cached under `VOICEPRINTS_DIR/meetings/<id>/` (matrix + sidecar with
  sha256, space id, cluster diagnostics) for re-matching and turn sampling; a new upload
  (`POST /audio/upload`) and `delete_meeting` purge them.

## Measured numbers

| What | Value | Where measured |
|---|---|---|
| Embedder | CAM++ ONNX, 512-d, sha256 `1068e4ac…8e93`, Apache-2.0; exact Kaldi fbank + CMN front-end | `scripts/verify_speaker_embedder.py`, MODEL_CARD |
| Clean TTS separation (2 SAPI voices x 8 sentences) | same-speaker cosine min 0.73, cross-speaker max 0.26 | `verify_speaker_embedder.py` |
| Real far-field Medpark audio (703 s) | within-speaker cosine ≈ 0.67-0.70; distance 0.55 merges everyone, distance 0.45 separates two alternating speakers | `verify_speaker_embedder.py --real` |
| Speed (CPU, 4 threads) | 17.6 ms per 1.5 s window; the 703 s recording VAD + embedded in ≈ 11 s | same |
| Short segments on the real recording | 49% of Whisper segments < 2.0 s of speech, 12% < 1 s | design doc §6 |
| Ground-truth SAPI meeting (12 turns, David/Zira alternating) | 12/12 segments in the right cluster; the two dominant clusters hold > 90% of speech; the standalone 1.0 s "Yes, okay." turn was split into its own 1.1 s cluster (over-splitting by design, blocked from bulk confirmation as `short_suspect`) | `backend/tests/test_speaker_diarization_groundtruth.py` |
| Suggestions on the ground-truth meeting after enrolling both voices from separate prompts | cluster centroid vs voiceprint cosine 0.954-0.974, margins far above 0.08; the unenrolled voice gets no suggestion | same |
| Enrollment sample quality | a 10.5 s SAPI clip = 9.6 s speech at -19.5 dBFS -> `usable`; a 1 s clip, 6 s of silence and a 40x clipped clip -> `reject`, nothing stored; three ~15 s prompts -> `enrolled` | `backend/tests/test_voice_profiles_api.py` |

## What is NOT claimed

- **Accuracy on far-field meeting-room audio is unmeasured.** Every accuracy number above comes from clean TTS
  voices, which prove the wiring, not real-world performance. The only real-audio facts are the cosine ranges and
  the clustering distance that separates two alternating speakers on the 703 s recording; no ground-truth
  diarization error rate exists for it.
- No same-gender / similar-voice test, no cross-language (RO/RU) enrollment test, no channel-mismatch test
  (laptop mic vs. room mic) has been run.
- `scripts/voice_e2e_gpu.py` (full API pipeline with Whisper on CUDA + Ollama, SAPI meeting, confirm through the
  API, PDF/DOCX assertions) is written but was **not run** in the build phase because the GPU was reserved;
  its PDF text extractor was exercised on an existing export only.
- The privacy preconditions in design §7 (app-layer encryption of voiceprints, authentication, RBAC, DPIA) are
  **not** implemented; voiceprints are plain `.npy` files on the local disk of an unauthenticated app. Three further
  §7 points diverge from the design and are prototype choices, not oversights to be read as compliance:
  `VOICE_ID_ENABLED` is a plain config flag defaulting to `true` (the design asked for `false`, computed from
  auth + encryption + DPIA and immune to override); enrollment WAVs are **retained** unencrypted with no retention
  period (`retain_audio` is set to `true` when consent is granted, so the voiceprint can be rebuilt; the design
  preferred discarding them); and consent withdrawal / profile deletion purge the biometric files but do **not**
  re-run affected meetings anonymously — names a reviewer already confirmed stay as snapshots on those meetings.
  No DPIA, RoPA or DPO review exists for this prototype.
- The frontend components exist but were verified only by `npm run build`; no browser walkthrough of the
  confirmation flow has been recorded.

## Known gaps (completeness review, 26 September 2026; verified in source, not yet fixed)

- **The People page cannot list or create profiles.** `people.py` registers list/create at `/voice-profiles/`
  (trailing slash) while `frontend/src/api/client.ts` calls `/voice-profiles`; because the compiled SPA is mounted
  at `/`, the slash-less path is swallowed by the static mount instead of being redirected: `GET` -> 404,
  `POST` -> 405 (reproduced with `TestClient`). `test_voice_profiles_api.py` and `scripts/voice_e2e_gpu.py` use
  the slash form, which is why the tests pass. Every other voice/speakers route matches. Fix in `people.py`
  (`@router.get("")` / `@router.post("")`) or in the client.
- `deploy/n8n/medpark_routing_workflow.json` still templates `{{ $json.summary_ro }}`, which the n8n payload no
  longer carries (`subject` / `body_text` only); the workflow emails render an empty summary line until it is
  switched to `$json.body_text`.
- `PUT /transcript/segments/{id}` accepts an anonymous `speaker` relabel on a **confirmed** segment without
  reverting its `cluster_id` / attribution, so a segment moved out of its cluster keeps printing the name.
- The printable floor is enforced by the confirm handler only: `TranscriptSegment` accepts
  `confirmed` + `printable_name=True` with `speech_seconds < 2.0` (no model-level check).
- `backend/tests/test_end_to_end_pipeline.py` overrides `DATA_DIR` but not `VOICEPRINTS_DIR`; its synthetic-noise
  upload yields no VAD speech so nothing was written, but any speech-bearing fixture would cache embeddings into
  the repository's `data/voiceprints`.

## Tests (all offline, isolated storage, dead SMTP/LLM ports, CPU only)

```powershell
$env:PYTHONPATH="backend"; $env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe backend\tests\test_voice_models_and_storage.py          # V3 invariants, migration, people/speaker-map stores, purge cascades, no vectors in JSON
.venv\Scripts\python.exe backend\tests\test_delivery_body_has_no_names.py        # build_body / subject / SMTP + n8n payload (transports mocked)
.venv\Scripts\python.exe backend\tests\test_speaker_confirmation_flow.py         # /speakers read + confirm/correct/reject/unknown, 409s, revision bump, in-place regeneration
.venv\Scripts\python.exe backend\tests\test_speaker_diarization_groundtruth.py   # SAPI two-voice meeting: clustering, enrollment, suggestions, floor, isolation
.venv\Scripts\python.exe backend\tests\test_voice_profiles_api.py                # enrollment flow, rejects, wipe, withdrawal, delete, status, 503 without the model
```

Each script sets `DATA_DIR`, `UPLOADS_DIR`, `EXPORTS_DIR`, `FIXTURES_DIR` and `VOICEPRINTS_DIR` to a fresh temp
directory before importing `app`, keeps `MODELS_DIR` on the repository cache, and skips (not fails) when SAPI or
the ONNX model is unavailable. The GPU-gated script refuses to start unless `nvidia-smi` shows < 1000 MiB in use.
