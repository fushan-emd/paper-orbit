from __future__ import annotations

from datetime import datetime


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def progress(label: str, current: int, total: int, width: int = 28) -> None:
    total = max(total, 1)
    current = min(current, total)
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    percent = int(100 * current / total)
    log(f"{label} [{bar}] {current}/{total} {percent:3d}%")
