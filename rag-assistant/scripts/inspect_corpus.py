"""Audit the local KNX corpus without modifying it."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pymupdf
from tqdm import tqdm

from src.manifest import iter_pdf_paths


def audit(corpus_dir: Path) -> dict:
    paths = iter_pdf_paths(corpus_dir)
    volumes: Counter[str] = Counter()
    pages = 0
    size = 0
    empty_first_page = 0
    low_text_first_page = 0
    details = []
    for path in tqdm(paths, desc="Audit", unit="pdf"):
        relative = path.relative_to(corpus_dir)
        volume = relative.parts[0] if relative.parts else "Other"
        volumes[volume] += 1
        size += path.stat().st_size
        with pymupdf.open(path) as document:
            page_count = document.page_count
            pages += page_count
            first_text = document[0].get_text("text").strip() if page_count else ""
        chars = len(first_text)
        if chars == 0:
            empty_first_page += 1
        elif chars < 300:
            low_text_first_page += 1
        details.append(
            {
                "path": relative.as_posix(),
                "pages": page_count,
                "first_page_chars": chars,
            }
        )
    return {
        "pdfs": len(paths),
        "pages": pages,
        "size_mb": round(size / (1024 * 1024), 1),
        "empty_first_page": empty_first_page,
        "low_text_first_page": low_text_first_page,
        "volumes": dict(sorted(volumes.items())),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita el corpus KNX local.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.corpus)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))


if __name__ == "__main__":
    main()
