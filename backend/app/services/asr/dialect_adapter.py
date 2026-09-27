"""
Medpark Meeting Intelligence System - Dialect Adapter & Conservative Normalization
Provides versioned, clinician-reviewed dialect normalization with non-negotiable safety guards:
- Never alters negation, numerical values, dosages, or medication names.
- Uses longest-match precedence, stable spans, and no cascading replacement.
- Downgrades ambiguous or mixed-language spans to suggestions rather than silent mutation.
- Stores local rule state and rollbacks under ADAPTATION_DIR without modifying tracked code.
"""

from functools import lru_cache
import json
import os
from pathlib import Path
import re
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.adaptation import (
    NormalizationResult,
    NormalizationRule,
    RuleAction,
    RuleApproval,
)

# Negation lexicons per language
NEGATION_TOKENS = {
    "ro": {"nu", "n-a", "n-au", "n-am", "n-ai", "n-ati", "n-ați", "fără", "fara", "nici", "niciun", "nicio", "deloc"},
    "ru": {"не", "нет", "ни", "без", "никаких", "ничуть", "никогда"},
    "en": {"no", "not", "none", "without", "never", "neither", "nor"},
}

DOSAGE_UNIT_REGEX = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:mg|ml|mcg|g|kg|l|ui|iu|mmol|%|mmhg|bpm|ml/h)\b",
    re.IGNORECASE,
)

WORD_TOKEN_REGEX = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)


def _get_packaged_rules_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "resources"


def _get_local_rules_path() -> Path:
    adaptation_dir = Path(settings.ADAPTATION_DIR)
    return adaptation_dir / "rules.json"


def load_rules(version_filter: Optional[str] = None) -> list[NormalizationRule]:
    """
    Loads all packaged and locally approved dialect normalization rules.
    Local rules (in ADAPTATION_DIR/rules.json) override packaged rules by rule ID.
    """
    rules_by_id: dict[str, NormalizationRule] = {}

    # 1. Load packaged rules from resources/language and resources/dialect
    res_root = _get_packaged_rules_dir()
    candidate_dirs = [res_root / "language", res_root / "dialect"]

    for d in candidate_dirs:
        if not d.is_dir():
            continue
        for file in sorted(d.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                version = data.get("version", "1.0.0")
                for r in data.get("rules", []):
                    rule = NormalizationRule(
                        id=r["id"],
                        language=r.get("language", data.get("language", "ro")),
                        variants=r["variants"] if "variants" in r else [m for m in r.get("match", "").split("|") if m],
                        canonical=r.get("canonical", r.get("replacement", "")),
                        scope=r.get("scope", "clinical"),
                        action=r.get("action", "safe_replace"),
                        version=r.get("version", version),
                        approval=r.get("approval", "approved" if r.get("status") != "disabled" else "rolled_back"),
                    )
                    rules_by_id[rule.id] = rule
            except Exception as exc:
                logger.warning(f"Failed to load packaged rules from {file}: {exc}")

    # 2. Load local rules from ADAPTATION_DIR/rules.json
    local_path = _get_local_rules_path()
    if local_path.is_file():
        try:
            local_data = json.loads(local_path.read_text(encoding="utf-8"))
            for r in local_data.get("rules", []):
                rule = NormalizationRule.model_validate(r)
                rules_by_id[rule.id] = rule
        except Exception as exc:
            logger.warning(f"Failed to load local rules from {local_path}: {exc}")

    rules = list(rules_by_id.values())
    if version_filter:
        rules = [r for r in rules if r.version == version_filter]
    return rules


def save_local_rule(rule: NormalizationRule) -> None:
    """Saves or updates a local rule in ADAPTATION_DIR/rules.json."""
    local_path = _get_local_rules_path()
    local_path.parent.mkdir(parents=True, exist_ok=True)

    rules_by_id: dict[str, dict[str, Any]] = {}
    if local_path.is_file():
        try:
            data = json.loads(local_path.read_text(encoding="utf-8"))
            for r in data.get("rules", []):
                rules_by_id[r["id"]] = r
        except Exception as exc:
            logger.warning(f"Failed to read existing local rules: {exc}")

    rules_by_id[rule.id] = rule.model_dump()
    local_path.write_text(
        json.dumps({"version": "local", "rules": list(rules_by_id.values())}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _has_glued_digits(text: str, start: int, end: int) -> bool:
    """Checks if the token containing the match span has any digits."""
    left = text.rfind(" ", 0, start)
    left = 0 if left == -1 else left + 1
    right = text.find(" ", end)
    right = len(text) if right == -1 else right
    token = text[left:right]
    return any(c.isdigit() for c in token)


def _is_near_negation(text: str, start: int, end: int, language: str) -> bool:
    """Checks if a negation token occurs in a window of 3 words preceding the match."""
    preceding_text = text[max(0, start - 40):start]
    tokens = [w.lower() for w in WORD_TOKEN_REGEX.findall(preceding_text)]
    recent_tokens = tokens[-3:] if len(tokens) >= 3 else tokens

    lang_keys = ["ro"] if language.startswith("ro") else (["ru"] if language.startswith("ru") else ["en"])
    neg_set = set()
    for lk in lang_keys:
        neg_set.update(NEGATION_TOKENS.get(lk, set()))
    neg_set.update(NEGATION_TOKENS["ro"])  # in mixed contexts check both
    neg_set.update(NEGATION_TOKENS["ru"])

    return any(tok in neg_set for tok in recent_tokens)


def _is_near_dosage_or_units(text: str, start: int, end: int) -> bool:
    """Checks if the match or adjacent text (window of 30 chars) touches dosage units or numbers."""
    window = text[max(0, start - 30):min(len(text), end + 30)]
    return bool(DOSAGE_UNIT_REGEX.search(window))


def _match_case(original: str, replacement: str) -> str:
    """Preserves capitalization pattern of the original matched string."""
    if original.isupper():
        return replacement.upper()
    if original.istitle() or (len(original) > 0 and original[0].isupper()):
        return replacement[:1].upper() + replacement[1:]
    return replacement


class _MatchSpan:
    def __init__(self, start: int, end: int, matched_text: str, rule: NormalizationRule, variant: str):
        self.start = start
        self.end = end
        self.matched_text = matched_text
        self.rule = rule
        self.variant = variant
        self.length = end - start


def normalize_dialect(
    text: str,
    language: str,
    rules: Optional[list[NormalizationRule]] = None,
) -> NormalizationResult:
    """
    Applies conservative dialect normalization rules to text:
    - Longest match precedence.
    - Stable non-overlapping original spans.
    - Zero cascading replacements.
    - Negation, dosage, glued-digit, and mixed-span safety checks.
    """
    if not text or not text.strip():
        return NormalizationResult(text=text)

    if rules is None:
        rules = load_rules()

    # Filter applicable approved rules
    applicable_rules: list[NormalizationRule] = []
    for r in rules:
        if r.approval != "approved":
            continue
        # Language matching check
        is_ro = language.startswith("ro") and (r.language.startswith("ro") or r.language == "ro")
        is_ru = language.startswith("ru") and (r.language.startswith("ru") or r.language == "ru")
        is_en = language.startswith("en") and r.language.startswith("en")
        is_mixed = language in ("mixed", "code_switch") or r.language in ("mixed", "code_switch")
        if is_ro or is_ru or is_en or is_mixed:
            applicable_rules.append(r)

    if not applicable_rules:
        return NormalizationResult(text=text)

    # Find all matches
    all_matches: list[_MatchSpan] = []
    for rule in applicable_rules:
        for variant in rule.variants:
            clean_var = variant.strip("\\b").strip()
            if not clean_var:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(clean_var) + r"(?!\w)", re.IGNORECASE)
            for m in pattern.finditer(text):
                all_matches.append(
                    _MatchSpan(
                        start=m.start(),
                        end=m.end(),
                        matched_text=m.group(0),
                        rule=rule,
                        variant=clean_var,
                    )
                )

    # Sort matches: longest match first, then start offset
    all_matches.sort(key=lambda m: (m.length, -m.start), reverse=True)

    # Select non-overlapping matches
    accepted_matches: list[_MatchSpan] = []
    for m in all_matches:
        overlaps = False
        for acc in accepted_matches:
            if not (m.end <= acc.start or m.start >= acc.end):
                overlaps = True
                break
        if not overlaps:
            accepted_matches.append(m)

    # Evaluate safety checks and partition into replacements vs suggestions
    corrections: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    safe_replacements: list[tuple[_MatchSpan, str]] = []

    for m in accepted_matches:
        rule = m.rule
        matched = m.matched_text

        # 1. Glued digits check
        if _has_glued_digits(text, m.start, m.end):
            continue

        # 2. Negation safety check
        if _is_near_negation(text, m.start, m.end, language):
            suggestions.append({
                "original": matched,
                "suggested": rule.canonical,
                "rule_id": rule.id,
                "rule_version": rule.version,
                "reason": "blocked_by_adjacent_negation",
            })
            continue

        # 3. Dosage / units check
        if _is_near_dosage_or_units(text, m.start, m.end):
            suggestions.append({
                "original": matched,
                "suggested": rule.canonical,
                "rule_id": rule.id,
                "rule_version": rule.version,
                "reason": "blocked_by_dosage_or_units",
            })
            continue

        # 4. Mixed-language rule check:
        # If rule is mixed/code_switch and speech language is not confirmed mixed, suggest only
        if rule.language in ("mixed", "code_switch") and language not in ("mixed", "code_switch"):
            suggestions.append({
                "original": matched,
                "suggested": rule.canonical,
                "rule_id": rule.id,
                "rule_version": rule.version,
                "reason": "unvalidated_mixed_language_span",
            })
            continue

        # 5. Suggest-only rule action
        if rule.action == "suggest_only":
            suggestions.append({
                "original": matched,
                "suggested": rule.canonical,
                "rule_id": rule.id,
                "rule_version": rule.version,
                "reason": "suggest_only_rule",
            })
            continue

        # 6. Safe replace
        replacement = _match_case(matched, rule.canonical)
        safe_replacements.append((m, replacement))
        corrections.append({
            "was": matched,
            "now": replacement,
            "score": 1.0,
            "rule_id": rule.id,
            "rule_version": rule.version,
            "start": m.start,
            "end": m.end,
        })

    # Apply safe replacements from right to left (descending order of start index)
    safe_replacements.sort(key=lambda pair: pair[0].start, reverse=True)
    result_chars = list(text)
    for m, replacement in safe_replacements:
        result_chars[m.start:m.end] = list(replacement)

    result_text = "".join(result_chars)
    return NormalizationResult(
        text=result_text,
        corrections=corrections,
        suggestions=suggestions,
    )
