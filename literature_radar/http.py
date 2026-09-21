from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


_SESSION: requests.Session | None = None


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    retry_total = kwargs.pop("retry_total", None)
    session = _session() if retry_total is None else _build_session(int(retry_total))
    response = session.request(method, url, **kwargs)
    response.raise_for_status()
    return response


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    _SESSION = _build_session(3)
    return _SESSION


def _build_session(retry_total: int) -> requests.Session:
    retry = Retry(
        total=retry_total,
        connect=retry_total,
        read=retry_total,
        status=retry_total,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504) if retry_total else (),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "bioinfo-literature-radar/0.1 (+https://github.com/local)",
            "Accept": "application/json, application/xml, text/xml, text/plain, */*",
        }
    )
    return session
