#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:  # The workspace bundle provides `pypdf`; the repo env provides `PyPDF2`.
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - fallback for project env
    from PyPDF2 import PdfReader  # type: ignore


ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results"
PDF_PATH = ROOT / "operations_manual_v1.pdf"
STRUCTURE_PATH = RESULTS_DIR / "operations_manual_v1_structure.json"
QUESTIONS_PATH = RESULTS_DIR / "questions.json"
RAW_RESULTS_PATH = RESULTS_DIR / "raw_results.json"
EVALUATION_RESULTS_PATH = RESULTS_DIR / "evaluation_results.json"
REPORT_PATH = RESULTS_DIR / "test_report.xlsx"
LOG_PATH = RESULTS_DIR / "test_log.txt"

SKILL_RUN_URL = os.getenv("SKILL_RUN_URL", "")
SKILL_API_KEY = os.getenv("SKILL_RUN_API_KEY", "")

SCORING_BASE_URL = os.getenv("SCORING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
SCORING_API_KEY = os.getenv("SCORING_API_KEY", "")
SCORING_MODEL = os.getenv("SCORING_MODEL", "qwen3.6-plus")

TARGET_QUESTION_COUNT = 500
BATCH_COUNT = 5
DEFAULT_WORKERS = 8
DEFAULT_SCORE_WORKERS = 8

HEADER_RE = re.compile(r"^(.+?)版本：\d{2}-\d{2}\s*$")
DATE_HEADER_RE = re.compile(r"^\d{4}\s*年\s*\d{2}\s*月\s*\d{2}\s*日")
PAGE_LABEL_RE = re.compile(r"^(?:\d+(?:\.\d+)?-\d+|附录\s*[A-Z]-\d+)$")
LEADING_NUMBER_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*|[（(][一二三四五六七八九十0-9]+[)）]\s*|[（(][a-zA-Z]+[)）]\s*|[IVX]+\s*[)．.]?\s*)")
CITATION_RE = re.compile(r"【[^】]*】")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")
NUMERIC_VALUE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百千万两]+(?:\.\d+)?)"
    r"(?:\s*(?:-|~|—|至)\s*(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百千万两]+(?:\.\d+)?))?"
    r"\s*(?:个|天|日|个月|月|小时|分钟|年|周|次|架|人|本|页|条|%|％|米|千克|公斤|座|套|份|项|级|位|公里|海里|秒|分|台|门|副|枚|只)?"
)

logger = logging.getLogger("skill_run_eval")


@dataclass
class LeafNode:
    title: str
    node_id: str
    start_index: int
    end_index: int
    path_titles: list[str]
    order: int


@dataclass
class Candidate:
    question: str
    reference_answer: str
    batch: int | None
    chapter_title: str
    chapter_span: int
    leaf_title: str
    leaf_path: str
    page_start: int
    page_end: int
    kind: str
    score: float
    generation_order: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logging() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.FileHandler(LOG_PATH, encoding="utf-8", mode="w"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_structure() -> list[dict[str, Any]]:
    payload = json.loads(STRUCTURE_PATH.read_text(encoding="utf-8"))
    structure = payload["structure"]
    if not isinstance(structure, list):
        raise RuntimeError("structure json is malformed")
    return structure


def flatten_leaf_nodes(structure: list[dict[str, Any]]) -> list[LeafNode]:
    leaves: list[LeafNode] = []

    def walk(node: dict[str, Any], path: list[str], order_start: int) -> int:
        current_path = path + [str(node.get("title", "")).strip()]
        nodes = node.get("nodes") or []
        if not nodes:
            leaves.append(
                LeafNode(
                    title=str(node.get("title", "")).strip(),
                    node_id=str(node.get("node_id", "")).strip(),
                    start_index=int(node["start_index"]),
                    end_index=int(node["end_index"]),
                    path_titles=current_path,
                    order=len(leaves),
                )
            )
            return order_start + 1
        cursor = order_start
        for child in nodes:
            cursor = walk(child, current_path, cursor)
        return cursor

    for item in structure:
        walk(item, [], 0)
    return leaves


def extract_pages(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return pages


def normalize_text(text: str) -> str:
    text = CITATION_RE.sub("", text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。；：、！？])", r"\1", text)
    text = re.sub(r"([（(])\s+", r"\1", text)
    text = re.sub(r"\s+([）)])", r"\1", text)
    return text.strip()


def is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if DATE_HEADER_RE.match(stripped):
        return True
    if "版本：" in stripped:
        return True
    if PAGE_LABEL_RE.match(stripped):
        return True
    if stripped == "（此页有意留空白）":
        return True
    if stripped.startswith("【") and stripped.endswith("】") and len(stripped) < 40:
        return True
    return False


def is_heading_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^\d+(?:\.\d+)*\s*", stripped):
        return True
    if re.match(r"^[（(][一二三四五六七八九十0-9]+[)）]\s*", stripped):
        return True
    if re.match(r"^[（(][a-zA-Z]+[)）]\s*", stripped):
        return True
    if stripped.startswith("附录 "):
        return True
    if re.match(r"^[IVX]+\s*[)．.]?\s*", stripped):
        return True
    return False


def is_table_like(line: str) -> bool:
    compact = line.replace(" ", "")
    if len(compact) < 10:
        return False
    digit_count = sum(1 for ch in compact if ch.isdigit())
    unit_hits = sum(1 for token in ["个月", "天", "年", "小时", "分钟", "个", "副", "卷", "块", "条", "片", "套", "支", "米", "千克", "座位", "数量", "配备", "保存"] if token in compact)
    space_count = line.count(" ")
    return (digit_count >= 2 and unit_hits >= 1) or (space_count >= 4 and digit_count >= 1)


def clean_lines(page_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in page_text.splitlines():
        line = normalize_text(raw_line)
        if is_noise_line(line):
            continue
        if line in {"附录", "飞行运行", "运行政策", "运行管理机构及职责"}:
            continue
        lines.append(line)
    return lines


def split_blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    buf = ""
    for idx, line in enumerate(lines):
        if not line:
            continue
        if not buf:
            buf = line
            continue
        if is_heading_start(line):
            blocks.append(buf.strip())
            buf = line
            continue
        if is_table_like(buf) and is_table_like(line) and not buf.endswith(("。", "！", "？", "；")):
            blocks.append(buf.strip())
            buf = line
            continue
        if buf.endswith(("。", "！", "？", "；")) and not line.startswith(("(", "（")):
            blocks.append(buf.strip())
            buf = line
            continue
        buf += line
        if buf.endswith(("。", "！", "？", "；")):
            blocks.append(buf.strip())
            buf = ""
    if buf.strip():
        blocks.append(buf.strip())
    return blocks


def split_units(block: str) -> list[str]:
    block = normalize_text(block)
    if not block:
        return []
    parts = SENTENCE_SPLIT_RE.split(block)
    units = [normalize_text(part) for part in parts if normalize_text(part)]
    return units or [block]


def strip_leading_structure(text: str) -> str:
    text = normalize_text(text)
    text = LEADING_NUMBER_RE.sub("", text)
    return text.strip()


def extract_anchor(text: str, *, max_chars: int = 18) -> str:
    text = strip_leading_structure(text)
    text = re.sub(r"^[-－—–]+", "", text).strip()
    text = re.split(r"[。！？；:：]", text, maxsplit=1)[0]
    text = re.split(r"[，,]", text, maxsplit=1)[0]
    text = text.strip().strip("“”\"'《》")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,、 ")
    return text or "原文内容"


def shorten_answer(text: str, *, max_chars: int = 120) -> str:
    text = normalize_text(text)
    if not text:
        return text
    if len(text) <= max_chars:
        return text

    sentences = [segment.strip() for segment in SENTENCE_SPLIT_RE.split(text) if segment.strip()]
    if len(sentences) > 1:
        first_sentence = sentences[0]
        if len(first_sentence) >= 48:
            text = first_sentence
        else:
            text = "".join(sentences[:2]).strip()

    if len(text) > max_chars:
        clauses = [segment.strip() for segment in re.split(r"[，,；;]", text) if segment.strip()]
        if len(clauses) > 1:
            condensed = clauses[0]
            for clause in clauses[1:]:
                if len(condensed) >= max_chars:
                    break
                condensed += "，" + clause
                if len(condensed) >= int(max_chars * 0.85):
                    break
            text = condensed

    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,、；; ")
    return text


def answer_after_marker(text: str, marker: str) -> str:
    idx = text.find(marker)
    if idx < 0:
        return shorten_answer(text)
    return shorten_answer(text[idx + len(marker) :])


def extract_numeric_phrase(text: str) -> str:
    candidates = [match.group(0).strip() for match in NUMERIC_VALUE_RE.finditer(text)]
    candidates = [candidate for candidate in candidates if candidate and re.search(r"\d|[零一二三四五六七八九十百千万两]", candidate)]
    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def sentence_type(text: str) -> str:
    stripped = strip_leading_structure(text)
    if re.match(r"^[（(][一二三四五六七八九十0-9]+[)）]\s*", stripped):
        return "list"
    if re.match(r"^[（(][a-zA-Z]+[)）]\s*", stripped):
        return "list"
    if "是指" in stripped or "定义" in stripped:
        return "definition"
    if any(keyword in stripped for keyword in ["配备", "保存", "期限", "数量", "至少", "不少于", "小时", "分钟", "天", "年", "个月", "%", "％"]) and re.search(r"\d|[零一二三四五六七八九十百千万两]", stripped):
        return "numeric"
    if any(keyword in stripped for keyword in ["应", "必须", "不得", "禁止", "应当"]):
        return "requirement"
    if re.search(r"(?:是|为)", stripped):
        return "fact"
    return "generic"


def build_question_answer(
    unit: str,
    section_prefix: str,
    chapter_title: str,
    chapter_span: int,
    leaf_title: str,
    page_start: int,
    page_end: int,
    generation_order: int,
) -> Candidate | None:
    text = strip_leading_structure(unit)
    if not text or len(text) < 6:
        return None

    kind = sentence_type(text)
    question = ""
    answer = ""

    if kind == "definition":
        m = re.search(r"(?P<term>[^：:。！？；]{2,40})[:：]\s*是指(?P<rest>.+)", text)
        if m:
            term = extract_anchor(m.group("term"), max_chars=22)
            rest = shorten_answer(m.group("rest"))
            question = f"根据 {section_prefix}，{term} 是什么？"
            answer = f"是指{rest}"
        else:
            m = re.search(r"(?P<term>[^：:。！？；]{2,40})[:：]\s*(?P<rest>.+)", text)
            if m:
                term = extract_anchor(m.group("term"), max_chars=22)
                rest = shorten_answer(m.group("rest"))
                question = f"根据 {section_prefix}，{term} 是什么？"
                answer = rest

    if not question and kind == "list":
        m = re.match(r"^[（(](?P<num>[一二三四五六七八九十0-9a-zA-Z]+)[)）]\s*(?P<rest>.+)", text)
        if m:
            num = m.group("num")
            rest = shorten_answer(m.group("rest"))
            question = f"根据 {section_prefix}，第 {num} 项规定了什么？"
            answer = rest

    if not question and kind == "fact":
        m = re.search(r"(?P<subject>[^。！？；:：]{2,40}?)(?:是|为)(?P<value>[^。！？；:：]{1,120})", text)
        if m:
            subject = extract_anchor(m.group("subject"), max_chars=24)
            value = shorten_answer(m.group("value"))
            if any(token in subject for token in ["基地", "机场", "地点", "位置", "驻地"]):
                question = f"根据 {section_prefix}，{subject}在哪里？"
            elif any(token in subject for token in ["数量", "期限", "时间", "期限", "保存", "配备", "人数", "座位", "重量", "油量"]) or re.search(r"\d", value):
                question = f"根据 {section_prefix}，{subject}是多少？"
            else:
                question = f"根据 {section_prefix}，{subject}是什么？"
            answer = value

    if not question and kind == "requirement":
        modal_match = re.search(r"(应当|应|必须|不得|禁止)", text)
        if modal_match:
            subject = extract_anchor(text[: modal_match.start()], max_chars=24)
            if not subject:
                subject = "原文"
            question = f"根据 {section_prefix}，原文对“{subject}”有什么要求？"
            answer = shorten_answer(text[modal_match.start() :])

    if not question and kind == "numeric":
        subject = extract_anchor(text, max_chars=22)
        numeric_value = extract_numeric_phrase(text)
        if numeric_value:
            question = f"根据 {section_prefix}，原文中“{subject}”的具体数值是多少？"
            answer = numeric_value
        else:
            question = f"根据 {section_prefix}，原文中“{subject}”的完整表述是什么？"
            answer = shorten_answer(text)

    if not question:
        anchor = extract_anchor(text, max_chars=18)
        question = f"根据 {section_prefix}，原文中“{anchor}”的完整表述是什么？"
        answer = shorten_answer(text)

    if len(question) < 10 or len(answer) < 2:
        return None

    score = candidate_score(kind, question, answer, text)
    return Candidate(
        question=question,
        reference_answer=answer,
        batch=None,
        chapter_title=chapter_title,
        chapter_span=chapter_span,
        leaf_title=leaf_title,
        leaf_path=section_prefix,
        page_start=page_start,
        page_end=page_end,
        kind=kind,
        score=score,
        generation_order=generation_order,
    )


def is_low_value_leaf(leaf: LeafNode) -> bool:
    section_prefix = build_section_prefix(leaf.path_titles)
    if section_prefix.startswith("0."):
        return True
    low_value_tokens = ("封面", "批准", "前言", "改版记录", "临时修改", "有效页清单", "目录")
    return any(token in section_prefix for token in low_value_tokens)


def candidate_score(kind: str, question: str, answer: str, source_text: str) -> float:
    score = 0.0
    if kind == "definition":
        score += 5
    elif kind == "fact":
        score += 4
    elif kind == "requirement":
        score += 4.5
    elif kind == "list":
        score += 4.2
    elif kind == "numeric":
        score += 4.8
    else:
        score += 2
    if len(answer) <= 120:
        score += 1.5
    if len(question) <= 120:
        score += 0.5
    if re.search(r"\d", source_text):
        score += 0.5
    if any(token in source_text for token in ["表", "图", "附录", "保存", "配备", "风险", "计划", "最低标准", "程序"]):
        score += 0.5
    return score


def select_leaf_quota(page_count: int) -> int:
    if page_count <= 1:
        return 1
    if page_count <= 8:
        return 2
    if page_count <= 20:
        return 3
    return 4


def build_section_prefix(path_titles: list[str]) -> str:
    pieces = [title.strip() for title in path_titles if title.strip()]
    return " ".join(pieces)


def collect_leaf_candidates(
    leaf: LeafNode,
    page_texts: list[str],
    chapter_title: str,
    chapter_span: int,
    generation_cursor: int,
) -> tuple[list[Candidate], int]:
    section_prefix = build_section_prefix(leaf.path_titles)
    raw_section_text = "\n".join(page_texts[leaf.start_index - 1 : leaf.end_index])
    lines = clean_lines(raw_section_text)
    blocks = split_blocks(lines)
    candidates: list[Candidate] = []
    cursor = generation_cursor
    for block in blocks:
        for unit in split_units(block):
            candidate = build_question_answer(
                unit,
                section_prefix,
                chapter_title,
                chapter_span,
                leaf.title,
                leaf.start_index,
                leaf.end_index,
                cursor,
            )
            cursor += 1
            if candidate is not None:
                candidates.append(candidate)
    # Fallback for blank-ish leaves.
    if not candidates:
        summary_unit = f"{leaf.title}"
        candidate = build_question_answer(
            summary_unit,
            section_prefix,
            chapter_title,
            chapter_span,
            leaf.title,
            leaf.start_index,
            leaf.end_index,
            cursor,
        )
        cursor += 1
        if candidate is not None:
            candidates.append(candidate)
    return candidates, cursor


def build_curated_candidates(page_texts: list[str]) -> list[Candidate]:
    curated: list[Candidate] = []
    cursor = 100000
    current_chapter_title = ""
    current_chapter_span = 0

    def set_chapter(title: str, span: int) -> None:
        nonlocal current_chapter_title, current_chapter_span
        current_chapter_title = title
        current_chapter_span = span

    def add(question: str, answer: str, leaf_title: str, section_prefix: str, page_start: int, page_end: int, kind: str, score: float) -> None:
        nonlocal cursor
        curated.append(
            Candidate(
                question=question,
                reference_answer=answer,
                batch=None,
                chapter_title=current_chapter_title,
                chapter_span=current_chapter_span,
                leaf_title=leaf_title,
                leaf_path=section_prefix,
                page_start=page_start,
                page_end=page_end,
                kind=kind,
                score=score,
                generation_order=cursor,
            )
        )
        cursor += 1

    # Chapter 1.5 record retention table
    set_chapter("1.0 记录管理", 24)
    section = "1.0 记录管理 1.5 运行记录管理"
    add(
        f"根据 {section}，AOC 与飞机的语音通信记录保存多久？",
        "30 天",
        "1.5 运行记录管理",
        section,
        49,
        52,
        "numeric",
        9.5,
    )
    add(
        f"根据 {section}，地空数据链通信记录保存多久？",
        "3 个月",
        "1.5 运行记录管理",
        section,
        49,
        52,
        "numeric",
        9.5,
    )
    add(
        f"根据 {section}，签派放行资料包保存多久？",
        "12 个月",
        "1.5 运行记录管理",
        section,
        49,
        52,
        "numeric",
        9.5,
    )
    add(
        f"根据 {section}，公司级手册修订、批准和发放记录保存多久？",
        "3 年",
        "1.5 运行记录管理",
        section,
        49,
        52,
        "numeric",
        9.5,
    )

    # Appendix I glossary
    set_chapter("附录", 138)
    section = "附录 附录I ACARS 简字简语表"
    add(
        f"根据 {section}，WX in DEST and ALT 表示什么？",
        "落地机场和备降机场天气",
        "附录I ACARS 简字简语表",
        section,
        1275,
        1284,
        "definition",
        10.2,
    )
    add(
        f"根据 {section}，NEXT PLAN 表示什么？",
        "机组后续飞行计划、机号、油量、飞机预达本场时间",
        "附录I ACARS 简字简语表",
        section,
        1275,
        1284,
        "definition",
        10.2,
    )
    add(
        f"根据 {section}，ACARS 是什么的缩写？",
        "Aircraft Communication Adressing and Reporting System 陆空数据通信系统",
        "附录I ACARS 简字简语表",
        section,
        1275,
        1284,
        "definition",
        10.2,
    )
    add(
        f"根据 {section}，ABEAM 的英文解释是什么？",
        "an aircraft is abeam a point when that point is at ninety degrees left or right of the aircraft's track, but term usually used to indicate a general position rather than a specific point. 正切",
        "附录I ACARS 简字简语表",
        section,
        1275,
        1284,
        "definition",
        10.2,
    )

    # Appendix J kits
    set_chapter("附录", 138)
    section = "附录 附录J 急救箱、应急医疗箱和卫生防疫包"
    add(
        f"根据 {section}，旅客座位数 100（含）以下时急救箱配备数量是多少？",
        "1",
        "附录J 急救箱、应急医疗箱和卫生防疫包",
        section,
        1285,
        1288,
        "numeric",
        10,
    )
    add(
        f"根据 {section}，旅客座位数 301-400 时急救箱配备数量是多少？",
        "4",
        "附录J 急救箱、应急医疗箱和卫生防疫包",
        section,
        1285,
        1288,
        "numeric",
        10,
    )
    add(
        f"根据 {section}，应急医疗箱的存放要求是什么？",
        "防尘、防潮、耐挤压，避免高温或低温环境。",
        "附录J 急救箱、应急医疗箱和卫生防疫包",
        section,
        1285,
        1288,
        "fact",
        10,
    )
    add(
        f"根据 {section}，每只应急医疗箱内至少要配备哪些药品和物品？",
        "血压计、听诊器、口咽气道、静脉止血带、脐带夹、医用口罩、医用橡胶手套、皮肤消毒剂、消毒棉签、体温计、注射器、0.9%氯化钠、1:1000 肾上腺素单次用量安瓿、盐酸苯海拉明注射液、硝酸甘油片、醋酸基水杨酸（阿司匹林）口服片、应急医疗箱手册和紧急医学事件报告单。",
        "附录J 急救箱、应急医疗箱和卫生防疫包",
        section,
        1285,
        1288,
        "definition",
        9.8,
    )
    add(
        f"根据 {section}，每只卫生防疫包至少配备哪些物品？",
        "消毒凝固剂、表面清理消毒片、皮肤消毒擦拭纸巾、医用口罩、眼罩、医用橡胶手套、防渗透橡胶（塑料）围裙、吸水纸（毛）巾、便携拾物铲、生物有害物专用垃圾袋、物品清单和使用说明书、紧急医学事件报告单。",
        "附录J 急救箱、应急医疗箱和卫生防疫包",
        section,
        1285,
        1288,
        "definition",
        9.8,
    )

    # Appendix K
    set_chapter("附录", 138)
    section = "附录 附录K 运行飞行计划（OFP）、签派单模板及中文释义"
    add(
        f"根据 {section}，普通飞行计划示例中的起飞机场代码是什么？",
        "ZGSZ",
        "附录K 运行飞行计划（OFP）、签派单模板及中文释义",
        section,
        1289,
        1324,
        "fact",
        9.6,
    )
    add(
        f"根据 {section}，普通飞行计划示例中的目的地机场代码是什么？",
        "ZBAA",
        "附录K 运行飞行计划（OFP）、签派单模板及中文释义",
        section,
        1289,
        1324,
        "fact",
        9.6,
    )
    add(
        f"根据 {section}，普通飞行计划示例中的航班号是什么？",
        "ZH9959",
        "附录K 运行飞行计划（OFP）、签派单模板及中文释义",
        section,
        1289,
        1324,
        "fact",
        9.6,
    )
    add(
        f"根据 {section}，普通飞行计划示例中呼号是什么？",
        "ZH9959",
        "附录K 运行飞行计划（OFP）、签派单模板及中文释义",
        section,
        1289,
        1324,
        "fact",
        9.6,
    )
    add(
        f"根据 {section}，ETOPS 二次放行飞行计划示例按照多少分钟规则制作？",
        "120 分钟",
        "附录K 运行飞行计划（OFP）、签派单模板及中文释义",
        section,
        1289,
        1324,
        "numeric",
        10,
    )

    # Appendix L
    set_chapter("附录", 138)
    section = "附录 附录L 新开/复航国际航线风险评估表和国际运行保障能力评估表"
    add(
        f"根据 {section}，新开/复航国际航线风险评估表将运行过程划分为哪六个阶段？",
        "运行批准、运行保障、航路运行、进场着陆、地面运行、起飞离场。",
        "附录L 新开/复航国际航线风险评估表和国际运行保障能力评估表",
        section,
        1325,
        1340,
        "definition",
        10,
    )
    add(
        f"根据 {section}，国际运行保障能力评估表包含哪五个评估类别？",
        "国际运行能力成熟度、机务维护保障能力成熟度、飞行机组保障能力、地面代理保障情况、运行控制保障能力成熟度。",
        "附录L 新开/复航国际航线风险评估表和国际运行保障能力评估表",
        section,
        1325,
        1340,
        "definition",
        10,
    )
    add(
        f"根据 {section}，国际运行保障能力评估表如何量化评估公司的国际运行保障能力？",
        "通过对运行资质时长、航材与工装配备、机组英语资质比例、地面服务协议签署情况、运行监控体系及通信能力等指标进行打分。",
        "附录L 新开/复航国际航线风险评估表和国际运行保障能力评估表",
        section,
        1325,
        1340,
        "definition",
        9.8,
    )

    return curated


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str]] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        key = (
            re.sub(r"\s+", " ", candidate.question.strip()),
            re.sub(r"\s+", " ", candidate.reference_answer.strip()),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def generate_question_pool(structure: list[dict[str, Any]], page_texts: list[str], limit: int | None) -> list[dict[str, Any]]:
    leaves = flatten_leaf_nodes(structure)
    chapter_meta = {
        str(item.get("title", "")).strip(): int(item["end_index"]) - int(item["start_index"]) + 1
        for item in structure
    }
    all_candidates: list[Candidate] = []
    generation_cursor = 0
    leaf_meta: dict[str, int] = {}

    logger.info("Extracting candidates from %d leaf sections", len(leaves))
    for leaf in leaves:
        if is_low_value_leaf(leaf):
            continue
        chapter_title = leaf.path_titles[0] if leaf.path_titles else leaf.title
        chapter_span = chapter_meta.get(chapter_title, leaf.end_index - leaf.start_index + 1)
        leaf_candidates, generation_cursor = collect_leaf_candidates(
            leaf,
            page_texts,
            chapter_title,
            chapter_span,
            generation_cursor,
        )
        leaf_candidates = dedupe_candidates(leaf_candidates)
        leaf_meta[build_section_prefix(leaf.path_titles)] = leaf.end_index - leaf.start_index + 1
        all_candidates.extend(leaf_candidates)

    curated = build_curated_candidates(page_texts)
    all_candidates.extend(curated)
    all_candidates = dedupe_candidates(all_candidates)
    all_candidates.sort(key=lambda c: (-c.score, c.generation_order))

    # Keep a diverse set by leaf before the final top-k trim.
    grouped: dict[str, list[Candidate]] = {}
    for candidate in all_candidates:
        grouped.setdefault(candidate.leaf_path, []).append(candidate)

    selected: list[Candidate] = []
    leftovers: list[Candidate] = []
    for leaf_path, group in grouped.items():
        group.sort(key=lambda c: (-c.score, c.generation_order))
        page_count = leaf_meta.get(leaf_path, group[0].page_end - group[0].page_start + 1)
        quota = select_leaf_quota(page_count)
        selected.extend(group[:quota])
        leftovers.extend(group[quota:])

    if len(selected) < TARGET_QUESTION_COUNT:
        remaining = [candidate for candidate in leftovers if candidate not in selected]
        remaining.sort(key=lambda c: (-c.score, c.generation_order))
        selected.extend(remaining[: TARGET_QUESTION_COUNT - len(selected)])
    if len(selected) > TARGET_QUESTION_COUNT:
        selected = selected[:TARGET_QUESTION_COUNT]

    selected.sort(key=lambda c: c.generation_order)
    if limit is not None:
        selected = selected[:limit]

    questions: list[dict[str, Any]] = []
    batch_counts = {batch: 0 for batch in range(1, BATCH_COUNT + 1)}
    for idx, candidate in enumerate(selected, start=1):
        batch = ((idx - 1) % BATCH_COUNT) + 1
        batch_counts[batch] += 1
        page_span = candidate.page_end - candidate.page_start + 1
        questions.append(
            {
                "id": idx,
                "batch": batch,
                "question": candidate.question,
                "reference_answer": candidate.reference_answer,
                "chapter_title": candidate.chapter_title,
                "chapter_span": candidate.chapter_span,
                "leaf_title": candidate.leaf_title,
                "leaf_path": candidate.leaf_path,
                "page_start": candidate.page_start,
                "page_end": candidate.page_end,
                "page_span": page_span,
                "kind": candidate.kind,
                "candidate_score": round(candidate.score, 3),
            }
        )

    logger.info("Generated %d questions; batch counts: %s", len(questions), batch_counts)
    return questions


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 180,
) -> tuple[int, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        try:
            return status, json.loads(body.decode("utf-8"))
        except Exception:
            return status, {"raw": body.decode("utf-8", errors="replace")}
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc)) from exc

    if not body:
        return status, None
    try:
        return status, json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"raw": body.decode("utf-8", errors="replace")}


def call_skill_run(question: dict[str, Any]) -> dict[str, Any]:
    chapter_span = int(question.get("chapter_span") or 0)
    selection_mode = "lexical_fallback" if chapter_span and chapter_span <= 24 else "outline_llm"
    payload = {
        "question": question["question"],
        "conversation_config": {
            "include_history": False,
            "query_rewrite_with_history": False,
        },
        "retrieval_config": {
            "selection_mode": selection_mode,
            "top_k": 1,
            "rerank_mode": "off",
            "max_context_pages": 40,
            "max_context_tokens": 12000,
        },
        "generation_config": {"temperature": 0, "max_tokens": 256},
    }
    request_time = utc_now_iso()
    started = time.perf_counter()
    status_code = 0
    raw_response: Any = None
    error: str | None = None
    try:
        status_code, raw_response = request_json(
            "POST",
            SKILL_RUN_URL,
            headers={"X-API-Key": SKILL_API_KEY},
            payload=payload,
            timeout=300,
        )
    except Exception as exc:
        error = str(exc)
        raw_response = None
    response_time = utc_now_iso()
    latency_ms = int((time.perf_counter() - started) * 1000)

    answer_text = ""
    citations: list[Any] = []
    if isinstance(raw_response, dict):
        answer_text = str(raw_response.get("answer_text") or raw_response.get("answer") or "")
        citations = raw_response.get("citations") or []
        if status_code and status_code >= 400:
            error = error or str(raw_response.get("detail") or raw_response.get("error") or f"HTTP {status_code}")
    else:
        if status_code and status_code >= 400:
            error = error or f"HTTP {status_code}"

    return {
        "question_id": question["id"],
        "batch": question["batch"],
        "question": question["question"],
        "request_time": request_time,
        "response_time": response_time,
        "latency_ms": latency_ms,
        "raw_response": raw_response,
        "answer_text": answer_text,
        "citations": citations,
        "status_code": status_code,
        "error": error,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def score_single_answer(row: dict[str, Any]) -> dict[str, Any]:
    citations = row.get("citations") or []
    compact_citations = []
    if isinstance(citations, list):
        for citation in citations:
            if isinstance(citation, dict):
                compact_citations.append(
                    {
                        "title": citation.get("title"),
                        "page_start": citation.get("page_start"),
                        "page_end": citation.get("page_end"),
                        "document_label": citation.get("document_label"),
                    }
                )
    prompt = (
        "你是一个专业的RAG系统评测专家。\n"
        "请根据以下信息对回答进行评分（1-5分制）：\n\n"
        f"【问题】{row['question']}\n"
        f"【答案摘要】{row['reference_answer']}\n"
        f"【系统回答】{row.get('answer_text') or ''}\n"
        f"【引用来源】{json.dumps(compact_citations, ensure_ascii=False)}\n\n"
        "评分标准：\n"
        "- 5分：内容正确、引用真实、结构清晰，没有任何编造\n"
        "- 4分：内容基本正确，轻微遗漏，无明显错误\n"
        "- 3分：内容部分正确，有轻微偏差或冗余\n"
        "- 2分：内容有明显错误，或引用不当\n"
        "- 1分：内容严重错误、大量编造或完全无关\n\n"
        "请严格按以下 JSON 格式输出，不要输出其他内容：\n"
        "{\n"
        '  "score": <1-5的整数>,\n'
        '  "content_correct": <true/false>,\n'
        '  "citation_correct": <true/false>,\n'
        '  "structure_correct": <true/false>,\n'
        '  "reason": "<简要评分理由，不超过100字>"\n'
        "}\n"
    )
    payload = {
        "model": SCORING_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }

    started = time.perf_counter()
    status_code, response = request_json(
        "POST",
        f"{SCORING_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {SCORING_API_KEY}"},
        payload=payload,
        timeout=240,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    content = ""
    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices and isinstance(choices, list):
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            if isinstance(message, dict):
                content = str(message.get("content") or "")

    try:
        parsed = extract_json_object(content)
    except Exception as exc:
        parsed = {
            "score": None,
            "content_correct": False,
            "citation_correct": False,
            "structure_correct": False,
            "reason": f"评分解析失败: {exc}",
        }

    score = parsed.get("score")
    if isinstance(score, str) and score.isdigit():
        score = int(score)
    if not isinstance(score, int):
        score = None
    return {
        "question_id": row["question_id"],
        "batch": row["batch"],
        "score": score,
        "content_correct": bool(parsed.get("content_correct")),
        "citation_correct": bool(parsed.get("citation_correct")),
        "structure_correct": bool(parsed.get("structure_correct")),
        "score_reason": str(parsed.get("reason") or parsed.get("score_reason") or ""),
        "score_status_code": status_code,
        "score_latency_ms": latency_ms,
        "score_raw_response": response,
    }


def run_with_retries(fn, *, retries: int = 2, base_sleep: float = 1.5):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(base_sleep * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def load_existing_records(path: Path, key: str) -> dict[int, dict[str, Any]]:
    payload = read_json(path)
    if not payload:
        return {}
    if not isinstance(payload, list):
        return {}
    records: dict[int, dict[str, Any]] = {}
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get(key), int):
            records[int(item[key])] = item
    return records


def is_valid_raw_record(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    status_code = record.get("status_code")
    if isinstance(status_code, int) and status_code != 0:
        return True
    return record.get("raw_response") is not None


def is_valid_eval_record(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    score_status_code = record.get("score_status_code")
    score = record.get("score")
    if isinstance(score_status_code, int) and score_status_code != 0:
        return True
    return record.get("score_raw_response") is not None or score is not None


def write_incremental(path: Path, records: list[dict[str, Any]]) -> None:
    write_json(path, records)


def process_questions(questions: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    existing = {
        question_id: record
        for question_id, record in load_existing_records(RAW_RESULTS_PATH, "question_id").items()
        if is_valid_raw_record(record)
    }
    results: dict[int, dict[str, Any]] = dict(existing)
    pending = [q for q in questions if q["id"] not in existing]
    logger.info("Skill run: %d existing, %d pending", len(existing), len(pending))
    if not pending:
        return [results[q["id"]] for q in questions if q["id"] in results]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(run_with_retries, lambda q=q: call_skill_run(q)): q
            for q in pending
        }
        completed = 0
        for future in as_completed(future_map):
            q = future_map[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {
                    "question_id": q["id"],
                    "batch": q["batch"],
                    "question": q["question"],
                    "request_time": utc_now_iso(),
                    "response_time": utc_now_iso(),
                    "latency_ms": 0,
                    "raw_response": None,
                    "answer_text": "",
                    "citations": [],
                    "status_code": 0,
                    "error": str(exc),
                }
            results[q["id"]] = record
            completed += 1
            if completed % 10 == 0:
                write_incremental(RAW_RESULTS_PATH, [results[q2["id"]] for q2 in questions if q2["id"] in results])
                logger.info("Skill run progress: %d/%d", len(results), len(questions))
    ordered = [results[q["id"]] for q in questions if q["id"] in results]
    write_incremental(RAW_RESULTS_PATH, ordered)
    return ordered


def process_scoring(questions: list[dict[str, Any]], raw_results: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    raw_by_id = {row["question_id"]: row for row in raw_results}
    existing = {
        question_id: record
        for question_id, record in load_existing_records(EVALUATION_RESULTS_PATH, "question_id").items()
        if is_valid_eval_record(record)
    }
    results: dict[int, dict[str, Any]] = dict(existing)
    pending = [q for q in questions if q["id"] not in existing]
    logger.info("Scoring: %d existing, %d pending", len(existing), len(pending))
    if not pending:
        return [results[q["id"]] for q in questions if q["id"] in results]

    def task(question_row: dict[str, Any]) -> dict[str, Any]:
        raw_row = raw_by_id.get(question_row["id"], {})
        merged = {**question_row, **raw_row}
        return score_single_answer(merged)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(run_with_retries, lambda q=q: task(q)): q
            for q in pending
        }
        completed = 0
        for future in as_completed(future_map):
            q = future_map[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {
                    "question_id": q["id"],
                    "batch": q["batch"],
                    "score": None,
                    "content_correct": False,
                    "citation_correct": False,
                    "structure_correct": False,
                    "score_reason": str(exc),
                    "score_status_code": 0,
                    "score_latency_ms": 0,
                    "score_raw_response": None,
                }
            results[q["id"]] = record
            completed += 1
            if completed % 10 == 0:
                write_incremental(EVALUATION_RESULTS_PATH, [results[q2["id"]] for q2 in questions if q2["id"] in results])
                logger.info("Scoring progress: %d/%d", len(results), len(questions))
    ordered = [results[q["id"]] for q in questions if q["id"] in results]
    write_incremental(EVALUATION_RESULTS_PATH, ordered)
    return ordered


def merge_results(
    questions: list[dict[str, Any]],
    raw_results: list[dict[str, Any]],
    eval_results: list[dict[str, Any]],
) -> pd.DataFrame:
    q_df = pd.DataFrame(questions)
    r_df = pd.DataFrame(raw_results).drop(columns=["batch", "question"], errors="ignore")
    e_df = pd.DataFrame(eval_results).drop(columns=["batch"], errors="ignore")
    merged = q_df.rename(columns={"id": "question_id"}).merge(r_df, on="question_id", how="left")
    merged = merged.merge(e_df, on="question_id", how="left", suffixes=("", "_eval"))
    merged["latency_ms"] = merged["latency_ms"].fillna(0).astype(int)
    merged["status_code"] = merged["status_code"].fillna(0).astype(int)
    merged["score"] = merged["score"].astype("Int64")
    merged["content_correct"] = merged["content_correct"].fillna(False).astype(bool)
    merged["citation_correct"] = merged["citation_correct"].fillna(False).astype(bool)
    merged["structure_correct"] = merged["structure_correct"].fillna(False).astype(bool)
    merged["citations"] = merged["citations"].apply(lambda v: json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v)
    merged["raw_response"] = merged["raw_response"].apply(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
    merged["score_raw_response"] = merged["score_raw_response"].apply(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
    ordered_columns = [
        "question_id",
        "batch",
        "question",
        "reference_answer",
        "answer_text",
        "citations",
        "score",
        "content_correct",
        "citation_correct",
        "structure_correct",
        "score_reason",
        "latency_ms",
        "request_time",
        "response_time",
        "status_code",
        "error",
    ]
    for column in ordered_columns:
        if column not in merged.columns:
            merged[column] = None
    merged = merged[ordered_columns]
    return merged.sort_values(["batch", "question_id"], kind="stable").reset_index(drop=True)


def build_stats_sheet(df: pd.DataFrame) -> pd.DataFrame:
    numeric_score = pd.to_numeric(df["score"], errors="coerce")
    batch_groups = df.groupby("batch", dropna=False)
    rows: list[dict[str, Any]] = []
    for batch, group in batch_groups:
        score_series = pd.to_numeric(group["score"], errors="coerce")
        latency_series = pd.to_numeric(group["latency_ms"], errors="coerce")
        score_mean = score_series.mean(skipna=True)
        score_max = score_series.max(skipna=True)
        score_min = score_series.min(skipna=True)
        latency_mean = latency_series.mean(skipna=True)
        latency_p90 = latency_series.quantile(0.9)
        latency_p99 = latency_series.quantile(0.99)
        rows.append(
            {
                "batch": int(batch),
                "count": int(len(group)),
                "avg_score": round(float(score_mean), 3) if pd.notna(score_mean) else None,
                "max_score": float(score_max) if pd.notna(score_max) else None,
                "min_score": float(score_min) if pd.notna(score_min) else None,
                "avg_latency_ms": round(float(latency_mean), 2) if pd.notna(latency_mean) else None,
                "p90_latency_ms": round(float(latency_p90), 2) if pd.notna(latency_p90) else None,
                "p99_latency_ms": round(float(latency_p99), 2) if pd.notna(latency_p99) else None,
                "content_correct_rate": round(float(group["content_correct"].mean() * 100), 2),
                "citation_correct_rate": round(float(group["citation_correct"].mean() * 100), 2),
                "structure_correct_rate": round(float(group["structure_correct"].mean() * 100), 2),
                "pass_rate_score_ge_4": round(float((score_series >= 4).mean() * 100), 2) if score_series.notna().any() else None,
                "error_count": int(group["error"].fillna("").astype(str).str.strip().ne("").sum()),
            }
        )
    overall_latency = pd.to_numeric(df["latency_ms"], errors="coerce")
    score_series = pd.to_numeric(df["score"], errors="coerce")
    score_mean = score_series.mean(skipna=True)
    score_max = score_series.max(skipna=True)
    score_min = score_series.min(skipna=True)
    latency_mean = overall_latency.mean(skipna=True)
    latency_p90 = overall_latency.quantile(0.9)
    latency_p99 = overall_latency.quantile(0.99)
    rows.append(
        {
            "batch": "overall",
            "count": int(len(df)),
            "avg_score": round(float(score_mean), 3) if pd.notna(score_mean) else None,
            "max_score": float(score_max) if pd.notna(score_max) else None,
            "min_score": float(score_min) if pd.notna(score_min) else None,
            "avg_latency_ms": round(float(latency_mean), 2) if pd.notna(latency_mean) else None,
            "p90_latency_ms": round(float(latency_p90), 2) if pd.notna(latency_p90) else None,
            "p99_latency_ms": round(float(latency_p99), 2) if pd.notna(latency_p99) else None,
            "content_correct_rate": round(float(df["content_correct"].mean() * 100), 2),
            "citation_correct_rate": round(float(df["citation_correct"].mean() * 100), 2),
            "structure_correct_rate": round(float(df["structure_correct"].mean() * 100), 2),
            "pass_rate_score_ge_4": round(float((score_series >= 4).mean() * 100), 2) if score_series.notna().any() else None,
            "error_count": int(df["error"].fillna("").astype(str).str.strip().ne("").sum()),
        }
    )
    return pd.DataFrame(rows)


def write_excel_report(df: pd.DataFrame, stats_df: pd.DataFrame) -> None:
    with pd.ExcelWriter(REPORT_PATH, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="detail", index=False)
        stats_df.to_excel(writer, sheet_name="stats", index=False)

        detail_ws = writer.sheets["detail"]
        stats_ws = writer.sheets["stats"]
        for ws in [detail_ws, stats_ws]:
            for column_cells in ws.columns:
                cells = list(column_cells)
                values = [cell.value for cell in cells[: min(len(cells), 200)] if cell.value is not None]
                width = max([len(str(v)) for v in values] + [10])
                ws.column_dimensions[cells[0].column_letter].width = min(width + 2, 60)


def ensure_target_count(questions: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    if len(questions) > target:
        return questions[:target]
    if len(questions) < target:
        raise RuntimeError(f"Question generation produced only {len(questions)} questions; expected {target}.")
    return questions


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill Run evaluation harness")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of questions to process")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent worker count for skill runs")
    parser.add_argument("--score-workers", type=int, default=DEFAULT_SCORE_WORKERS, help="Concurrent worker count for scoring")
    parser.add_argument("--questions-only", action="store_true", help="Only generate questions.json")
    parser.add_argument("--run-only", action="store_true", help="Only run the Skill Run API using existing questions.json")
    parser.add_argument("--score-only", action="store_true", help="Only score existing raw_results.json")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    setup_logging()

    if not PDF_PATH.exists():
        raise SystemExit(f"PDF not found: {PDF_PATH}")
    if not STRUCTURE_PATH.exists():
        raise SystemExit(f"Structure file not found: {STRUCTURE_PATH}")

    structure = load_structure()
    page_texts = extract_pages(PDF_PATH)
    logger.info("Loaded %d PDF pages", len(page_texts))

    questions = read_json(QUESTIONS_PATH)
    regenerate_questions = not isinstance(questions, list) or not questions
    if isinstance(questions, list) and questions:
        if (
            not isinstance(questions[0], dict)
            or "page_span" not in questions[0]
            or "leaf_path" not in questions[0]
            or "chapter_span" not in questions[0]
            or "chapter_title" not in questions[0]
        ):
            regenerate_questions = True
        if args.limit is None and len(questions) != TARGET_QUESTION_COUNT:
            regenerate_questions = True
        if args.limit is not None and len(questions) < args.limit:
            regenerate_questions = True
    if regenerate_questions:
        questions = generate_question_pool(structure, page_texts, args.limit)
        if args.limit is None:
            questions = ensure_target_count(questions, TARGET_QUESTION_COUNT)
        write_json(QUESTIONS_PATH, questions)
    else:
        logger.info("Reusing existing questions.json with %d questions", len(questions))
        if args.limit is not None:
            questions = questions[: args.limit]

    if args.questions_only:
        logger.info("Question generation complete; questions.json written.")
        return 0

    if not args.score_only:
        if not SKILL_RUN_URL or not SKILL_API_KEY:
            raise SystemExit("Set SKILL_RUN_URL and SKILL_RUN_API_KEY before running Skill Run calls.")
        raw_results = process_questions(questions, args.workers)
    else:
        raw_results = read_json(RAW_RESULTS_PATH) or []
        if not isinstance(raw_results, list):
            raise SystemExit("raw_results.json is malformed")
        logger.info("Reusing existing raw_results.json with %d rows", len(raw_results))

    if args.run_only:
        logger.info("Skill Run stage complete; skipping scoring.")
        return 0

    if not SCORING_API_KEY:
        raise SystemExit("Set SCORING_API_KEY before running scoring.")
    eval_results = process_scoring(questions, raw_results, args.score_workers)
    merged = merge_results(questions, raw_results, eval_results)
    stats_df = build_stats_sheet(merged)
    write_excel_report(merged, stats_df)

    logger.info("Wrote report to %s", REPORT_PATH)
    logger.info("Done. questions=%d raw=%d eval=%d", len(questions), len(raw_results), len(eval_results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
