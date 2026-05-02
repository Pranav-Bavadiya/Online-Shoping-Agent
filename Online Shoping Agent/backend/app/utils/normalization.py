"""Query / text normalization helpers."""
import re
from typing import Optional


def normalize_text(text: str) -> str:
    """Lowercase, strip extra whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_keywords(keywords: list[str]) -> list[str]:
    return [normalize_text(k) for k in keywords if k.strip()]


def keyword_overlap_ratio(a: list[str], b: list[str]) -> float:
    """Jaccard-like similarity between two keyword lists."""
    if not a or not b:
        return 0.0
    set_a = set(normalize_keywords(a))
    set_b = set(normalize_keywords(b))
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def extract_price_from_text(text: str) -> Optional[float]:
    """Very simple price extractor: returns first number found."""
    match = re.search(r"[\d,]+(?:\.\d+)?", text.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None
