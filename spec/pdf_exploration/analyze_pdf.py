import json
import re
import statistics
from collections import Counter
from pathlib import Path

import fitz
from PyPDF2 import PdfReader


ROOT = Path("/Users/shaoqing/workspace/PageIndex")
PDF_PATH = ROOT / "《运行手册》（第1版）.pdf"
OUT_PATH = ROOT / "spec" / "pdf_exploration" / "report.json"


def summarize_text(text: str) -> dict:
    text = text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    digits = len(re.findall(r"\d", text))
    return {
        "chars": len(text),
        "lines": len(lines),
        "non_ascii_chars": non_ascii,
        "cjk_chars": cjk,
        "digit_chars": digits,
        "preview": lines[:8],
    }


def is_toc_like(text: str) -> bool:
    if not text:
        return False
    patterns = [
        r"目录",
        r"contents",
        r"table of contents",
        r"有效页清单",
        r"\b\d+\.\d+\b",
    ]
    score = 0
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered if pattern.isascii() else text, re.I):
            score += 1
    score += len(re.findall(r"\b\d+\.\d+(?:/\d+(?:-\d+)?)?\b", text))
    return score >= 3


def main() -> None:
    doc = fitz.open(PDF_PATH)
    reader = PdfReader(str(PDF_PATH))

    page_sizes = Counter()
    rotations = Counter()
    text_lengths = []
    image_counts = []
    drawing_counts = []
    searchable_pages = 0
    toc_candidates = []
    short_pages = []
    blank_pages = []
    page_samples = []
    odd_pages = []

    for index, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        word_count = len(text.split())
        char_count = len(text)
        if char_count > 20:
            searchable_pages += 1
        if char_count == 0:
            blank_pages.append(index)
        if char_count < 120:
            short_pages.append(index)

        rect = page.rect
        page_sizes[(round(rect.width, 1), round(rect.height, 1))] += 1
        rotations[page.rotation] += 1
        text_lengths.append(char_count)
        image_counts.append(len(page.get_images(full=True)))
        drawing_counts.append(len(page.get_drawings()))

        lowered = text.lower()
        if index <= 40 and is_toc_like(lowered):
            toc_candidates.append(
                {
                    "page": index,
                    "summary": summarize_text(text),
                }
            )

        if index <= 5 or index in (10, 11, 12, 13, 14, 15, 16, 17) or index >= len(doc) - 2:
            page_samples.append(
                {
                    "page": index,
                    "summary": summarize_text(text),
                    "images": image_counts[-1],
                    "drawings": drawing_counts[-1],
                    "rotation": page.rotation,
                }
            )

        if (
            char_count > 0
            and word_count < 20
            and len(re.findall(r"\b\d+(?:\.\d+)?(?:/\d+(?:-\d+)?)?\b", text)) >= 3
        ):
            odd_pages.append(
                {
                    "page": index,
                    "summary": summarize_text(text),
                }
            )

    metadata = reader.metadata or {}
    outlines = []
    try:
        outline = reader.outline
        outlines = str(outline)[:2000]
    except Exception as exc:
        outlines = f"<outline read failed: {exc}>"

    report = {
        "pdf_path": str(PDF_PATH),
        "file_size_bytes": PDF_PATH.stat().st_size,
        "page_count": len(doc),
        "metadata": {
            "title": metadata.title,
            "author": metadata.author,
            "subject": metadata.subject,
            "creator": metadata.creator,
            "producer": metadata.producer,
        },
        "outline_preview": outlines,
        "page_size_distribution": [
            {"size": list(size), "count": count}
            for size, count in page_sizes.most_common()
        ],
        "rotation_distribution": dict(rotations),
        "text_length_stats": {
            "min": min(text_lengths),
            "max": max(text_lengths),
            "mean": round(statistics.mean(text_lengths), 2),
            "median": round(statistics.median(text_lengths), 2),
        },
        "image_count_stats": {
            "min": min(image_counts),
            "max": max(image_counts),
            "mean": round(statistics.mean(image_counts), 2),
            "median": round(statistics.median(image_counts), 2),
        },
        "drawing_count_stats": {
            "min": min(drawing_counts),
            "max": max(drawing_counts),
            "mean": round(statistics.mean(drawing_counts), 2),
            "median": round(statistics.median(drawing_counts), 2),
        },
        "searchable_page_ratio": round(searchable_pages / len(doc), 4),
        "blank_pages_first_50": blank_pages[:50],
        "short_pages_first_50": short_pages[:50],
        "toc_candidates": toc_candidates,
        "odd_pages": odd_pages[:20],
        "page_samples": page_samples,
    }

    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(OUT_PATH))


if __name__ == "__main__":
    main()
