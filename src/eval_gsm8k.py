"""Robust GSM8K parsing and evaluation helpers."""

from __future__ import annotations

import re
from typing import Optional, Tuple

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
FINAL_RE = re.compile(r"FINAL\s*:\s*(-?\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)


def normalize_numeric_text(text: str) -> str:
    """Normalize commas, surrounding whitespace, and trailing punctuation."""

    cleaned = text.strip().rstrip(".")
    return cleaned.replace(",", "")


def extract_gsm8k_gold(answer_full: str) -> str:
    """Extract the gold numeric answer from GSM8K's `####` format."""

    if "####" not in answer_full:
        match = NUMBER_RE.findall(answer_full)
        if not match:
            raise ValueError("Could not extract GSM8K gold answer")
        return normalize_numeric_text(match[-1])
    return normalize_numeric_text(answer_full.split("####")[-1])


def extract_gsm8k_pred(text: str) -> Optional[str]:
    """Prefer `FINAL: <number>`, then fall back to the last numeric token."""

    final_match = FINAL_RE.search(text)
    if final_match:
        return normalize_numeric_text(final_match.group(1))

    numbers = NUMBER_RE.findall(text)
    if not numbers:
        return None
    return normalize_numeric_text(numbers[-1])


def gsm8k_is_correct(pred: Optional[str], gold: str) -> bool:
    """Check exact match after numeric normalization."""

    if pred is None:
        return False
    return normalize_numeric_text(pred) == normalize_numeric_text(gold)


def evaluate_gsm8k_response(response_text: str, answer_full: str) -> Tuple[bool, str, bool, Optional[str], str]:
    """Return success, failure bucket, format flag, parsed prediction, and gold answer."""

    gold = extract_gsm8k_gold(answer_full)
    pred = extract_gsm8k_pred(response_text)
    format_ok = pred is not None
    if pred is None:
        return False, "parse_failure", False, None, gold
    if gsm8k_is_correct(pred, gold):
        return True, "ok", True, pred, gold
    return False, "wrong_answer", True, pred, gold
