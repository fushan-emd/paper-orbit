from __future__ import annotations

import argparse
from pathlib import Path

from literature_radar.config import load_config
from literature_radar.deepseek import deepseek_status
from literature_radar.progress import log
from literature_radar.collector import collect_library


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and analyze recent bioinformatics papers.")
    parser.add_argument("--config", default="config.toml", help="Path to TOML config.")
    parser.add_argument("--days", type=int, default=None, help="Override run.days_back.")
    parser.add_argument("--max-per-source", type=int, default=None, help="Override run.max_papers_per_source.")
    parser.add_argument("--min-score", type=int, default=None, help="Override run.min_score.")
    parser.add_argument("--output", default=None, help="Optional explicit report path (.html or .md).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from literature_radar.paths import acquire_workspace_lock
    acquire_workspace_lock()
    config = load_config(args.config)

    days_back = args.days or int(config["run"]["days_back"])
    max_per_source = args.max_per_source or int(config["run"]["max_papers_per_source"])
    min_score = args.min_score if args.min_score is not None else int(config["run"]["min_score"])
    log(f"Analysis backend: {deepseek_status(config)}")

    config['run'].update(days_back=days_back,max_papers_per_source=max_per_source,min_score=min_score)
    collect_library(config,Path.cwd(),log,args.output)


if __name__ == "__main__":
    main()
