from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from requests import HTTPError, RequestException, Timeout

from literature_radar.fetchers.common import parse_date
from literature_radar.http import request
from literature_radar.models import Paper
from literature_radar.text import clean_text, matches_profile_text


def fetch_openalex(config: dict, start_date: date, end_date: date, max_results: int) -> list[Paper]:
    source_config = config["sources"]["openalex"]
    timeout_seconds = int(source_config.get("timeout_seconds", 12))
    effective_max_results = min(max_results, int(source_config.get("max_results", max_results)))
    _raise_if_in_cooldown(config)
    params = {
        "search": source_config["query"],
        "filter": f"from_publication_date:{start_date.isoformat()},to_publication_date:{end_date.isoformat()}",
        "sort": "publication_date:desc",
        "per-page": str(effective_max_results),
    }
    from literature_radar.secrets import get_secret
    headers = {}
    key=get_secret("OPENALEX_API_KEY")
    if key:headers["Authorization"]="Bearer "+key
    if source_config.get("mailto"):
        params["mailto"] = source_config["mailto"]
        headers["User-Agent"] = f"PaperOrbit/0.4 (mailto:{source_config['mailto']})"
    try:
        response = request(
            "GET",
            "https://api.openalex.org/works",
            params=params,
            headers=headers,
            timeout=(6, timeout_seconds),
            retry_total=0,
        )
    except HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 429:
            cooldown_minutes = int(source_config.get("cooldown_minutes", 30))
            _save_cooldown(config, cooldown_minutes)
            raise RuntimeError(
                "OpenAlex rate limited this run (HTTP 429). "
                f"Cooling down OpenAlex for {cooldown_minutes} minutes. "
                "Configure an OpenAlex API key in Settings or wait for the quota to reset."
            ) from exc
        raise
    except Timeout as exc:
        raise RuntimeError(
            f"OpenAlex timed out after {timeout_seconds}s. "
            "Try a larger timeout or disable OpenAlex temporarily if your network is slow."
        ) from exc
    except RequestException as exc:
        raise RuntimeError("OpenAlex connection failed") from exc
    payload = response.json()

    papers = []
    for item in payload.get("results", []):
        paper = _parse_work(item)
        if matches_profile_text(f"{paper.title}\n{paper.abstract}", config):
            papers.append(paper)
    return papers


def _state_path(config: dict) -> Path:
    database_path = Path(config["project"]["database"])
    return Path(config.get("_workspace_root",".")) / database_path.parent / "openalex_state.json"


def _raise_if_in_cooldown(config: dict) -> None:
    state_path = _state_path(config)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    cooldown_until = float(state.get("cooldown_until", 0))
    now = time.time()
    if cooldown_until <= now:
        return
    wait_minutes = max(1, round((cooldown_until - now) / 60))
    raise RuntimeError(f"OpenAlex cooldown is active for about {wait_minutes} more minutes after a recent HTTP 429.")


def _save_cooldown(config: dict, minutes: int) -> None:
    state_path = _state_path(config)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cooldown_until": time.time() + max(1, minutes) * 60,
        "reason": "HTTP 429",
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_work(item: dict) -> Paper:
    title = clean_text(item.get("title") or item.get("display_name"))
    abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index") or {})
    doi = item.get("doi")
    external_id = item.get("id", "").rstrip("/").split("/")[-1] or title
    authors = []
    for authorship in item.get("authorships", []):
        author = authorship.get("author", {})
        if author.get("display_name"):
            authors.append(author["display_name"])
    host = item.get("primary_location", {}).get("source") or {}
    url = item.get("doi") or item.get("id") or ""

    return Paper(
        source="openalex",
        external_id=external_id,
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        journal=host.get("display_name"),
        published=parse_date(item.get("publication_date")),
        url=url,
        raw={"openalex_id": item.get("id"), "type": item.get("type")},
    )


def _abstract_from_inverted_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    positioned = []
    for word, positions in index.items():
        for position in positions:
            positioned.append((position, word))
    positioned.sort(key=lambda pair: pair[0])
    return clean_text(" ".join(word for _, word in positioned))
