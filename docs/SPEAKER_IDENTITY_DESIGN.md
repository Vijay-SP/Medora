# Speaker enrollment and identity attribution — design

Status: **design only, nothing implemented.** Researched 25 September 2026 by six parallel probes
(runtime, algorithm, data model, UX, evaluation, privacy) and three adversarial critics
(clinical safety, engineering feasibility, accuracy realism).

Verdict: **the feature is worth building, but not in the form it was first proposed, and not on
the timeline first suggested.** The accuracy critic returned `fundamentally_flawed` on the
accuracy machinery while affirming the safety architecture. Fifteen blocking objections were
raised and are folded into the design below.

Every claim here is marked **[verified]** (someone executed something on this machine),
**[published]** (a cited external benchmark, under its own conditions), or **[estimate]**.

---

## 1. Corrections to earlier advice

Two things I told the user in conversation were wrong and are corrected here.

**ECAPA-TDNN via SpeechBrain, or Resemblyzer, was the wrong recommendation.**
`torch` is not installed in `F:\DEEPTECH\.venv` at all — faster-whisper runs on CTranslate2, which
does not imply torch. `scipy`, `scikit-learn` and `librosa` are also absent. What *is* installed is
`onnxruntime 1.30.0`. **[verified]** So the cheap path is ONNX, not torch: recommending SpeechBrain
would have added roughly 1 GB of dependencies to an air-gapped hospital deployment for no
measurable speed benefit. Resemblyzer is not merely suboptimal, it is blocked — it requires
`webrtcvad`, which publishes no wheels on PyPI, so every Python 3.13 Windows install would need
MSVC build tools to compile an abandoned C extension. **[verified]**

**"Roughly a week of work" was wrong by an order of magnitude.** The engineering critic put it at
**2.5–4 months**, with the long poles being calibration data collection, the security preconditions,
and achieving Kaldi front-end parity. That estimate is sound and is reflected in §9.

---

## 2. What the environment forces

| Fact | Evidence |
|---|---|
| No `torch`, `scipy`, `sklearn`, `librosa`, `speechbrain`, `pyannote` | `pip list` + explicit import probe **[verified]** |
| `onnxruntime 1.30.0` present, providers = `['AzureExecutionProvider','CPUExecutionProvider']` | **[verified]** — no CUDA EP, no DirectML EP |
| `cublas64_12/13`, `cublasLt64_12`, `cudnn64_9`, `cudart64_12` all MISSING; only `nvcuda.dll` loads | ctypes probe **[verified]** |
| Therefore Whisper runs **CPU int8**, not GPU | `_resolve_device` returns `cuda` from device-count, then falls back **[verified]** |
| CPU is strong: 16 threads, 242–269 GFLOPS sustained sgemm | **[verified]** |
| 80-bin log-mel front end in pure numpy: 0.070 s per 60 s of audio | **[verified]** |

**Decision: WeSpeaker ONNX under the already-installed onnxruntime, CPU unconditionally.**
`Wespeaker/wespeaker-voxceleb-campplus-LM` (29.3 MB, Apache-2.0, ungated, 512-dim) as primary;
`wespeaker-voxceleb-resnet34-LM` (26.5 MB, CC-BY-4.0, ungated, 256-dim) as the alternative.
Zero new Python packages, one ~29 MB model file, no HuggingFace token gate, so air-gap staging
needs no account.

**Do not add a GPU code path.** The GPU cannot be used today, and even with CUDA repaired the win
is under two minutes per meeting while adding CUDA DLL failure modes to a hospital deploy.

**Gate before any code is written.** Neither probe actually downloaded the ONNX file — "onnxruntime
runs it" is *unverified*; what was proven is that ORT executes a hand-built MatMul graph. Before a
single config constant is committed: stage the file on a networked build machine, load it under ORT
1.30.0 CPU EP, print input/output names and shapes, and — the load-bearing part — **validate the
numpy Kaldi fbank against WeSpeaker's reference implementation on a fixed WAV to a numeric
tolerance, not by eye.** WeSpeaker declares Kaldi fbank (povey window, `dither=1.0`, `snip_edges`,
utterance CMN); faster-whisper's in-tree extractor is Whisper/Slaney mel. Using the convenient
in-tree one is a trap whose failure is silent: plausible embeddings, degraded clusters, no
exception, discovered weeks later during calibration. Budget 2–4 days for front-end parity alone.

---

## 3. Problems this research found in the product as it stands today

These are independent of the voice feature and several are more urgent than it. They were found
while tracing where a name could reach a signed document.

**3.1 — The LLM can already write any attendee's name into a signed PDF, with no voiceprints
involved.** `prompt_templates.py` passes the full roster (`Participanți cunoscuți: {attendees}`)
into the prompt and instructs the model to emit `"owner"` and `"speaker"` name fields.
`validator.py` validates **only** `evidence[].quote` against the transcript — it never inspects
`summary_ro`, `summary_en`, `decision`, `topic`, `task` or `description`, and `generator.py` prints
all of those verbatim into the PDF and DOCX. So the model can write *"Dr. Ceban a aprobat
întreruperea anticoagulantului"* into the executive summary from the roster alone, and no guard in
the system inspects that string. **[verified by source trace]**

**3.2 — `validator.py:119` guards the wrong branch.** `evidence.speaker = seg.speaker` sits inside
the *secondary* match path, which runs only when the primary check fails. On the primary path — the
common case for a well-behaved model — the LLM's own `speaker` string survives untouched into the
DOCX "Dovadă Audio" column. **[verified]**

**3.3 — Whisper timestamps on the real recording are fabricated.** On the 702.5 s Medpark recording
in `.audit/real-run/`: 199 of 248 segment durations are integer-valued seconds, 102 are *exactly*
2.000 s, 46 exactly 1.000 s, and 98% of consecutive segments have a gap of exactly 0.000 s. The
transcript also shows an identical string repeated verbatim at 38.18–40.18, 40.18–42.34 and
42.34–44.34, and a 27.72 s hallucinated opening segment. **[verified]** That is the signature of
fallback rather than aligned timestamps, and it invalidates any design that reconciles speaker turns
against Whisper boundaries.

**3.4 — ASR forces one language for the whole meeting.** `whisper_engine` sets
`language=detected_primary` from a single `info.language`, so all 248 segments are tagged `ru`,
including Romanian-looking content. **[verified]** This directly contradicts the product's
code-switching claim.

**3.5 — Extraction yields zero decisions and zero action items on the only real recording in the
repo.** **[verified]** The entire attribution apparatus would be feeding a downstream surface that
currently produces nothing.

**3.6 — The current diarizer is at chance, not merely weak.** Re-running `AcousticDiarizer`'s own
feature function over the real recording: all 351 windows fall inside a **5.03-degree cone**, with
**99.93%** of each L2-normalized vector's mass on the crest-factor component. **[verified]** Cosine
k-means on that geometry partitions noise. Any evaluation must include a random-assignment control
or it will mistake chance for signal.

**3.7 — No authentication anywhere.** Zero uses of `Depends(` in `backend/app`. **[verified]**
No crypto library in the venv or `requirements.txt`. `Attendee.email` accepts `''` and untrimmed
mixed case, so any design that links people by email equality will merge distinct humans.

> **Recommendation: fix 3.1 and 3.2 before anything else in this document.** They are live paths to
> a wrong name in a signed hospital document, they exist today, and neither requires the voice
> feature. 3.3–3.5 cap how good attribution can ever be — attribution quality is bounded above by
> transcript quality, and the transcript is currently the larger problem.

---

## 4. Architecture

Two layers, separated so the valuable half can ship without the regulated half.

### Layer A — better anonymous diarization (no biometrics, no Article 9 data)

Replaces `AcousticDiarizer` behind the existing `BaseDiarizationEngine` interface, so
`pipeline_orchestrator` keeps calling `assign_speakers(normalized_path, segments, attendees)`
unchanged. Output stays anonymous `Speaker N`.

- **Front end:** 80-dim Kaldi-style log-mel, 25 ms / 10 ms, pure numpy. Audio is already 16 kHz mono
  PCM from `preprocessor.py`, matching the model's declared `fbank_args`.
- **Fine VAD pass:** re-run Silero separately from ASR's pass at `min_speech_duration_ms=100,
  min_silence_duration_ms=100` (ASR uses 500 ms — too coarse for turn boundaries). ~7.9 s/hour.
- **Embedding windows:** 1.5 s window, 0.75 s hop, over VAD speech only.
- **Change points:** union of (a) VAD gaps ≥ 250 ms and (b) embedding divergence peaks, accepted
  when `d > mean + 1.5·std` over a sliding 60 s window **and** `d > 0.25` absolute.
- **Turns:** one embedding per turn over up to 8 s of its pooled speech — a single forward pass over
  more audio beats averaging short-window embeddings.
- **Clustering:** agglomerative, cosine, average linkage, **stopped by distance threshold**, with
  attendee count as a *soft prior only*. Deterministic, no RNG. Never `np.random.seed` — use a
  local `default_rng` if randomness is ever needed.
- **Bias deliberately toward over-splitting.** Over-clustering costs a reviewer clicks;
  under-clustering puts another doctor's decision under a confirmed name.

**Reconciliation onto Whisper segments — do not build on Whisper boundaries (§3.3).** Diarize on the
VAD/frame timeline independently and treat Whisper times as approximate. Where a segment straddles a
change: assign majority overlap, set `is_flagged=True` with a reason naming the other speaker. Do
**not** fabricate a split. Splitting must happen in stage 3 before stage 4, or evidence spans are
orphaned; never re-split a meeting that already has minutes.

Layer A alone is a real improvement over a diarizer that is at chance, creates no biometric data,
and needs none of the security gates in §7.

### Layer B — enrollment and named attribution (Article 9 data; gated)

Voiceprint per **person**, matched against clusters, surfaced as a *suggestion*, confirmed by a
human, and only then allowed near a document.

---

## 5. What the critics killed

Six proposals were rejected outright. Each was defensible-looking and wrong.

**5.1 — Confirmed names must never enter the LLM prompt.** A proposal to have
`Transcript.to_full_text()` emit confirmed names was the single most dangerous line in the combined
design. Confirmation is *cluster-level*: one click asserts identity over every turn in a cluster, so
one wrong confirmation on a mixed cluster produces fluent Romanian prose attributing another
person's decisions to the confirmed name — in free text no validator inspects. It is also
irreversible by re-rendering: a later speaker correction fixes the `owner` field and leaves the
executive summary still saying Dr. A approved it.
→ **`to_full_text()` emits `Speaker N` permanently, in every state, for every consumer.** Names are
mapped in only at render time, only into structured fields, only from the confirmed map.

**5.2 — The "cluster purity proxy" is mathematically vacuous.** Average-linkage AHC stopped at
threshold *t* terminates precisely when no two clusters are within *t*; every member is then within
*t* of its own centroid **by construction**. Verified numerically: with two acoustically similar
same-gender speakers fully merged (true purity 0.750), the proxy reported **1.000 at every threshold
from 0.55 to 0.85**. **[verified]** The worst failure mode in the feature — one name applied to
another doctor's utterances — had as its only automatic detector a tautology.
→ Delete it. Replace with: 2-means split of each cluster compared against its own within-cluster
distribution; a minimum count of distinct VAD-separated regions before bulk confirmation; and
re-scoring every turn against the confirmed voiceprint to surface the **lowest**-scoring turns.

**5.3 — A single "nobody" dummy column under one-to-one assignment is P0.5 again.** One dummy column
lets at most *one* cluster be labelled unknown. Three unenrolled visitors → two are forced onto real
enrolled people. That is ordinal forced assignment wearing a Hungarian solver and a confidence score.
→ Drop the one-to-one constraint. Score each cluster independently with explicit open-set rejection;
use an assignment solver only as a post-hoc consistency *warning*.

**5.4 — One-to-one also breaks on the design's own premise.** The same probe argued each person needs
per-language sub-centroids because phonetic content leaks into the embedding — which means one
person's Romanian and Russian turns will often form *separate* clusters. One-to-one then forces one
of them onto a different attendee, converting a benign failure (one person appears as two anonymous
speakers) into the catastrophic one.
→ Allow many-to-one. Two clusters matching the same person is a **merge suggestion**, never a
conflict resolved by reassigning one to somebody else.

**5.5 — Retro-enrollment ("mint a voiceprint from a confirmed cluster") must not be the main path.**
It turns every confirmation error into a permanent, self-reinforcing, invisible enrollment error: a
contaminated template produces confident matches for *both* voices in every future meeting and looks
exactly like a good template from outside. The proposed human check made it worse by offering the
reviewer the three **longest** turns — the ones most likely to have been clustered correctly.
→ Explicit enrollment under a controlled prompt is the only routine path. Matched-condition
enrollment (same laptop mic, same room, same distance) recovers most of the domain-match benefit
without laundering confirmation errors into templates.

**5.6 — The spoken-name channel must never populate a rendered field.** The existing heuristics do no
referent resolution: `speaker_engine` sets `suggested_identity` when *any* attendee name-part longer
than 3 characters appears anywhere in an utterance, and `llm_engine` sets `detected_owner` on a bare
substring test. Neither distinguishes speaker from addressee from third party **from patient**.
*"Pacientul Popov necesită anticoagulant, trebuie să verificăm dozajul"* matches an action keyword
and contains the attendee name-part "Popov" → `owner = "Dr. Popov"`, for a task about a patient who
shares his surname. Romanian and Russian surnames collide heavily between staff and patients in one
hospital. Two probes had treated this as the *safe* non-acoustic fallback; for this domain that is
exactly backwards, and none of the six probes considered patient names.
→ The spoken-name channel becomes a **reviewer prompt only**, absent from every document. Under
`meeting_type == medical`, suppress it entirely and route to a review flag.

---

## 6. The safety architecture that survived

These were attacked and held.

- **Four-state attribution, structurally enforced:** `anonymous` → `suggested` → `confirmed` →
  `corrected`. A Pydantic invariant makes an unconfirmed name unrepresentable in a render context.
- **Confirmed-only rendering.** One `build_render_context` accessor is the sole path from stored
  state to any rendered surface. Documents and email read only from it.
- **Downgrade-at-dispatch.** At the moment of export or send, any attribution not confirmed *for
  that exact revision* degrades to the anonymous label. Confirmation is bound to a revision, so a
  later transcript edit cannot silently carry an old confirmation forward.
- **Output-side name filter (added by the clinical critic).** As the last step before any render or
  export, scan every free-text field (`summary_ro`, `summary_en`, `agenda_topics[]`, `decision`,
  `topic`, `task`, `deadline_phrase`, `description`) for any known person name. Reject unless that
  exact token appears inside a grounded evidence quote for that item **and** the cited segment is
  confirmed to that person. Fail closed — neutralize to the cluster label or drop to
  `risks_and_questions`, as the validator already does for ungrounded evidence.
- **Remove `{attendees}` from the extraction prompt entirely**, and delete `speaker` from the
  requested JSON schema. The model does not need the roster to extract decisions; handing it the
  roster is what makes name fabrication fluent and plausible.

**The segment, not the cluster, carries a printable name.** This is the critics' most important
structural change. Cluster confirmation sets an *eligibility flag*; a name renders on a segment only
if that segment independently carries ≥ a minimum speech duration **and** its own embedding agrees
with the confirmed voiceprint. Segments below the floor render anonymous even inside a confirmed
cluster. Any decision or action item whose evidence span falls below the floor is unattributed
regardless of cluster state.

Why this matters concretely: on the real recording, **49% of Whisper segments contain under 2.0 s of
actual speech and 12% under 1 s** **[verified]**, while the three clusters carry 62.9 s, 248.2 s and
378.0 s — so a 10 s cluster-level duration gate passes trivially and then propagates the name onto
every sub-second segment. That transcript contains *"Да."* seven times and *"Окей."* five times. A
bare *"Да."* approving a change of anticoagulation, attributed to a named doctor because a 1.0 s
segment landed in a confirmed cluster, is precisely the harm this feature must not create.

**Bulk confirmation hard-refuses (409, not a warning)** on any cluster below the purity floor, above
a speech cap without proportional sampling, or containing an overlapping/straddling segment. The
card states sampling honestly — *"you listened to 24 s of 4 m 12 s"* — rather than implying coverage.

---

## 7. Privacy preconditions

Moldova's GDPR-transposing **Law No. 195/2024 entered into force 23 August 2026** — before today —
so this ships under a regime already mandating RoPA, DPIA for high-risk processing, and a DPO.
Voiceprints used to identify a person are special-category biometric data. *(Flagging as a
requirement to check with counsel, not as legal advice.)*

- **`VOICE_ID_ENABLED = False`** master gate. When false, no enrollment route is registered and
  `voiceprints.json` is never created. Computed at startup as False unless authentication is wired
  **and** the encryption provider initialises **and** the DPIA hash matches — and it must refuse a
  config override.
- **Store embeddings, not enrollment audio.** Discard raw enrollment once the embedding is computed.
  Retaining it enables re-enrollment on model upgrade but it is the most sensitive artifact in the
  system; if retained, encrypt with a stated retention period.
- **Nobody may enroll anyone but themselves.** This alone kills retro-enrollment as a routine path.
- **Working withdrawal path** that deletes the embedding and re-runs affected meetings anonymously.
- **Model-version binding.** Embeddings from model A are meaningless against model B; each
  voiceprint records its producing model and version.

**The unresolved blocker.** The privacy probe requires app-layer encryption before the first
voiceprint is written; no crypto library exists in the venv or `requirements.txt`, and the probe was
barred from choosing a dependency. **[verified]** So the design currently forbids itself from
shipping. This needs a decision from you (§10).

The security gates also exceed the feature itself in size: authentication, RBAC, CORS lockdown,
tested cascade delete, append-only audit log, backup-deletion policy. The realistic failure mode is
that these slip and a biometric store lands on an unauthenticated app.

---

## 8. Accuracy: what to actually expect

**Teams is not a fair comparison, and the gap is not closeable by model choice.** Teams reads speaker
identity from *stream ownership and authenticated login*, never from voice, so its speaker-attribution
error is structurally ~0. That is an information advantage, not a model advantage. **If attribution
accuracy is clinically load-bearing, buy microphones before buying models.**

**Published anchors** (pyannote 3.1, no collar, overlap scored): AMI headset mix 18.8% DER; AMI
array1 far-field single channel, 4 speakers, English, instrumented room **22.4%**; AliMeeting ch1
24.4%; CHiME-6 far-field best >45% with oracle SAD. DIHARD III meeting domain median 35–45%.
VoxCeleb1-O EER for WeSpeaker ResNet34-LM: 0.723% — near-field, clean, full-length, English.

**Estimates for Medora** (marked as estimates, not measurements):

| Condition | Expected |
|---|---|
| 2–4 speakers, laptop mic 1–3 m, RO/RU/EN | DER ~20–35% |
| 6–8 speakers, round table | DER ~35–55% |
| Per-segment named identity on 2–5 s utterances | 10–25% per-comparison error |
| Current code | at chance **[verified]** |

My earlier conversational estimate of "85–95% for 2–4 speakers" was too optimistic — it was
near-field intuition applied to a far-field problem.

**The number a hospital administrator understands:** at a per-comparison FAR of 1% with 8 enrolled
people and 6 clusters, **38% of generated documents would contain at least one wrong name**; at 0.5%
FAR, **21%**. That arithmetic, not DER, is what governs this feature.

**Why DER is the wrong headline:** DER computes an optimal mapping from cluster labels onto reference
speakers *before* scoring, so a system that consistently swaps two doctors scores near-zero speaker
confusion while putting the wrong name on every decision. DER measures whether you found the turn
boundaries; **CWAR** — confidently-wrong attribution rate, computed over decision and
action-owner items specifically — measures the clinical harm.

**Overlap floor:** ~16–20% of meeting speech is overlapped in AMI/AliMeeting. One-speaker-per-segment
assignment has a missed-speech floor equal to the overlap ratio, and Medora's floor is *worse*
because its assignment unit is an ASR segment that is not speaker-homogeneous. Overlap regions should
be candidates for forced *unknown*, not best-effort naming.

---

## 9. Evaluation and phasing

**Phase A — verification diagnostic (half a day, ~10 staff).** 60–90 s read Romanian passage + 30 s
spontaneous per person, **on the same laptop mic at typical meeting distance** (HI-MIA evidence:
matched far-field enrollment beat close-talk, 3.29% vs 4.02% EER — so enroll in the room, not on a
headset). All-pairs trials give a labelled DET curve with zero annotation effort.

**Phase B — 6 scripted mock meetings × ~20 min (~2 h). The core set.** The cost lever: record each
participant on a **cheap reference channel** (their own phone in a breast pocket) alongside the room
mic, sync with a hand clap. Reference RTTM is then generated near-automatically by energy VAD per
channel — turning 30–40 person-hours of manual labelling into a scripting job. Gate a frame to
speaker *k* only when *k*'s channel exceeds all others by a margin; manually spot-correct ~10% and
**report the reference's own error rate**.

Sessions: (1) 3 speakers, best case. (2) 4 speakers, natural interruption. (3) 7–8 speakers, stress.
(4) **adversarial-similar** — two same-gender, similar-age speakers seated adjacent. (5)
**adversarial-far** — one participant at 4–5 m with HVAC running. (6) **adversarial-open-set** — an
unenrolled visitor who speaks substantially, plus an enrolled attendee who says two sentences.

*The trick that makes tier-3 metrics nearly free:* script ~10 explicit decision/action moments per
session with a **known true owner**, ≥3 uttered by the quiet/far/similar-voice participant. You then
measure decision-attribution accuracy directly on ~60 items with zero annotation.

**Statistical honesty.** By the rule of three, zero errors in *n* trials bounds the rate at ~3/*n*
(95%). Sixty error-free decision events bound CWAR at **~5%, not 0%**. Certifying ≤1% needs ~300
error-free events ≈ **30 mock meetings**. Decide the stringency you want *before* recording — the
gate dictates the data budget.

**Calibration.** Do not operate at EER. Choose the operating point on the FAR axis (start at 0.5%)
and report whatever coverage falls out. Use a NIST-style cost function with **C_fa 100–1000× C_fr**.
Require both `top1 > τ` **and** `(top1 − top2) > margin` — the specific guard against the
similar-voice case where confident errors concentrate. Apply AS-norm before thresholding, since raw
cosine shifts with room and channel. Fit on one set of speakers and room, **evaluate on held-out
speakers and a held-out room**, or you are fitting noise.

*(A rejected shortcut: calibrating τ from enrollment halves gives 8 genuine / 28 impostor trials with
8 attendees — a FAR resolution floor of 3.6% and a 95% upper bound of 10.7%. You cannot measure a 1%
FAR that way, and both sides are clean close speech, so it is calibrated in the wrong domain.
Smoke test only.)*

**Phase C — shadow mode.** Run live with attribution **hidden from the document**, log suggestions,
let the reviewer (who was in the room) correct speaker labels. Every correction is a free
real-condition label. Beware: override rate is biased downward by automation bias — a plausible
pre-filled name gets confirmed far more readily than a blank field gets filled.

### Gates

**Gate A — may show suggestions to a reviewer.** CWAR ≤ 5% *with 95% upper bound also ≤ 5%*;
out-of-gallery false-name rate ≤ 2%; macro-averaged per-person recall ≥ 40%; coverage ≥ 50%; beats
the random-assignment control by a wide reported margin.

**Gate B — a name may reach a signed document.** The recommendation is the uncomfortable one:
**voice alone is never sufficient, at any measured accuracy.** A name reaches a signed minute only
when a human explicitly confirmed the cluster→person mapping for that revision. The reviewer's
signature carries the liability; the machine must not be the last link in the chain.

### Honest scope

**2.5–4 months**, not a week. Long poles: calibration data collection (Phase B is ~2 h of recording
but weeks of scheduling 8 clinicians), the security preconditions in §7, and Kaldi front-end parity.

**Smallest genuinely shippable version:** Layer A only — better anonymous diarization, no
enrollment, no biometrics, no Article 9 data, none of the §7 gates. It replaces an engine that is
verifiably at chance and delivers most of the transcript-readability benefit. Ship that first.

---

## 10. Decisions needed from you

1. **Crypto dependency.** Add `cryptography` to `requirements.txt`, or accept Windows DPAPI via
   ctypes (`CryptProtectData`) as the zero-dependency option? Without one, Layer B cannot start.
2. **Data budget.** ~2 h of mock meetings bounds CWAR at ~5%. Certifying ≤1% needs ~30 sessions.
   Which gate do you want, knowing the recording cost?
3. **Ship Layer A first?** It needs no consent, no encryption, no auth, and fixes a diarizer that is
   at chance.
4. **Fix §3.1/§3.2 now?** The LLM can write any attendee's name into a signed PDF today. That is a
   present-tense version of exactly the harm this feature is designed to avoid.
5. **Microphone.** A cheap USB array at the table centre would do more for attribution accuracy than
   any model choice on this list.

## 11. What must not be claimed until measured

Not "speaker identification", not "knows who said what", not "like Teams' intelligent recap" — Teams
reads login, not voice. Not any VoxCeleb or pyannote figure as if it were Medora's. Not any accuracy
figure at present: there is no measurement, no annotated data, and the current engine is verifiably
at chance. Not a DER without its collar and overlap convention. Not "works for Romanian/Russian/
English" — WeSpeaker is trained largely on English-dominant VoxCeleb and cross-lingual transfer to
Moldovan clinical speech is untested. Not "offline, therefore privacy-safe" — local processing does
not exempt biometric processing from consent, and embeddings are pseudonymous, not anonymous.
