from __future__ import annotations

from datetime import date
from email.utils import parsedate_to_datetime


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y", "%d %b %Y", "%Y %b %d"):
        try:
            parsed = date.fromisoformat(cleaned) if fmt == "%Y-%m-%d" else None
            if parsed:
                return parsed
        except ValueError:
            pass
        try:
            from datetime import datetime

            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(cleaned).date()
    except (TypeError, ValueError, IndexError):
        return None
