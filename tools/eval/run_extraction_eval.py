"""
Medpark Meeting Intelligence System - Extraction Evaluation Scorer
Scores a MinutesOfMeeting JSON against a gold annotation file (tools/eval/gold/*.json) and prints a
Markdown table. Standard library only, so it runs anywhere without the backend virtualenv.

    python tools/eval/run_extraction_eval.py --gold tools/eval/gold/synthetic_trackA.json --minutes minutes.json
    python tools/eval/run_extraction_eval.py --gold tools/eval/gold --minutes store/minutes.json --meeting-id <id>

Matching rule for decisions and actions (gold item vs predicted item): the cited evidence segment
sets intersect AND the normalised difflib ratio of the item texts is >= 0.5. Matching is greedy 1:1
by descending ratio. Evidence indices of a prediction are recovered from evidence[].segment_id via the
gold segment table (fallback: identical start/end timestamps).
"""

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Optional

TEXT_RATIO_THRESHOLD = 0.5
SPEAKER_LABEL_RE = re.compile(r"^speaker \d+$")


def normalise(text: Optional[str]) -> str:
    """NFKD, strip diacritics/punctuation, casefold, collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = re.sub(r"[^\w\s]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip().casefold()


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def load_gold_files(gold_arg: Path) -> list[Path]:
    if gold_arg.is_dir():
        return sorted(gold_arg.glob("*.json"))
    return [gold_arg]


def load_minutes(path: Path, meeting_id: Optional[str]) -> dict[str, Any]:
    """Accepts a MinutesOfMeeting dump or the repository store map keyed by meeting id."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "summary_ro" in data or "decisions" in data:
        return data
    if meeting_id and meeting_id in data:
        return data[meeting_id]
    entries = [v for v in data.values() if isinstance(v, dict) and "decisions" in v]
    if len(entries) == 1:
        return entries[0]
    raise SystemExit(f"Cannot pick a minutes entry from {path}: pass --meeting-id (found {len(entries)} candidates)")


class GoldFragment:
    def __init__(self, data: dict[str, Any]):
        self.name: str = data.get("name", "unnamed")
        self.segments: list[dict[str, Any]] = data["segments"]
        self.id_to_index = {s["id"]: int(s["index"]) for s in self.segments}
        self.index_to_text = {int(s["index"]): s["text"] for s in self.segments}
        self.transcript_norm = " ".join(normalise(s["text"]) for s in self.segments)
        self.attendee_names = [a["name"] for a in data.get("meeting", {}).get("attendees", [])]
        self.attendee_norm = " ".join(normalise(n) for n in self.attendee_names)
        self.proposal_segments = [int(i) for i in data.get("proposal_segments", [])]
        self.decisions = data.get("decisions", [])
        self.action_items = data.get("action_items", [])
        self.risks = data.get("risks_and_questions", [])

    def evidence_indices(self, item: dict[str, Any]) -> set[int]:
        """Maps a prediction's evidence citations back to gold segment indices."""
        found: set[int] = set()
        for ev in item.get("evidence", []) or []:
            idx = self.id_to_index.get(ev.get("segment_id"))
            if idx is None:
                for s in self.segments:
                    same_start = abs(float(s["start"]) - float(ev.get("start", -1))) < 0.05
                    same_end = abs(float(s["end"]) - float(ev.get("end", -1))) < 0.05
                    if same_start and same_end:
                        idx = int(s["index"])
                        break
            if idx is not None:
                found.add(idx)
        return found

    def evidence_is_valid(self, ev: dict[str, Any]) -> bool:
        """A citation is valid when its segment resolves and the quote is verbatim from that segment."""
        idx = self.id_to_index.get(ev.get("segment_id"))
        if idx is None:
            return False
        quote = normalise(ev.get("quote"))
        return bool(quote) and quote in normalise(self.index_to_text[idx])


def match_items(
    gold_items: list[dict], pred_items: list[dict], gold_key: str, pred_key: str, gold: GoldFragment
) -> list[tuple[int, int, float]]:
    """Greedy 1:1 matching: evidence sets intersect AND text ratio >= threshold, best ratio first."""
    candidates: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gold_items):
        g_idx = set(int(i) for i in g.get("evidence_idx", []))
        for pi, p in enumerate(pred_items):
            p_idx = gold.evidence_indices(p)
            if not (g_idx & p_idx):
                continue
            r = ratio(g.get(gold_key, ""), p.get(pred_key, ""))
            if r >= TEXT_RATIO_THRESHOLD:
                candidates.append((r, gi, pi))
    candidates.sort(reverse=True)
    used_g: set[int] = set()
    used_p: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for r, gi, pi in candidates:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matches.append((gi, pi, r))
    return matches


def prf(tp: int, n_pred: int, n_gold: int) -> tuple[float, float, float]:
    p = tp / n_pred if n_pred else (1.0 if n_gold == 0 else 0.0)
    r = tp / n_gold if n_gold else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def fmt(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def score(gold: GoldFragment, minutes: dict[str, Any]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    pred_decisions = minutes.get("decisions", []) or []
    pred_actions = minutes.get("action_items", []) or []
    pred_risks = minutes.get("risks_and_questions", []) or []

    # Decisions
    d_matches = match_items(gold.decisions, pred_decisions, "decision", "decision", gold)
    p, r, f = prf(len(d_matches), len(pred_decisions), len(gold.decisions))
    rows.append((
        "Decision P / R / F1",
        f"{fmt(p)} / {fmt(r)} / {fmt(f)}",
        f"{len(d_matches)} matched, {len(pred_decisions)} predicted, {len(gold.decisions)} gold",
    ))

    # False decisions on proposal segments
    if gold.proposal_segments:
        cited_by_decisions: set[int] = set()
        for d in pred_decisions:
            cited_by_decisions |= gold.evidence_indices(d)
        hit = [i for i in gold.proposal_segments if i in cited_by_decisions]
        rows.append((
            "False-decision rate (proposal segments)",
            fmt(len(hit) / len(gold.proposal_segments)),
            f"proposal lines cited as decisions: {hit or 'none'} of {gold.proposal_segments}",
        ))
    else:
        rows.append(("False-decision rate (proposal segments)", "n/a", "no proposal segments annotated"))

    # Actions
    a_matches = match_items(gold.action_items, pred_actions, "task", "task", gold)
    p, r, f = prf(len(a_matches), len(pred_actions), len(gold.action_items))
    rows.append((
        "Action P / R / F1",
        f"{fmt(p)} / {fmt(r)} / {fmt(f)}",
        f"{len(a_matches)} matched, {len(pred_actions)} predicted, {len(gold.action_items)} gold",
    ))

    # Owner accuracy over matched actions
    owner_hits = 0
    owner_total = 0
    for gi, pi, _ in a_matches:
        g_owner = gold.action_items[gi].get("owner")
        if not g_owner:
            continue
        owner_total += 1
        if normalise(g_owner) == normalise(pred_actions[pi].get("owner")):
            owner_hits += 1
    rows.append(("Owner accuracy (matched actions)", fmt(owner_hits / owner_total) if owner_total else "n/a", f"{owner_hits}/{owner_total}"))

    # Owner fabrication over all predicted actions with a named owner
    fabricated: list[str] = []
    named = 0
    for a in pred_actions:
        owner = a.get("owner") or "Unassigned"
        n_owner = normalise(owner)
        if n_owner == "unassigned" or SPEAKER_LABEL_RE.match(n_owner):
            continue
        named += 1
        tokens = [t for t in n_owner.split() if len(t) >= 4]
        grounded = any(t in gold.transcript_norm or t in gold.attendee_norm for t in tokens)
        if not grounded:
            fabricated.append(owner)
    detail = f"{len(fabricated)}/{named}" + (f": {fabricated}" if fabricated else "")
    rows.append(("Owner fabrication rate (named owners)", fmt(len(fabricated) / named) if named else "n/a", detail))

    # Deadline phrase recall over gold actions that carry a phrase
    dl_total = 0
    dl_hits = 0
    matched_by_gold = {gi: pi for gi, pi, _ in a_matches}
    for gi, g in enumerate(gold.action_items):
        g_phrase = g.get("deadline_phrase")
        if not g_phrase:
            continue
        dl_total += 1
        pi = matched_by_gold.get(gi)
        if pi is None:
            continue
        p_phrase = normalise(pred_actions[pi].get("deadline_phrase"))
        if p_phrase and (normalise(g_phrase) in p_phrase or p_phrase in normalise(g_phrase)):
            dl_hits += 1
    rows.append(("Deadline phrase recall", fmt(dl_hits / dl_total) if dl_total else "n/a", f"{dl_hits}/{dl_total}"))

    # Risks (recall by evidence intersection + text similarity)
    r_matches = match_items(gold.risks, pred_risks, "description", "description", gold)
    rows.append(("Risk recall", fmt(len(r_matches) / len(gold.risks)) if gold.risks else "n/a", f"{len(r_matches)}/{len(gold.risks)} ({len(pred_risks)} predicted)"))

    # Evidence validity over every predicted citation
    all_ev = [ev for item in pred_decisions + pred_actions + pred_risks for ev in (item.get("evidence") or [])]
    valid = sum(1 for ev in all_ev if gold.evidence_is_valid(ev))
    rows.append(("Evidence validity", fmt(valid / len(all_ev)) if all_ev else "n/a", f"{valid}/{len(all_ev)} citations verbatim from the cited segment"))

    flags = (
        f"is_degraded={minutes.get('is_degraded', False)} "
        f"needs_name_review={minutes.get('needs_name_review', False)} "
        f"failed_chunks={minutes.get('failed_chunks', [])}"
    )
    rows.append(("Audit flags", "-", flags))
    stats = minutes.get("extraction_stats") or {}
    if stats:
        rows.append(("Extraction stats", "-", ", ".join(f"{k}={v}" for k, v in stats.items())))
    return rows


def print_markdown(name: str, model_version: str, rows: list[tuple[str, str, str]]) -> None:
    print(f"\n### {name}  (model_version: {model_version})\n")
    print("| Metric | Value | Detail |")
    print("|---|---|---|")
    for metric, value, detail in rows:
        print(f"| {metric} | {value} | {detail} |")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score extracted minutes against gold annotations.")
    parser.add_argument("--gold", type=Path, default=Path("tools/eval/gold"), help="Gold JSON file or directory")
    parser.add_argument("--minutes", type=Path, required=True, help="MinutesOfMeeting JSON (or repository minutes.json map)")
    parser.add_argument("--meeting-id", default=None, help="Entry to pick when --minutes is a repository map")
    args = parser.parse_args(argv)

    minutes = load_minutes(args.minutes, args.meeting_id)
    gold_files = load_gold_files(args.gold)
    if not gold_files:
        print(f"No gold files under {args.gold}", file=sys.stderr)
        return 2
    for gold_path in gold_files:
        gold = GoldFragment(json.loads(gold_path.read_text(encoding="utf-8")))
        print_markdown(gold.name, str(minutes.get("model_version", "?")), score(gold, minutes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
