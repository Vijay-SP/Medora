"""
Medpark Meeting Intelligence System - Transcript Chunker
Splits the compact indexed transcript into context-sized fragments for sequential map calls.
"""

from dataclasses import dataclass
import math
import re
from typing import Optional
from app.core.config import settings


# Fallback turn detection when the caller does not pass explicit turn starts: "12 S3: ..."
_TURN_LINE_PATTERN = re.compile(r"^\d+ S\d+: ")


@dataclass
class Chunk:
    """A contiguous run of indexed transcript lines sent to one map call."""
    ordinal: int
    first_index: int      # first line index included (overlap lines come first)
    last_index: int       # last line index included
    overlap_until: int    # first index NOT covered by the previous chunk; items ending before it are duplicates
    text: str


def estimate_tokens(text: str) -> int:
    """Conservative token estimate from character count (LLM_CHARS_PER_TOKEN), never zero for non-empty text."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / settings.LLM_CHARS_PER_TOKEN))


def _line_cost(line: str) -> int:
    # +1 for the newline that joins lines inside the prompt
    return estimate_tokens(line) + 1


def build_chunks(
    lines: list[str],
    budget_tokens: int,
    overlap_tokens: int,
    turn_starts: Optional[set[int]] = None,
) -> list[Chunk]:
    """
    Packs indexed lines into chunks of at most budget_tokens (estimated) without ever splitting a line.

    Each chunk after the first is prefixed with up to overlap_tokens of the previous chunk's tail so
    that items straddling the cut are still seen in full; overlap_until marks where fresh lines begin.
    When more lines remain, the cut is moved back by at most two lines to land on a speaker-turn
    boundary. A single line larger than the budget is emitted as its own chunk.
    """
    n = len(lines)
    if n == 0:
        return []
    if turn_starts is None:
        turn_starts = {i for i, line in enumerate(lines) if _TURN_LINE_PATTERN.match(line)}

    costs = [_line_cost(line) for line in lines]
    chunks: list[Chunk] = []
    fresh_start = 0
    ordinal = 0

    while fresh_start < n:
        # 1. Overlap: walk back from the fresh start while the tail of the previous chunk fits the overlap budget
        overlap_start = fresh_start
        overlap_cost = 0
        if ordinal > 0 and overlap_tokens > 0:
            j = fresh_start - 1
            while j >= 0 and overlap_cost + costs[j] <= overlap_tokens:
                overlap_cost += costs[j]
                j -= 1
            overlap_start = j + 1

        # 2. Fresh lines: greedy fill up to the budget
        total = overlap_cost
        end = fresh_start - 1
        i = fresh_start
        while i < n and total + costs[i] <= budget_tokens:
            total += costs[i]
            end = i
            i += 1

        if end < fresh_start:
            # The first fresh line does not fit alongside the overlap: drop the overlap, then
            # emit it alone if it is oversized on its own.
            overlap_start = fresh_start
            total = 0
            end = fresh_start - 1
            i = fresh_start
            while i < n and total + costs[i] <= budget_tokens:
                total += costs[i]
                end = i
                i += 1
            if end < fresh_start:
                end = fresh_start
                i = fresh_start + 1

        # 3. Prefer ending right before a speaker turn, looking back at most 3 candidate lines
        if i < n:
            for cand in (end, end - 1, end - 2):
                if cand < fresh_start:
                    break
                if (cand + 1) in turn_starts:
                    end = cand
                    break

        chunks.append(
            Chunk(
                ordinal=ordinal,
                first_index=overlap_start,
                last_index=end,
                overlap_until=fresh_start,
                text="\n".join(lines[overlap_start:end + 1]),
            )
        )
        fresh_start = end + 1
        ordinal += 1

    return chunks


def filter_chunk_items(items: list[dict], chunk: Chunk) -> list[dict]:
    """
    Post-map hygiene for one chunk: keeps only evidence indices inside the chunk, drops items left
    without evidence, and (for ordinal > 0) drops items that live entirely inside the overlap region
    because the previous chunk already reported them.
    """
    kept: list[dict] = []
    for item in items:
        idx = sorted({i for i in item.get("evidence_idx", []) if chunk.first_index <= i <= chunk.last_index})
        if not idx:
            continue
        if chunk.ordinal > 0 and max(idx) < chunk.overlap_until:
            continue
        item = dict(item)
        item["evidence_idx"] = idx
        kept.append(item)
    return kept
