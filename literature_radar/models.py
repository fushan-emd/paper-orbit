from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PaperAnalysis:
    provider: str = "heuristic"
    score: int = 0
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    detailed_summary: str = ""
    method_clues: list[str] = field(default_factory=list)
    data_task_clues: list[str] = field(default_factory=list)
    method_flow: list[str] = field(default_factory=list)
    follow_up_prompts: list[str] = field(default_factory=list)
    evaluation: str = ""
    why_read: str = ""
    rating_dimensions: dict[str, int] = field(default_factory=dict)
    rating_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Paper:
    source: str
    external_id: str
    title: str
    abstract: str
    url: str
    published: date | None = None
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    journal: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    analysis: PaperAnalysis = field(default_factory=PaperAnalysis)

    @property
    def identity(self) -> str:
        from literature_radar.identity import normalize_doi
        return normalize_doi(self.doi) or f"{self.source}:{self.external_id}"
