# Inline speaker attribution in the minutes

Last revised: 26 September 2026 (contracts N1-N7). Describes what is in source and what the offline tests
prove; nothing here is a plan. Companion documents: `docs/VOICE_PROFILES.md` (how a cluster gets a name),
`docs/LLM_EXTRACTION.md` (the map/reduce engine), `docs/SPEAKER_IDENTITY_DESIGN.md` (read-only design).

## What changed

Until this pass the extracted prose was written impersonally ("Se pregătește documentul actualizat al
protocolului") and a person's name could appear only in two structured places: the evidence speaker of a
quote and the owner of an action item, both rewritten by the confirm endpoint. The narrative never said who
proposed, who approved, who will do what.

Now the LLM writes the decision / task / description texts and the summaries in facilitator style, attributing
each act to the **anonymous speaker label exactly as it appears in the indexed transcript**:

```
S3 a propus modificarea dozei de vancomicină; S1 a aprobat.
S2 va trimite documentul comitetului de calitate până vineri.
S3 a semnalat riscul de stoc insuficient de hemostatice.
```

That label text is what the repository stores. A **render layer** (`backend/app/services/extraction/attribution_render.py`)
substitutes the tokens at read time, per reader and per locale, with either the name a reviewer put on the
cluster or a localized anonymous form. Nothing about *how* a name becomes allowed changed: it is still a human
decision on `POST /api/v1/meetings/{id}/speakers/{cluster}/confirm`. What changed is *where* the name appears
once it is allowed: inline in the prose, in every language, in the API, the PDF and the DOCX.

## What the reviewer sees

**Before any confirmation** (every cluster anonymous), `GET /api/v1/meetings/{id}/minutes` and the documents show:

| field | rendered |
|---|---|
| `summary_ro`, `decision`, `task`, `description`, `agenda_topics` | `Vorbitorul 2 a propus actualizarea listei; Vorbitorul 1 a aprobat.` |
| `*_en` | `Speaker 2 proposed updating the list; Speaker 1 approved.` |
| `*_ru` | `Участник 2 предложил обновить список; Участник 1 одобрил.` |
| `EvidenceQuote.speaker`, `ActionItem.owner` (speaker-derived) | `Speaker 2` (the PDF/DOCX owner column prints it as `Vorbitor 2`, unchanged) |
| transcript | `Speaker 2` on every segment, as before |

**After the reviewer confirms a voiceprint match or assigns a label** to cluster 2, the same reads show the name
inline: `Consultant extern a propus actualizarea listei; Vorbitorul 1 a aprobat.` / `Consultant extern proposed
updating the list; Speaker 1 approved.` / `Консультант ... Участник 1 одобрил.` (the Russian text keeps the name
as written; names are never translated). The other clusters stay anonymous. Rejecting the cluster (`action:
"reject"` / `"unknown"`) returns every field to the anonymous form on the next read, without re-extraction.

`GET /minutes?names=labels` returns the stored token form (`S2 a propus ...`) for tools that want to see exactly
what the model wrote; `names=resolved` is the default and what the UI uses. `POST /translate` returns resolved
text the same way. `PUT /minutes` stores the body verbatim: it is reviewer-authored text, so a name the reviewer
typed (or a resolved name the editor sent back) is the reviewer's own statement.

## A label assignment: what it is and what it is not

`POST /api/v1/meetings/{id}/speakers/{cluster}/confirm` with `action: "label"` and either `display_label`
(a typed name, 2-60 characters after trimming, never `Speaker N` / `SN`) or `attendee_id` (an entry of
`meeting.attendees`, including the client-side guests the participant picker creates with ids `guest_...`; the
attendee's name becomes the label). The listing endpoint offers the candidates as `SpeakerCluster.label_options`
(`{id, name, role, is_guest}`) and reports the current one as `current_label`.

- **A human decision.** Nothing else calls this route. The reviewer's name and role are recorded on every
  segment (`confirmed_by`) and in the speaker map as an audit event with `person_id = None` and the label as
  `person_name_snapshot`.
- **No voiceprint, no Person.** The segments are written as `attribution_state = "corrected"`,
  `speaker_id = None`, `attribution_basis = "reviewer_label"`, `confirmed_display_name = <label>`. No `.npy`
  file, no `people.json` entry, no enrollment happens. The Pydantic invariant was relaxed exactly this far:
  `corrected` requires `confirmed_display_name` and (`speaker_id` **or** `attribution_basis = "reviewer_label"`);
  `confirmed` still requires `speaker_id`; a reviewer label with a `speaker_id`, or a reviewer label on a
  `confirmed` segment, is rejected.
- **Revision-bound.** Like a confirmation, a label is refused with 409 when `expected_revision` is stale, and
  on approved or delivered minutes it bumps the revision and clears the sign-off (`confirmed_for_revision`
  follows). Blocked clusters (mixed voices, too few speech regions, straddling segments) refuse a label in
  bulk with the same 409 as a confirmation.
- **The printable floor applies.** `printable_name` is set per segment from `speech_seconds >=
  SPEAKER_MIN_PRINTABLE_SPEECH_S` (2.0 s). A 1.2 s "Verificăm dozajul." in a labelled cluster still renders
  `Speaker 2` in the transcript, keeps `Speaker 2` on its stored evidence quote, and an action whose only
  evidence is that turn keeps `owner = "Speaker 2"` in the store.
- **Cluster-level prose, per-segment structure.** The label map is built per cluster, so the prose (`S2 va
  verifica dozajul.`) renders the label wherever it says `S2`: the narrative attributes the whole cluster.
  Structured fields are per segment (invariant 4): a resolved `EvidenceQuote.speaker` is the cited segment's
  `display_speaker` (the name only when that turn is printable, else `Speaker N`), and a speaker-derived
  `owner` resolves to the name only when every evidence turn is printable and in that cluster, the same rule
  `speakers._apply_attribution_to_minutes` applies when the decision is written. The action above therefore
  keeps `Speaker 2` (PDF/DOCX `Vorbitor 2`) in its owner column and on its quote in `GET /minutes`, the PDF
  and the DOCX alike. `render_minutes` applies this rule (repair round 1); `test_inline_attribution.py`
  (10/10) and `test_speaker_label_action.py` (7/7) assert it against current source (re-run 26 Sep).
- **Reversible.** `reject` / `unknown` clear the label, the basis returns to `voiceprint` (the default),
  evidence and owners fall back to the anonymous label, the documents are regenerated.

## What auto-pilot can never do

- The LLM never sees a person's name. `Transcript.to_indexed_lines()` renders `S1: text`; the prompts contain
  no roster, date or title; the synthesis call sees the merged items with their labels, never the transcript.
  The map prompt states that the label is the **only** allowed way to name a person and that "doctorul X" is
  forbidden in the attributed fields (`owner_mention` still carries the verbatim spoken mention separately for
  `resolve_owner`).
- Every map item carries `speakers` (<= 3 labels). After the merge, `validator.ground_speaker_labels`
  replaces any `S<n>` token in the text or the list that no **cited** segment spoke with the cited label
  that has the most speech; the summaries and agenda are grounded against the transcript's label set the
  same way. A repair sets `needs_name_review` and appends ONE medium-severity item
  `NOTĂ AUDIT: atribuirea vorbitorilor a fost corectată automat pentru N element(e) ...`.
- A suggestion (voiceprint match nobody confirmed) never renders as a name; a confirmed cluster whose every
  turn is below the floor renders anonymously.
- `speaker_label_style` is `"impersonal"` by default and only new LLM extractions are stamped `"labels"`.
  The heuristic (degraded) extractor is unchanged and impersonal. `render_minutes` leaves the prose of
  `"impersonal"` minutes byte-identical (only evidence speakers and speaker-derived owners follow the
  per-segment rule), and clinical `S<n>` notation is never treated as a label (see "Clinical notation").
- Label-styled prose is also audited for names: `validator.audit_person_names` flags any person name outside
  the `S<n>` tokens (for example a synthesis that writes "Doctorul Popescu"), adds a `NOTĂ AUDIT ... numește
  persoane` item and sets `needs_name_review`.

### Clinical notation

`S1`..`S4` are also medical notation (sacral level `L5-S1`, nerve root `radiculopatie S1`, heart sounds
`zgomotele cardiace S1 și S2`, `galop S3`, stage `stadiul S2`). `LABEL_RE` only matches a token that stands
alone (not inside a word, a range `S1-S2`, a code `C7/S1` or a decimal `S1.5`), and `is_speaker_label` rejects a
token governed by a clinical cue word (RO/EN/RU list in `attribution_render.py`). The same predicate is used by
the renderer, by `validator.ground_labels_in_text` and by the translation guard, so
`ground_speaker_labels("S2 a propus RMN pentru hernia L5-S1.", ["S2"], <S2 turn>)` returns the text unchanged
with `repaired=False` (checked 26 Sep), and `render_text` leaves the clinical tokens exactly as written.
- The e-mail body and subject still carry counts and attachment names only (`assert_no_person_names`);
  names reach a recipient only inside the attached PDF/DOCX, which print them only where the transcript
  allows (`test_delivery_body_has_no_names.py` still passes).
- Translation (`translation_service`) always runs on the **stored** token text, never on rendered names. The
  prompt pins the labels ("rămân EXACT neschimbate"); if a translated field drops, adds or renumbers a label
  the Romanian text is kept for that field and a WARNING is logged.

## Why storage keeps labels (re-render safety)

Storing `S2 a propus ...` rather than the resolved sentence means:

1. Confirming, correcting, labelling or rejecting a cluster never rewrites prose; the next read renders the
   new state. A wrong confirmation is undone by a reject, not by a re-extraction or a manual edit.
2. The RU/EN translations stay name-free and are rendered per locale from the same map, so a name never
   gets machine-translated and the three languages cannot disagree about who did what.
3. A document regenerated for a later revision, or a stored minutes JSON opened by another tool, cannot leak
   a name that a later decision revoked.
4. The name-safety invariants stay checkable in one place: the stored transcript. Whether a token may render
   as a name is decided from `attribution_state`, `printable_name` and `confirmed_display_name` at read time.

`PUT /minutes` accepts either GET form. `App.tsx` `handleSaveSummary` sends the whole RESOLVED object back, so
`review._restore_stored_tokens` keeps the stored token text for every field whose submitted value equals what the
reader was shown, and converts the names and `Vorbitorul N` / `Speaker N` / `Участник N` forms of an edited field
back to tokens. Checked 26 Sep: an edited `summary_ro` "Dr. Ana Popescu a deschis ședința; Vorbitorul 2 a notat."
is stored as "S1 a deschis ședința; S2 a notat." and the untouched decision keeps "S1 a aprobat; S2 a propus.".
A name the reviewer types that is not a rendered cluster name is stored as typed (reviewer-authored).

## Where it lives

| concern | file |
|---|---|
| prompts (facilitator style, label-only naming, synthesis narrative) | `backend/app/services/extraction/prompt_templates.py` |
| `speakers` in `MAP_SCHEMA` / `MapDecision` / `MapAction` / `MapRisk` | `backend/app/services/extraction/schemas.py` |
| `ground_speaker_labels`, `ground_labels_in_text` | `backend/app/services/extraction/validator.py` |
| grounding pass, audit note, `speaker_label_style="labels"`, labelled synthesis block | `backend/app/services/extraction/llm_engine.py` |
| `LABEL_RE`, `SPEAKER_RE`, `ANON`, `build_label_map`, `render_text`, `render_minutes` | `backend/app/services/extraction/attribution_render.py` |
| `MinutesOfMeeting.speaker_label_style` | `backend/app/models/extraction.py` |
| `attribution_basis`, relaxed `corrected` invariant | `backend/app/models/transcript.py` |
| `GET /minutes?names=`, resolved `/translate`, token-restoring `PUT` (`_restore_stored_tokens`) | `backend/app/api/v1/endpoints/review.py` |
| action `label`, `label_options`, `current_label`, `validate_label` | `backend/app/api/v1/endpoints/speakers.py` |
| rendered copy for PDF/DOCX (legend and footer unchanged) | `backend/app/services/documents/generator.py` |
| label preservation in translation | `backend/app/services/translation/translation_service.py` |
| "Someone else" menu: enrolled voices / attendees & guests / custom label; "Assigned —" state | `frontend/src/components/voice/SpeakerConfirmationPanel.tsx`, `api/client.ts`, `types/index.ts` |

## Verified offline (no GPU, no Ollama, no mail)

```powershell
$env:PYTHONPATH="backend"; $env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe backend\tests\test_inline_attribution.py      # 10/10: N1 prompts/schema, N2 grounding + audit note, N3 map/render + per-segment floor, FakeClient run
.venv\Scripts\python.exe backend\tests\test_speaker_label_action.py    # 7/7: N4 label action (typed / attendee / guest), sub-floor owner/quote stay anonymous, refusals, reject, revision, ?names=, translate, PUT, PDF/DOCX, invariants
.venv\Scripts\python.exe backend\tests\test_translation_service.py     # 8/8: incl. N5 token preservation with a fake client and the Romanian fallback
```

Each script isolates `DATA_DIR` / `UPLOADS_DIR` / `EXPORTS_DIR` / `FIXTURES_DIR` / `VOICEPRINTS_DIR` under
`%TEMP%`, pins SMTP to a dead port with simulated delivery off and the LLM to a dead port; the extraction run
injects a `FakeClient`. The FakeClient run asserts that every item's label tokens and `speakers` are a subset of
the labels of its cited lines and that the summary names at least two distinct labels.

## Not verified / known gaps

- **No live LLM run yet.** Whether Qwen3-4B actually writes "S3 a propus ...; S1 a aprobat" with correct labels
  on real audio, and how often `ground_speaker_labels` has to repair it, must be measured in the VERIFY phase
  (`test_llm_extraction_live.py`, then a real recording). The offline tests prove the plumbing, not the model.
- `SpeakerAttributionEvent.action` (`backend/app/models/person.py`) still lists only
  `confirm | correct | reject | unknown`; a label decision is therefore audited as `correct` with
  `person_id = None` and the label as `person_name_snapshot`. Adding `"label"` to that `Literal` makes the
  endpoint record it as `"label"` (the endpoint already checks the model's allowed values).
- The PDF assertions in `test_speaker_label_action.py` rely on the best-effort fpdf2 text extractor from
  `scripts/voice_e2e_gpu.py`; when it recovers fewer than 200 characters the test falls back to the DOCX.
- The frontend menu was only type-checked (`npm run build`; the critic re-ran `tsc --noEmit`, exit 0). No
  browser walkthrough was recorded.
- **The clinical guard is a cue-word list, not a parser.** An `S<n>` in clinical phrasing without a listed cue
  (and not in a range, code or decimal) is still read as a speaker label. The guard is conservative in the
  other direction too: a label right after a clinical list ("radiculopatie S1, S1 a cerut") stays raw.
- **Unknown tokens print raw.** `render_text` substitutes only clusters the transcript has; `S10` in a
  meeting without a tenth cluster (possible only through reviewer-typed `PUT` text, since extraction grounds
  every token against the transcript) is shown as written, not as `Vorbitorul 10`. It can never print a name.
- `backend/tests/test_llm_extraction_pipeline.py` `test_extract_minutes_with_fake_client` (outside this
  feature's test set) still uses an impersonal canned synthesis naming "Doctorul Popescu"; with the engine now
  stamping `"labels"`, `audit_person_names` flags it, so that test fails (14/15) until its fixture is rewritten
  in labelled prose. The engine behaviour is the intended one. Verified replacement for `summary_ro` (passes
  15/15 unchanged assertions in an out-of-tree harness):
  "S2 a propus noul protocol de antibioterapie pentru ATI, în vigoare de luni, iar S1 l-a aprobat. S1 actualizează ghidul clinic până luni, iar tabelele de dozare vor fi trimise până vineri. S2 a semnalat riscul epuizării stocului de meropenem.".
- Documents print the resolved prose; the owner column still uses the pre-existing `Vorbitor N` form while the
  prose uses `Vorbitorul N`. Both are anonymous; the wording is not unified.
