from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import requests

from literature_radar.fetchers.common import parse_date
from literature_radar.http import request
from literature_radar.models import Paper
from literature_radar.text import clean_text, matches_profile_text


ATOM = {"atom": "http://www.w3.org/2005/Atom"}
RSS = {
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def fetch_arxiv(config: dict, start_date: date, end_date: date, max_results: int) -> list[Paper]:
    source_config = config["sources"]["arxiv"]
    params = {
        "search_query": source_config["query"],
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        response = request("GET", "https://export.arxiv.org/api/query", params=params, timeout=45)
    except requests.RequestException as exc:
        print(f"  warning: arxiv API failed, trying RSS fallback: {exc}", flush=True)
        return _fetch_arxiv_rss(config, start_date, end_date, max_results)

    root = ET.fromstring(response.text)
    papers = []
    for entry in root.findall("atom:entry", ATOM):
        paper = _parse_entry(entry)
        if not paper or not paper.published:
            continue
        if paper.published < start_date or paper.published > end_date:
            continue
        if matches_profile_text(f"{paper.title}\n{paper.abstract}", config):
            papers.append(paper)
    if papers:
        return papers

    print("  warning: arxiv API returned 0 papers, trying RSS fallback.", flush=True)
    return _fetch_arxiv_rss(config, start_date, end_date, max_results)


def _fetch_arxiv_rss(config: dict, start_date: date, end_date: date, max_results: int) -> list[Paper]:
    source_config = config["sources"]["arxiv"]
    categories = source_config.get("categories", [])
    papers_by_id: dict[str, Paper] = {}
    for category in categories:
        if len(papers_by_id) >= max_results:
            break
        url = f"https://rss.arxiv.org/rss/{category}"
        try:
            response = request("GET", url, timeout=30)
        except requests.RequestException as exc:
            print(f"  warning: arxiv RSS category {category} failed: {exc}", flush=True)
            continue

        root = ET.fromstring(response.text)
        for item in root.findall("./channel/item"):
            paper = _parse_rss_item(item)
            if not paper or not paper.published:
                continue
            if paper.published < start_date or paper.published > end_date:
                continue
            if not matches_profile_text(f"{paper.title}\n{paper.abstract}", config):
                continue
            papers_by_id[paper.external_id] = paper
            if len(papers_by_id) >= max_results:
                break
    return list(papers_by_id.values())


def _parse_entry(entry: ET.Element) -> Paper | None:
    title = clean_text(_text(entry, "atom:title"))
    abstract = clean_text(_text(entry, "atom:summary"))
    entry_id = clean_text(_text(entry, "atom:id"))
    if not title or not entry_id:
        return None

    external_id = entry_id.rstrip("/").split("/")[-1]
    authors = [clean_text(node.findtext("atom:name", default="", namespaces=ATOM)) for node in entry.findall("atom:author", ATOM)]
    authors = [author for author in authors if author]
    published = parse_date(_text(entry, "atom:published"))
    doi = None
    for link in entry.findall("atom:link", ATOM):
        if link.attrib.get("title") == "doi":
            doi = link.attrib.get("href")

    return Paper(
        source="arxiv",
        external_id=external_id,
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        journal="arXiv",
        published=published,
        url=entry_id,
        raw={"arxiv_id": external_id},
    )


def _parse_rss_item(item: ET.Element) -> Paper | None:
    title = clean_text(item.findtext("title"))
    link = clean_text(item.findtext("link"))
    guid = clean_text(item.findtext("guid"))
    description = _clean_rss_description(item.findtext("description"))
    if not title or not link:
        return None

    external_id = link.rstrip("/").split("/")[-1]
    if guid and ":" in guid:
        external_id = guid.rsplit(":", 1)[-1]
    authors = _rss_authors(item)
    return Paper(
        source="arxiv",
        external_id=external_id,
        doi=None,
        title=title,
        abstract=description,
        authors=authors,
        journal="arXiv",
        published=parse_date(item.findtext("pubDate")),
        url=link,
        raw={"arxiv_id": external_id, "fallback": "rss"},
    )


def _clean_rss_description(value: str | None) -> str:
    text = clean_text(value)
    marker = "Abstract:"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    return text


def _rss_authors(item: ET.Element) -> list[str]:
    creator = clean_text(item.findtext("dc:creator", default="", namespaces=RSS))
    if not creator:
        return []
    return [author.strip() for author in creator.split(",") if author.strip()]


def _text(element: ET.Element, path: str) -> str | None:
    node = element.find(path, ATOM)
    return node.text if node is not None else None
