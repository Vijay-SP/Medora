# Extraction evaluation data

`tools/eval/gold` holds **text-only** gold annotations for scoring the LLM extraction stage
(`tools/eval/run_extraction_eval.py`). It must never contain audio, recordings, exports or
anything derived from a real hospital meeting: the gold files are checked-in test fixtures,
not patient data. They live next to the scorer rather than under `data/` because `data/` is
git-ignored at the repository root (`.gitignore` line `data/`), and git cannot re-include a
file whose parent directory is excluded; `backend/tests/test_llm_extraction_pipeline.py` and
`test_llm_extraction_live.py` load `gold/synthetic_trackA.json` from here.

## Two tracks

| Track | Input | What it measures | Gold files |
|---|---|---|---|
| **A - corrected transcript** | A transcript whose text is known to be right (hand-written or reviewer-corrected). | Extraction quality in isolation: decision precision/recall, proposal-vs-decision discipline, verbatim owner mention and deadline phrase capture, evidence validity. | `gold/synthetic_trackA.json` (11 lines, RO/RU/EN) |
| **B - raw ASR** | The unedited Whisper output of a real recording (e.g. `.audit/real-run/store/transcripts.json`, 248 segments, mostly repetition loops and nonsense). | Robustness only: no crash, no fabrication, timing. The model correctly extracts **nothing** from that transcript; zero items there is the expected result, not a bug. No gold file exists for track B because there is nothing to score. | none |

## Gold file format

One JSON object per fragment:

- `meeting` - title/type/date/attendees used to build the `Meeting` object in tests. The
  roster is only used by the **scorer** (owner accuracy, fabrication) and by `resolve_owner`;
  per contract it is never placed in a prompt.
- `segments[]` - `index` (the citation key the LLM sees), `id` (the `TranscriptSegment.id`
  the scorer maps `evidence[].segment_id` back to), `speaker`, `start`, `end`, `language`, `text`.
- `proposal_segments` - indices of hedged proposals ("poate ar fi bine...") that must not be
  cited by any decision (false-decision rate).
- `decisions[]`, `action_items[]`, `risks_and_questions[]` - gold items with `evidence_idx`.
  Actions carry `owner` (resolved, roster name or `Speaker N`), `owner_mention` (verbatim) and
  `deadline_phrase` (verbatim, spoken language).

## Producing a minutes JSON to score

Any `MinutesOfMeeting` dump works (`minutes.model_dump(mode="json")`), as does the repository
`store/minutes.json` map (the scorer picks the entry whose `meeting_id` matches, or the only entry).
The tests in `backend/tests/test_llm_extraction_pipeline.py` build the Track-A transcript from
this gold file with the same segment ids, so evidence maps back by id.

```
PYTHONPATH=backend .venv/Scripts/python.exe tools/eval/run_extraction_eval.py \
    --gold tools/eval/gold/synthetic_trackA.json --minutes <minutes.json>
```
