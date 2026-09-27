# Medora Offline ASR Evaluation Harness

The Medora ASR Evaluation Harness provides reproducible, offline measurement of speech recognition performance across Romanian, Russian, English, and code-switched clinical conversations.

It computes **Word Error Rate (WER)**, **Character Error Rate (CER)**, **clinical entity recall**, **critical-fact inversions (negations & dosages)**, and **silence hallucinations** without invoking the live pipeline or relying on external cloud APIs.

---

## 1. Core Principles & Safeguards

1. **Independent Manifest Splits**:
   - Audio recordings and overlapping acoustic regions cannot appear in multiple splits (`train`, `dev`, `test`).
   - Split manifests strictly enforce unique SHA-256 checksums per recording.
2. **Beyond Naive WER**:
   - A model that drops WER by 2% but misses negations (*"nu are pneumonie"* $\to$ *"are pneumonie"*) or alters drug dosages (*"4 mg"* $\to$ *"40 mg"*) is a clinical hazard and will fail evaluation.
   - Clinical entity recall and critical-fact checks are first-class gates.
3. **Clustered Paired Bootstrap Confidence Intervals**:
   - Bootstrap resampling ($B=1000$) is clustered at the recording level using a fixed seed (`seed=42`) to compute honest 95% confidence intervals $[p_{2.5}, p_{97.5}]$.
4. **Offline & Air-Gapped**:
   - Operates strictly on local JSON manifests and saved hypotheses. Never calls remote telemetry.

---

## 2. Manifest & Hypothesis Formats

### Gold Manifest (`ASRManifest`)
```json
{
  "schema_version": "1.0.0",
  "recordings": [
    {
      "recording_id": "rec_001",
      "checksum_sha256": "abcdef...",
      "duration_seconds": 12.0,
      "split": "test",
      "acoustic_condition": "clean",
      "segments": [
        {
          "segment_id": "seg_001",
          "start": 0.5,
          "end": 6.0,
          "speaker": "Speaker 1",
          "language": "ro",
          "verbatim_text": "Pacientul nu are alergie la penicilină.",
          "entities": [{ "term": "penicilină", "category": "medication" }],
          "critical_facts": [{ "kind": "negation", "expected_token": "nu" }]
        }
      ]
    }
  ]
}
```

### Hypotheses (`ASRHypothesisSet`)
```json
{
  "schema_version": "1.0.0",
  "model_id": "whisper-large-v3-turbo",
  "runtime": "faster-whisper",
  "hypotheses": [
    {
      "recording_id": "rec_001",
      "segments": [
        { "start": 0.5, "end": 6.0, "text": "Pacientul nu are alergie la penicilină." }
      ]
    }
  ]
}
```

---

## 3. Running Evaluation

Run evaluation offline via CLI:
```powershell
python tools/eval/run_asr_eval.py --manifest <gold_manifest.json> --hypotheses <hypotheses.json> --output <report.json>
```

Compare a candidate model against a baseline:
```powershell
python tools/eval/run_asr_eval.py `
  --manifest tools/eval/fixtures/asr_synthetic.json `
  --hypotheses candidate_hypotheses.json `
  --compare baseline_hypotheses.json `
  --output report.json
```

---

## 4. Annotation Pilot Planning Target

For real-world clinical calibration at Medpark Hospital:
- **Target Size**: Initial pilot of approximately **2–3 hours** of recorded meetings.
- **Diversity**: Multi-speaker clinical turns, room microphones (far-field), lapel/boundary mics.
- **Languages**: Balanced representation of standard Romanian, Moldovan regional expressions, Russian clinical terms, English technology terms, and within-utterance code-switching.
