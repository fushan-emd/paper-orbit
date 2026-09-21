from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from typing import Iterable

from literature_radar.http import request
from literature_radar.models import Paper
from literature_radar.text import clean_text


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def fetch_pubmed(config: dict, start_date: date, end_date: date, max_results: int) -> list[Paper]:
    source_config = config["sources"]["pubmed"]
    ids = _search_ids(config, source_config, start_date, end_date, max_results)
    if not ids:
        return []
    return _fetch_details(source_config, ids)


def _search_ids(config: dict, source_config: dict, start_date: date, end_date: date, max_results: int) -> list[str]:
    ids = _search_ids_for_term(source_config, source_config["query"], start_date, end_date, max_results)

    journal_term = _journal_search_term(config, source_config)
    if journal_term:
        journal_limit = int(source_config.get("journal_max_results", max(10, max_results // 2)))
        journal_ids = _search_ids_for_term(source_config, journal_term, start_date, end_date, journal_limit)
        ids = _merge_ids(ids, journal_ids)

    return ids


def _search_ids_for_term(
    source_config: dict,
    term: str,
    start_date: date,
    end_date: date,
    max_results: int,
) -> list[str]:
    params = {
        "db": "pubmed",
        "term": term.strip(),
        "retmode": "json",
        "retmax": str(max_results),
        "sort": "pub date",
        "datetype": "pdat",
        "mindate": start_date.isoformat(),
        "maxdate": end_date.isoformat(),
    }
    _add_ncbi_identity(params, source_config)
    method = "POST" if len(term) > 1200 else "GET"
    response = request(
        method,
        f"{BASE_URL}/esearch.fcgi",
        params=params if method == "GET" else None,
        data=params if method == "POST" else None,
        timeout=30,
    )
    payload = response.json()
    return payload.get("esearchresult", {}).get("idlist", [])


def _journal_search_term(config: dict, source_config: dict) -> str:
    journals = [journal.strip() for journal in source_config.get("journals", []) if journal.strip()]
    if not source_config.get("enable_journal_watch", False) or not journals:
        return ""

    journal_query = " OR ".join(f'"{_escape_pubmed_phrase(journal)}"[Journal]' for journal in journals)
    journal_block = f"({journal_query})"
    if source_config.get("journal_profile_filter", True):
        profile_terms = _profile_terms(config)
        if profile_terms:
            journal_block = f"({journal_block} AND ({profile_terms}))"

    return journal_block


def _merge_ids(primary: list[str], secondary: list[str]) -> list[str]:
    merged = []
    seen = set()
    for pmid in primary + secondary:
        if pmid in seen:
            continue
        seen.add(pmid)
        merged.append(pmid)
    return merged


def _profile_terms(config: dict) -> str:
    keywords = config.get("profile", {}).get("core_keywords") or config.get("profile", {}).get("include_keywords", [])
    seen = set()
    terms = []
    for keyword in keywords:
        normalized = str(keyword).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        terms.append(f'"{_escape_pubmed_phrase(normalized)}"[Title/Abstract]')
    return " OR ".join(terms)


def _escape_pubmed_phrase(value: str) -> str:
    return value.replace('"', '\\"')


def _fetch_details(source_config: dict, ids: Iterable[str]) -> list[Paper]:
    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
    }
    _add_ncbi_identity(params, source_config)
    response = request("GET", f"{BASE_URL}/efetch.fcgi", params=params, timeout=45)

    root = ET.fromstring(response.text)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        paper = _parse_pubmed_article(article)
        if paper:
            papers.append(paper)
    return papers


def _parse_pubmed_article(article: ET.Element) -> Paper | None:
    pmid = clean_text(_text(article, ".//PMID"))
    title = clean_text(_text(article, ".//ArticleTitle"))
    if not pmid or not title:
        return None

    abstract_parts = [clean_text("".join(node.itertext())) for node in article.findall(".//Abstract/AbstractText")]
    abstract = " ".join(part for part in abstract_parts if part)
    authors = _authors(article)
    doi = _article_id(article, "doi")
    journal = clean_text(_text(article, ".//Journal/Title"))
    published = _pub_date(article)

    return Paper(
        source="pubmed",
        external_id=pmid,
        title=title,
        abstract=abstract,
        authors=authors,
        doi=doi,
        journal=journal,
        published=published,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw={"pmid": pmid,
             "publication_types":[clean_text("".join(n.itertext())) for n in article.findall('.//PublicationType')],
             "retraction_status":('retracted' if article.find(".//CommentsCorrections[@RefType='RetractionIn']") is not None or any(n.text=='Retracted Publication' for n in article.findall('.//PublicationType')) else 'retraction_notice' if any(n.text=='Retraction of Publication' for n in article.findall('.//PublicationType')) else 'not_flagged_by_source')},
    )


def _authors(article: ET.Element) -> list[str]:
    names = []
    for author in article.findall(".//AuthorList/Author"):
        last = clean_text(_text(author, "LastName"))
        initials = clean_text(_text(author, "Initials"))
        collective = clean_text(_text(author, "CollectiveName"))
        if last:
            names.append(f"{last} {initials}".strip())
        elif collective:
            names.append(collective)
    return names


def _article_id(article: ET.Element, id_type: str) -> str | None:
    for node in article.findall(".//ArticleIdList/ArticleId"):
        if node.attrib.get("IdType") == id_type:
            return clean_text(node.text)
    return None


def _pub_date(article: ET.Element) -> date | None:
    pub_date = article.find(".//Article/Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year = clean_text(_text(pub_date, "Year"))
    month = clean_text(_text(pub_date, "Month"))
    day = clean_text(_text(pub_date, "Day")) or "1"
    month_map = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    if not year:
        return None
    try:
        month_value = int(month) if month.isdigit() else month_map.get(month[:3], 1)
        return date(int(year), month_value, int(day))
    except ValueError:
        return date(int(year), 1, 1)


def _text(element: ET.Element, path: str) -> str | None:
    node = element.find(path)
    return "".join(node.itertext()) if node is not None else None


def _add_ncbi_identity(params: dict, source_config: dict) -> None:
    if source_config.get("email"):
        params["email"] = source_config["email"]
    from literature_radar.secrets import get_secret
    key=get_secret("NCBI_API_KEY") or source_config.get("api_key")
    if key:params["api_key"]=key
