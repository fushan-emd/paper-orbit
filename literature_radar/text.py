from __future__ import annotations

import re
from html import unescape


WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    without_tags = TAG_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", unescape(without_tags)).strip()


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def matching_keywords(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def matches_profile_text(text: str, config: dict) -> bool:
    profile = config["profile"]
    core_keywords = profile.get("core_keywords") or profile.get("include_keywords", [])
    if matching_keywords(text, core_keywords):
        return True

    lowered = text.lower()
    has_bio_context = "bioinformatics" in lowered or "computational biology" in lowered
    has_method_context = any(
        keyword in lowered
        for keyword in ["software", "tool", "pipeline", "package", "benchmark", "deep learning", "machine learning"]
    )
    return has_bio_context and has_method_context


def first_sentence(text: str, max_chars: int = 260) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    sentence_end = re.search(r"(?<=[.!?])\s+", cleaned)
    sentence = cleaned[: sentence_end.start()] if sentence_end else cleaned
    if len(sentence) <= max_chars:
        return sentence
    return sentence[: max_chars - 3].rstrip() + "..."
