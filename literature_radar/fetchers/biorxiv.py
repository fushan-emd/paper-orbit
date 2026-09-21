from __future__ import annotations

from datetime import date

from literature_radar.fetchers.common import parse_date
from literature_radar.http import request
from literature_radar.models import Paper
from literature_radar.text import clean_text, matches_profile_text


def fetch_biorxiv(config: dict, start_date: date, end_date: date, max_results: int) -> list[Paper]:
    source_config = config["sources"]["biorxiv"]
    papers = []
    for server in source_config.get("servers", ["biorxiv"]):
        try:
            papers.extend(_fetch_server(server, start_date, end_date, max_results, config))
        except Exception as exc:
            print(f"  warning: {server} failed inside biorxiv source: {exc}", flush=True)
    return papers[:max_results]


def _fetch_server(
    server: str,
    start_date: date,
    end_date: date,
    max_results: int,
    config: dict,
) -> list[Paper]:
    cursor = 0
    papers = []
    while len(papers) < max_results:
        url = f"https://api.biorxiv.org/details/{server}/{start_date.isoformat()}/{end_date.isoformat()}/{cursor}"
        response = request("GET", url, timeout=45)
        payload = response.json()
        collection = payload.get("collection", [])
        if not collection:
            break
        for item in collection:
            text = f"{item.get('title', '')}\n{item.get('abstract', '')}"
            if matches_profile_text(text, config):
                papers.append(_parse_item(server, item))
                if len(papers) >= max_results:
                    break
        cursor += len(collection)
        if len(collection) < 100:
            break
    return papers


def _parse_item(server: str, item: dict) -> Paper:
    doi = clean_text(item.get("doi"))
    title = clean_text(item.get("title"))
    abstract = clean_text(item.get("abstract"))
    authors = [name.strip() for name in clean_text(item.get("authors")).split(";") if name.strip()]
    published = parse_date(item.get("date"))
    url = f"https://www.biorxiv.org/content/{doi}v{item.get('version', '1')}" if server == "biorxiv" else f"https://www.medrxiv.org/content/{doi}v{item.get('version', '1')}"
    return Paper(
        source=server,
        external_id=f"{doi}v{item.get('version', '1')}",
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        journal=server,
        published=published,
        url=url,
        raw=item,
    )
