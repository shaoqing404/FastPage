#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
QUESTION_SOURCE_PATH = RESULTS_DIR / "questions.json"
QUESTION_OUTPUT_PATH = RESULTS_DIR / "b4_4_skill_eval_questions.json"
QUESTION_BY_WORKER_DIR = RESULTS_DIR / "b4_4_skill_eval_questions_by_worker"
RUN_OUTPUT_FAST_PATH = RESULTS_DIR / "b4_4_skill_run_fast.jsonl"
RUN_OUTPUT_DEEP_PATH = RESULTS_DIR / "b4_4_skill_run_deep_research.jsonl"
RUN_OUTPUT_OPENAI_COMPAT_PATH = RESULTS_DIR / "b4_4_skill_run_openai_compat.jsonl"
JUDGMENT_OUTPUT_PATH = RESULTS_DIR / "b4_4_skill_eval_judgments.jsonl"
LATENCY_SUMMARY_PATH = RESULTS_DIR / "b4_4_skill_latency_summary.json"
LATENCY_REPORT_PATH = RESULTS_DIR / "b4_4_skill_latency_report.md"
EVAL_SUMMARY_PATH = RESULTS_DIR / "b4_4_skill_eval_summary.json"
EVAL_REPORT_PATH = RESULTS_DIR / "b4_4_skill_eval_report.md"
RUN_WORKER_ROOT = RESULTS_DIR / "b4_4_skill_run_workers"

DEFAULT_API_BASE = "http://localhost:8000"
DEFAULT_SKILL_ID = "380b5ee0-6e66-46a8-8355-4b3fbd3a5d6b"
DEFAULT_EVAL_MODEL = "deepseek-v4-pro"
DEFAULT_EVAL_API_BASE = "https://api.deepseek.com"
DEFAULT_WORKER_COUNT = 5
WORKER_BATCH_SIZE = 100

FORBIDDEN_QUESTION_PATTERNS = [
    re.compile(r"^\s*\d+(?:\.\d+)+"),
    re.compile(r"第\s*\d+\s*章"),
    re.compile(r"第\s*\d+\s*页"),
    re.compile(r"node[_-]?id", re.I),
]

LEADING_TITLE_NUMBER_RE = re.compile(r"^\s*(?:第\s*)?(?:\d+(?:\.\d+)*|[IVX]+|[一二三四五六七八九十]+)\s*[-－—.]?\s*")
SECTION_REF_RE = re.compile(r"(?<!\d)\d+(?:\s*\.\s*\d+){1,4}(?:\s*-\s*\d+)?\s*(?=[一-龥A-Za-z])")
ANSWER_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")
ANSWER_CLAUSE_SPLIT_RE = re.compile(r"[，,；;]")

EXPECTED_ANSWER_OVERRIDES: dict[int, str] = {
    8: "B737NG 机型配《B737NG 最低设备清单和外形缺损清单》，B737MAX 机型配《B737MAX 最低设备清单和外形缺损清单》。",
    9: "B737MAX 机型配《B737MAX 最低设备清单和外形缺损清单》。",
    10: "B737NG 机型配英文版 MEL&CDL，B737MAX 机型 MEL&CDL 为中英文对照版。",
    12: "A320 机型配备《A320 正常检查单》。",
    13: "A321 机型配备《A321 正常检查单》。",
    16: "签派放行单由运行管理部保存 3 个月，电子版。",
    17: "疲劳管理基础数据由飞行部/客舱服务部/空中保卫支队保存 24 个月，电子版。",
    18: "机组成员的疲劳风险报告由飞行部/客舱服务部/空中保卫支队保存 24 个月，电子版。",
    24: "若局方决定重新进行全面检查，公司应在前述 5 个工作日内保持可随时接受检查的状态。",
    31: "机组落地后归还的飞行资料袋相关资料由运行管理部检查归档，至少保存 3 个月。",
    34: "除列明设备外，一般不得在运行飞机上使用 PED；低能见度和电磁干扰时需关闭并恢复使用，带发射功能设备和充电宝全程禁用。",
    35: "营销委应于开航前 60 天通报标准管理部。",
    47: "机长应确认特许人员证件齐全、按指示就座、可到达驾驶舱和出口，并在起飞前接受禁烟和系安全带的口头简介。",
    48: "无客舱乘务组运行时，如机上载有特许载运人员，飞行机组还应负责安全广播并完成客舱准备、滑梯预位/解除预位、颠簸及紧急撤离等程序。",
    53: "公司所有员工在航空器活动区域、候机楼旅客活动区域、旅客通道、摆渡车和机组车内禁止吸烟。",
    99: "机长若无该机场仪表进近经历，应满足规定的任一条件，否则按“机长的新机场运行标准”实施运行。",
    100: "所有机组人员执行飞行任务时应穿统一飞行制服、按职位佩戴肩章、保持仪容整洁并遵守公众场合行为和禁酒要求。",
    105: "课程设计和教学过程遵循成人学习原理，强调实际体验-观察反思-总结规律-实践应用。",
    108: "加/改装机上设备应依据 SB/SL、CAD、STC/VSTC、公司运行需要和中国民航规章要求。",
    136: "使用着陆最低标准时，应遵守能见度和跑道视程限制；低于 1,200 米时除非具备更低标准资格，否则不得实施或开始仪表进近。",
    164: "特定一发失效应急程序可按咨询通告执行，但需向局方提供相应书面证明材料。",
    178: "使用观察员座位的非机组人员应接受驾驶舱安全知识介绍，并在飞行中正确系带、使用氧气面罩和遵守撤离要求。",
    182: "飞行中机长失能时，应按副驾驶、观察员、主任乘务长/乘务长顺序接替机上指挥权。",
    191: "飞行前必须按机型 FCOM 完成外部绕机检查和内部检查。",
    208: "复飞应按仪表进近图规定的程序执行；未到达复飞点时应先飞到 MAPt。",
    211: "过站旅客留在机上时，应采取发动机关车、开放出口、保持足够客舱乘务员或合格人员分布等措施。",
    216: "紧急情况下，机长可在保证飞行安全范围内偏离规定程序，并按应急权利原则和程序报告。",
    220: "飞机发生坠毁、可控撞地、迫降等事故时，应先撤离旅客、保护现场、救援伤员并及时通报。",
    231: "被拦截飞机应立即听从拦截指示、报告空管、建立 121.5/243 MHz 联系并按要求选择 7700。",
    232: "迷航时不得盲目改变航向或下降高度，应报告 ATC、检查油量并按指令飞行。",
    277: "实地验证试飞方案应至少包括地点、机型、起飞时间和持续时间、机组名单、科目/应急程序、燃油量和其他需请示事项。",
    294: "RNA V10 区域发生影响导航能力的意外事件时，应按应急程序处置并在必要时获得 ATC 许可后偏航。",
    295: "执行 RNP1 标准仪表离场和标准仪表进场前，应检查 ICAO 飞行计划、RAIM、GPS、数据库有效性和程序加载情况。",
    297: "执行 RNP4 运行前，应检查 ICAO 飞行计划、导航设备、RAIM、数据库和应急程序。",
    393: "过站旅客留在机上时，应采取发动机关车、开放出口、保持足够客舱乘务员或合格人员分布等措施。",
    413: "发现传染性疾病乘客时，应按规定对机舱环境进行消毒处理。",
    431: "重要旅客包括省部级以上负责人、军队在职正军级少将以上负责人、公使大使级外交使节及中央各部委或驻外使领馆指定接待客人。",
    487: "指某点位于航空器航迹左右 90 度处，通常用于表示大致方位而非精确点位。",
    491: "应急医疗箱应配备血压计、听诊器、口咽气道、止血带、手套、消毒剂、注射器、0.9% 氯化钠、肾上腺素等急救用品。",
}


@dataclass
class LoadedHelpers:
    module: Any

    @property
    def utc_iso(self):
        return self.module.utc_iso

    @property
    def load_env_files(self):
        return self.module.load_env_files

    @property
    def parse_sse_events(self):
        return self.module.parse_sse_events

    @property
    def parse_raw_event(self):
        return self.module.parse_raw_event

    @property
    def sanitize(self):
        return self.module.sanitize

    @property
    def AuthFailure(self):
        return self.module.AuthFailure


def load_latency_helpers() -> LoadedHelpers:
    helper_path = ROOT / "scripts" / "b4_4_latency_compare.py"
    spec = importlib.util.spec_from_file_location("b4_4_latency_compare_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load helper module: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return LoadedHelpers(module=module)


HELPERS = load_latency_helpers()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mono_now() -> float:
    return time.perf_counter()


def wall_now() -> float:
    return time.time()


def read_json(path: Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")


def normalize_spaces(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def strip_title_prefix(title: str | None) -> str:
    text = normalize_spaces(title)
    text = LEADING_TITLE_NUMBER_RE.sub("", text)
    return text.strip(" -—–·：:")


def prompt_core_from_source(question: str) -> str:
    core = normalize_spaces(question)
    core = re.sub(r"^根据\s+.*?[，,]\s*", "", core)
    core = re.sub(r"^原文(?:中|对)?\s*", "", core)
    core = re.sub(r"^请问\s*", "", core)
    core = core.replace("“", "").replace("”", "")
    core = core.replace("原文中", "").replace("原文对", "").replace("原文", "")
    return normalize_spaces(core)


def strip_section_refs(text: str) -> str:
    cleaned = normalize_spaces(text)
    cleaned = re.sub(r"[表图]\s*(?=\d)", "", cleaned)
    cleaned = SECTION_REF_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def rewrite_question(source_question: str, chapter_title: str | None, leaf_title: str | None) -> str:
    context = strip_title_prefix(leaf_title) or strip_title_prefix(chapter_title) or "手册相关条款"
    core = prompt_core_from_source(source_question)
    if not core:
        core = "原文要求是什么"
    core = strip_section_refs(core)
    context_norm = normalize_spaces(context)
    if context_norm and normalize_spaces(core).startswith(context_norm):
        core = normalize_spaces(core)[len(context_norm):].lstrip("，,。:： ")
    core = strip_section_refs(core)
    core = normalize_spaces(core)
    question = f"{context}中，{core}"
    question = normalize_spaces(question)
    question = question.replace(f"{context}中，{context}", f"{context}中，")
    question = strip_section_refs(question)
    if not question.endswith(("？", "?", "。")):
        question += "？"
    return question


def build_question_type(question: str, source_kind: str, leaf_title: str, answer: str) -> str:
    q = normalize_spaces(question)
    leaf = normalize_spaces(leaf_title)
    answer_text = normalize_spaces(answer)

    if any(token in q for token in ("表格", "清单", "对应", "配备", "一览", "区间", "范围")) or any(
        token in leaf for token in ("表", "清单")
    ):
        return "table_lookup"
    if any(token in q for token in ("同时", "分别", "其中", "以及", "并且", "若", "如果", "条件", "例外")):
        return "multi_condition"
    if any(token in q for token in ("是否", "能否", "可否", "允许", "禁止", "不得", "必须")):
        return "compliance_judgment" if source_kind == "requirement" else "requirement"
    if source_kind == "definition":
        return "definition"
    if source_kind == "numeric":
        if any(token in q for token in ("数量", "数值", "时限", "期限", "上限", "下限", "配备", "区间")):
            return "table_lookup"
        if len(re.findall(r"[、，；]", answer_text)) >= 2:
            return "multi_condition"
        return "numeric"
    if source_kind == "requirement":
        return "requirement"
    if source_kind == "fact":
        if len(re.findall(r"[、，；]", answer_text)) >= 2:
            return "multi_condition"
        return "fact"
    if len(re.findall(r"[、，；]", answer_text)) >= 2:
        return "multi_condition"
    return "fact"


def build_difficulty(question_type: str, page_span: int, expected_answer: str, question: str) -> str:
    answer_len = len(normalize_spaces(expected_answer))
    if question_type in {"table_lookup", "multi_condition"} or page_span >= 8 or answer_len >= 90:
        return "hard"
    if question_type in {"definition", "requirement", "compliance_judgment"} or page_span >= 4 or answer_len >= 35:
        return "medium"
    if "并" in question or "其中" in question:
        return "medium"
    return "easy"


def build_assessment_point(question_type: str, title: str) -> str:
    leaf = strip_title_prefix(title) or "相关条款"
    templates = {
        "definition": f"核对“{leaf}”中的定义或完整表述",
        "numeric": f"核对“{leaf}”中的具体数值、数量或时限",
        "table_lookup": f"核对“{leaf}”中的表格/清单对应值",
        "multi_condition": f"核对“{leaf}”中多条件叠加时的适用规则",
        "requirement": f"核对“{leaf}”中的约束性要求",
        "compliance_judgment": f"核对“{leaf}”中的允许/禁止/必须类判断",
        "fact": f"核对“{leaf}”中的事实性规定或配置",
    }
    return templates.get(question_type, f"核对“{leaf}”中的原文信息")


def build_reasoning_path(question_type: str, chapter_title: str, leaf_title: str) -> str:
    context = strip_title_prefix(leaf_title) or strip_title_prefix(chapter_title) or "相关条款"
    base = f"先定位到“{context}”对应原文，再判断这是{question_type}类信息，最后按原文直接作答，不做外推。"
    if question_type == "table_lookup":
        base += " 若是表格题，优先按行列或区间对应关系查找。"
    elif question_type == "multi_condition":
        base += " 若存在多个条件或例外，需逐项核对并保留边界条件。"
    elif question_type == "compliance_judgment":
        base += " 重点核对是否存在必须、禁止、允许或例外条款。"
    return base


def build_expected_citation_hint(chapter_title: str, leaf_title: str, page_start: int, page_end: int, node_id: str | None) -> str:
    hint_parts = [
        f"章节: {chapter_title}",
        f"子节: {leaf_title}",
        f"页码: {page_start}-{page_end}",
    ]
    if node_id:
        hint_parts.append(f"node_id: {node_id}")
    return " / ".join(hint_parts)


def summarize_expected_answer(question_id: int, raw_answer: str) -> str:
    override = EXPECTED_ANSWER_OVERRIDES.get(question_id)
    if override:
        return override
    answer = normalize_spaces(raw_answer).strip("：: ")
    if not answer:
        return ""
    if len(answer) <= 96:
        return answer
    sentences = [segment.strip() for segment in ANSWER_SENTENCE_SPLIT_RE.split(answer) if segment.strip()]
    if len(sentences) > 1:
        first_sentence = sentences[0]
        if len(first_sentence) >= 48:
            answer = first_sentence
        else:
            answer = "".join(sentences[:2]).strip()
    if len(answer) > 96:
        clauses = [segment.strip() for segment in ANSWER_CLAUSE_SPLIT_RE.split(answer) if segment.strip()]
        if len(clauses) > 1:
            condensed = clauses[0]
            for clause in clauses[1:]:
                if len(condensed) >= 96:
                    break
                condensed += "，" + clause
                if len(condensed) >= 84:
                    break
            answer = condensed
    if len(answer) > 96:
        answer = answer[:96].rstrip("，,、；; ")
    return answer


def validate_question_text(question: str) -> list[str]:
    failures: list[str] = []
    for pattern in FORBIDDEN_QUESTION_PATTERNS:
        if pattern.search(question):
            failures.append(pattern.pattern)
    if SECTION_REF_RE.search(question):
        failures.append(SECTION_REF_RE.pattern)
    return failures


def generate_question_set() -> list[dict[str, Any]]:
    source = read_json(QUESTION_SOURCE_PATH, [])
    if not isinstance(source, list) or not source:
        raise RuntimeError(f"Question source missing or invalid: {QUESTION_SOURCE_PATH}")

    generated: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, item in enumerate(source, start=1):
        if not isinstance(item, dict):
            continue
        question_id = int(item.get("id") or index)
        chapter_title = str(item.get("chapter_title") or "").strip()
        leaf_title = str(item.get("leaf_title") or "").strip()
        source_kind = str(item.get("kind") or "fact").strip()
        source_question = str(item.get("question") or "").strip()
        expected_answer = summarize_expected_answer(question_id, str(item.get("reference_answer") or ""))
        page_start = int(item.get("page_start") or 0)
        page_end = int(item.get("page_end") or 0)
        page_span = int(item.get("page_span") or max(0, page_end - page_start + 1))
        node_id = str(item.get("node_id") or "").strip() or None

        question = rewrite_question(source_question, chapter_title, leaf_title)
        question_type = build_question_type(question, source_kind, leaf_title, expected_answer)
        difficulty = build_difficulty(question_type, page_span, expected_answer, question)
        assessment_point = build_assessment_point(question_type, leaf_title or chapter_title)
        reasoning_path = build_reasoning_path(question_type, chapter_title, leaf_title)
        citation_hint = build_expected_citation_hint(chapter_title, leaf_title, page_start, page_end, node_id)

        record = {
            "question_id": question_id,
            "worker_id": ((question_id - 1) // WORKER_BATCH_SIZE) + 1,
            "question": question,
            "assessment_point": assessment_point,
            "expected_answer": expected_answer,
            "reasoning_path": reasoning_path,
            "expected_citation_hint": citation_hint,
            "question_type": question_type,
            "difficulty": difficulty,
            "chapter_title": chapter_title,
            "leaf_title": leaf_title,
            "page_start": page_start,
            "page_end": page_end,
            "page_span": page_span,
            "source_kind": source_kind,
            "source_question": source_question,
            "node_id": node_id,
        }
        failures = validate_question_text(question)
        if failures:
            invalid.append({"question_id": question_id, "question": question, "patterns": failures})
            # Final fallback that still preserves the section context without numeric prefixes.
            safe_leaf = strip_title_prefix(leaf_title) or strip_title_prefix(chapter_title) or "相关条款"
            record["question"] = f"{safe_leaf}中，原文对应信息是什么？"
            if not record["question"].endswith("？"):
                record["question"] += "？"
            if validate_question_text(record["question"]):
                raise RuntimeError(f"Unable to sanitize generated question {question_id}: {record['question']}")
        generated.append(record)

    if len(generated) != 500:
        raise RuntimeError(f"Expected 500 generated questions, got {len(generated)}")

    generated.sort(key=lambda item: int(item["question_id"]))
    if invalid:
        write_json(RESULTS_DIR / "b4_4_skill_eval_question_generation_invalid.json", invalid)
    return generated


def split_by_worker(questions: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        grouped[int(question["worker_id"])].append(question)
    for worker_id in grouped:
        grouped[worker_id].sort(key=lambda item: int(item["question_id"]))
    return grouped


def persist_question_artifacts(questions: list[dict[str, Any]]) -> None:
    write_json(QUESTION_OUTPUT_PATH, questions)
    QUESTION_BY_WORKER_DIR.mkdir(parents=True, exist_ok=True)
    worker_groups = split_by_worker(questions)
    for worker_id in range(1, DEFAULT_WORKER_COUNT + 1):
        worker_questions = worker_groups.get(worker_id, [])
        write_json(QUESTION_BY_WORKER_DIR / f"worker_{worker_id}.json", worker_questions)


def resolve_api_base() -> str:
    base = (
        os.getenv("PAGEINDEX_API_BASE", "").strip()
        or os.getenv("PAGEINDEX_API_BASE_URL", "").strip()
        or DEFAULT_API_BASE
    )
    if base.endswith("/api/v1"):
        return base.rstrip("/")
    return f"{base.rstrip('/')}/api/v1"


def require_pageindex_api_key() -> str:
    api_key = os.getenv("PAGEINDEX_API_KEY", "").strip() or os.getenv("SKILL_RUN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("PAGEINDEX_API_KEY is required.")
    return api_key


def resolve_skill_id(cli_skill_id: str | None, api_base: str, session: requests.Session) -> str:
    if cli_skill_id:
        return cli_skill_id.strip()
    env_skill_id = os.getenv("PAGEINDEX_SKILL_ID", "").strip()
    if env_skill_id:
        return env_skill_id

    candidates = [
        DEFAULT_SKILL_ID,
        "43a652ac-f028-45e7-bd58-cc6f84675759",
    ]
    for candidate in candidates:
        try:
            response = session.get(
                f"{api_base.rstrip('/')}/skills/{candidate}",
                headers={"Accept": "application/json"},
                timeout=(10, 30),
            )
            if response.ok:
                return candidate
        except Exception:
            continue
    return candidates[0]


def build_skill_run_payload(question: str, retrieval_mode: str, generation_config: dict[str, Any] | None = None) -> dict[str, Any]:
    if generation_config is None:
        generation_config = {"temperature": 0}
        max_tokens = (
            os.getenv("PAGEINDEX_RUN_MAX_TOKENS", "").strip()
            or os.getenv("PAGEINDEX_CHAT_MAX_TOKENS", "").strip()
        )
        if max_tokens:
            try:
                generation_config["max_tokens"] = int(max_tokens)
            except ValueError:
                pass
    payload: dict[str, Any] = {
        "question": question,
        "stream": True,
        "conversation_config": {
            "include_history": False,
            "query_rewrite_with_history": False,
            "include_assistant_messages": False,
        },
        "retrieval_config": {
            "retrieval_mode": retrieval_mode,
        },
        "generation_config": generation_config,
    }
    return payload


def resolve_run_model_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    provider_id = (
        os.getenv("PAGEINDEX_RUN_PROVIDER_ID", "").strip()
        or os.getenv("PAGEINDEX_CHAT_PROVIDER_ID", "").strip()
    )
    model = (
        os.getenv("PAGEINDEX_RUN_MODEL", "").strip()
        or os.getenv("PAGEINDEX_CHAT_MODEL", "").strip()
    )
    if provider_id:
        settings["provider_id"] = provider_id
    if model:
        settings["model"] = model
    return settings


def _event_elapsed_ms(start_mono: float, event_mono: float | None) -> float | None:
    if event_mono is None:
        return None
    return round((event_mono - start_mono) * 1000.0, 3)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_step_timings(observation_events: list[dict[str, Any]]) -> dict[str, Any]:
    timings: dict[str, dict[str, Any]] = defaultdict(lambda: {"started_ms": None, "completed_ms": None})
    for event in observation_events:
        step = event.get("step")
        event_type = event.get("event_type")
        if not step or event_type not in {"step_started", "step_completed"}:
            continue
        timing = timings[str(step)]
        key = "started_ms" if event_type == "step_started" else "completed_ms"
        timing[key] = event.get("arrival_ms")
        payload = event.get("payload")
        if isinstance(payload, dict):
            if event_type == "step_completed":
                if "context_block_count" in payload:
                    timing["context_block_count"] = payload.get("context_block_count")
                if "context_chars" in payload:
                    timing["context_chars"] = payload.get("context_chars")
                if "answer_ms" in payload:
                    timing["answer_ms"] = payload.get("answer_ms")
                if "ttft_ms" in payload:
                    timing["ttft_ms"] = payload.get("ttft_ms")
            timing.setdefault("payloads", [])
            timing["payloads"].append(payload)
    return dict(timings)


def _build_execution_context_summary(execution_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(execution_context, dict):
        return {}
    provider = execution_context.get("provider")
    model = execution_context.get("model")
    retrieval = execution_context.get("retrieval")
    target = execution_context.get("target")
    merge = execution_context.get("merge")
    summary = {
        "provider": {
            "id": provider.get("id") if isinstance(provider, dict) else None,
            "name": provider.get("name") if isinstance(provider, dict) else None,
            "type": provider.get("type") if isinstance(provider, dict) else None,
            "scope": provider.get("scope") if isinstance(provider, dict) else None,
            "resolution_source": provider.get("resolution_source") if isinstance(provider, dict) else None,
        },
        "model": {
            "resolved_model": model.get("resolved_model") if isinstance(model, dict) else None,
        },
        "retrieval": {},
        "target": {},
        "merge": {},
    }
    if isinstance(retrieval, dict):
        keep_keys = (
            "retrieval_mode",
            "query",
            "rewritten_query",
            "rewrite_applied",
            "top_k",
            "node_top_k",
            "candidate_top_k",
            "selection_mode",
            "query_rewrite_strategy",
            "outline_selection_strategy",
            "selected_node_count",
            "content_backed_node_count",
            "active_backend",
            "requested_dense_source",
            "dense_source",
            "fallback_reason",
            "fallback_recommendation",
            "boundary_flags",
            "documents_considered",
            "documents_with_hits",
            "rerank_mode",
            "rerank_resolved_mode",
            "rerank_applied",
            "rerank_model",
            "rerank_provider_source",
            "warnings",
        )
        summary["retrieval"] = {key: retrieval.get(key) for key in keep_keys if retrieval.get(key) is not None}
    if isinstance(target, dict):
        summary["target"] = {key: target.get(key) for key in ("requested_mode", "resolved_mode", "knowledge_base_id") if target.get(key) is not None}
    if isinstance(merge, dict):
        summary["merge"] = {key: merge.get(key) for key in ("strategy", "candidate_count", "selected_citation_count", "fallback_mode") if merge.get(key) is not None}
    telemetry = execution_context.get("telemetry")
    if isinstance(telemetry, dict):
        summary["telemetry"] = telemetry
    return summary


def _build_metrics_summary(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    keep_keys = (
        "queue_ms",
        "retrieve_ms",
        "answer_ms",
        "ttft_ms",
        "total_ms",
        "wall_clock_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "manual_count",
        "selected_section_count",
        "successful_llm_calls",
        "citations_count",
        "stream_usage_source",
        "retrieval_mode",
        "node_top_k",
        "selected_node_count",
        "content_backed_node_count",
        "active_backend",
        "requested_dense_source",
        "dense_source",
        "fallback_reason",
        "boundary_flags",
        "documents_considered",
        "documents_with_hits",
    )
    return {key: metrics.get(key) for key in keep_keys if metrics.get(key) is not None}


def _build_stream_record(
    *,
    question: dict[str, Any],
    retrieval_mode: str,
    request_start_wall: float,
    request_start_mono: float,
    response_headers_mono: float,
    response_headers_wall: float,
    response_headers: requests.Response,
    run_started_mono: float | None,
    run_completed_mono: float | None,
    first_answer_delta_mono: float | None,
    stream_closed_mono: float,
    stream_closed_wall: float,
    observation_events: list[dict[str, Any]],
    event_log: list[dict[str, Any]],
    completed_payload: dict[str, Any] | None,
    run_details: dict[str, Any] | None,
    request_id: str | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = _build_metrics_summary((run_details or {}).get("metrics") if isinstance(run_details, dict) else None)
    execution_context = _build_execution_context_summary((run_details or {}).get("execution_context") if isinstance(run_details, dict) else None)
    selected_sections = (run_details or {}).get("selected_sections") if isinstance(run_details, dict) else None
    citations = (run_details or {}).get("citations") if isinstance(run_details, dict) else None
    answer_text = str((run_details or {}).get("answer_text") or (run_details or {}).get("answer") or "")
    provider_info = execution_context.get("provider", {}) if isinstance(execution_context, dict) else {}
    model_info = execution_context.get("model", {}) if isinstance(execution_context, dict) else {}
    retrieval_info = execution_context.get("retrieval", {}) if isinstance(execution_context, dict) else {}
    step_timings = _extract_step_timings(observation_events)

    status_retrieving_ms = next((event.get("elapsed_ms") for event in event_log if event["event"] == "status" and event.get("payload", {}).get("status") == "retrieving"), None)
    build_context_start_ms = step_timings.get("build_context", {}).get("started_ms")
    build_context_end_ms = step_timings.get("build_context", {}).get("completed_ms")
    final_answer_start_ms = step_timings.get("final_answer", {}).get("started_ms")
    final_answer_end_ms = step_timings.get("final_answer", {}).get("completed_ms")

    retrieval_ms = None
    if status_retrieving_ms is not None and build_context_start_ms is not None:
        retrieval_ms = round(build_context_start_ms - status_retrieving_ms, 3)
    build_context_ms = None
    if build_context_start_ms is not None and build_context_end_ms is not None:
        build_context_ms = round(build_context_end_ms - build_context_start_ms, 3)
    final_answer_ms = _safe_float(metrics.get("answer_ms"))
    if final_answer_ms is None and final_answer_start_ms is not None and final_answer_end_ms is not None:
        final_answer_ms = round(final_answer_end_ms - final_answer_start_ms, 3)
    ttft_ms = _safe_float(metrics.get("ttft_ms"))
    if ttft_ms is None and first_answer_delta_mono is not None and final_answer_start_ms is not None:
        ttft_ms = round(first_answer_delta_mono - final_answer_start_ms, 3)
    context_block_count = step_timings.get("build_context", {}).get("context_block_count")
    context_chars = step_timings.get("build_context", {}).get("context_chars")
    context_tokens = None
    if isinstance(retrieval_info, dict):
        context_tokens = retrieval_info.get("context_tokens")
    if context_tokens is None and isinstance(step_timings.get("build_context", {}).get("payloads"), list):
        for payload in step_timings.get("build_context", {}).get("payloads", []):
            if isinstance(payload, dict) and payload.get("context_tokens") is not None:
                context_tokens = payload.get("context_tokens")
                break

    output_tokens = _safe_int(metrics.get("output_tokens"))
    input_tokens = _safe_int(metrics.get("input_tokens"))
    total_tokens = _safe_int(metrics.get("total_tokens"))
    output_tokens_per_sec = None
    if output_tokens is not None and final_answer_ms and final_answer_ms > 0:
        output_tokens_per_sec = round(output_tokens / (final_answer_ms / 1000.0), 3)

    total_elapsed_ms = round((stream_closed_mono - request_start_mono) * 1000.0, 3)
    response_headers_elapsed_ms = round((response_headers_mono - request_start_mono) * 1000.0, 3)
    run_started_elapsed_ms = _event_elapsed_ms(request_start_mono, run_started_mono)
    run_completed_elapsed_ms = _event_elapsed_ms(request_start_mono, run_completed_mono or stream_closed_mono)
    first_answer_elapsed_ms = _event_elapsed_ms(request_start_mono, first_answer_delta_mono)
    sse_flush_lag_ms = None
    if run_completed_mono is not None:
        sse_flush_lag_ms = round((stream_closed_mono - run_completed_mono) * 1000.0, 3)

    stream_event_counts = Counter(event["event"] for event in event_log)
    observation_event_counts = Counter(event.get("event_type") for event in observation_events if event.get("event_type"))

    run_status = "unknown"
    if isinstance(run_details, dict):
        run_status = str(run_details.get("status") or run_status)
    if error and run_status == "unknown":
        run_status = "failed"

    return {
        **{key: question.get(key) for key in (
            "question_id",
            "worker_id",
            "question",
            "assessment_point",
            "expected_answer",
            "reasoning_path",
            "expected_citation_hint",
            "question_type",
            "difficulty",
            "chapter_title",
            "leaf_title",
            "page_start",
            "page_end",
            "page_span",
            "source_kind",
            "source_question",
            "node_id",
        )},
        "retrieval_mode": retrieval_mode,
        "request_start_ms": int(request_start_wall * 1000),
        "request_start_iso": HELPERS.utc_iso(request_start_wall),
        "response_headers_ms": response_headers_elapsed_ms,
        "response_headers_iso": HELPERS.utc_iso(response_headers_wall),
        "run_started_ms": run_started_elapsed_ms,
        "first_answer_delta_ms": first_answer_elapsed_ms,
        "ttft_ms": ttft_ms,
        "run_completed_ms": run_completed_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "retrieval_ms": retrieval_ms,
        "build_context_ms": build_context_ms,
        "final_answer_ms": final_answer_ms,
        "queue_ms": _safe_float(metrics.get("queue_ms")),
        "sse_flush_lag_ms": sse_flush_lag_ms,
        "output_tokens": output_tokens,
        "input_tokens": input_tokens,
        "prompt_tokens": input_tokens,
        "total_tokens": total_tokens,
        "output_tokens_per_sec": output_tokens_per_sec,
        "answer_text": answer_text,
        "selected_sections": selected_sections if isinstance(selected_sections, list) else [],
        "citations": citations if isinstance(citations, list) else [],
        "context_block_count": context_block_count,
        "context_chars": context_chars,
        "context_tokens": context_tokens,
        "provider": provider_info,
        "model": model_info,
        "retrieval": retrieval_info,
        "execution_context": execution_context,
        "metrics": metrics,
        "step_timings": step_timings,
        "stream_event_counts": dict(stream_event_counts),
        "observation_event_counts": dict(observation_event_counts),
        "event_log": event_log,
        "request_id": request_id,
        "status": run_status,
        "error": error,
        "completed_payload": completed_payload,
        "response_headers": {
            "content_type": response_headers.headers.get("content-type"),
            "cache_control": response_headers.headers.get("cache-control"),
            "x_accel_buffering": response_headers.headers.get("x-accel-buffering"),
            "transfer_encoding": response_headers.headers.get("transfer-encoding"),
            "request_id": request_id,
        },
    }


def fetch_run_details(session: requests.Session, api_base: str, auth_headers: dict[str, str], run_id: str) -> dict[str, Any] | None:
    try:
        response = session.get(
            f"{api_base.rstrip('/')}/runs/{run_id}",
            headers={**auth_headers, "Accept": "application/json"},
            timeout=(20, 120),
        )
    except Exception:
        return None
    if not response.ok:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def run_skill_case(
    session: requests.Session,
    *,
    api_base: str,
    auth_headers: dict[str, str],
    skill_id: str,
    question: dict[str, Any],
    retrieval_mode: str,
    request_timeout_seconds: int = 3600,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/chat/skills/{skill_id}/run"
    payload = build_skill_run_payload(str(question["question"]), retrieval_mode)
    payload.update(resolve_run_model_settings())
    request_start_mono = mono_now()
    request_start_wall = wall_now()
    response = session.post(
        url,
        json=payload,
        headers={**auth_headers, "Accept": "text/event-stream", "Content-Type": "application/json"},
        stream=True,
        timeout=(30, request_timeout_seconds),
    )
    response_headers_mono = mono_now()
    response_headers_wall = wall_now()
    request_id = response.headers.get("x-request-id") or response.headers.get("X-Request-ID")
    if response.status_code >= 400:
        body = response.text
        response.close()
        error_payload = {
            "type": "http_error",
            "status_code": response.status_code,
            "body": body[:5000],
            "request_id": request_id,
        }
        if response.status_code == 401:
            raise HELPERS.AuthFailure(body)
        return _build_stream_record(
            question=question,
            retrieval_mode=retrieval_mode,
            request_start_wall=request_start_wall,
            request_start_mono=request_start_mono,
            response_headers_mono=response_headers_mono,
            response_headers_wall=response_headers_wall,
            response_headers=response,
            run_started_mono=None,
            run_completed_mono=None,
            first_answer_delta_mono=None,
            stream_closed_mono=mono_now(),
            stream_closed_wall=wall_now(),
            observation_events=[],
            event_log=[],
            completed_payload=None,
            run_details=None,
            request_id=request_id,
            error=error_payload,
        )

    event_log: list[dict[str, Any]] = []
    observation_events: list[dict[str, Any]] = []
    completed_payload: dict[str, Any] | None = None
    run_id: str | None = None
    run_started_mono: float | None = None
    run_completed_mono: float | None = None
    first_answer_delta_mono: float | None = None
    error_payload: dict[str, Any] | None = None
    last_answer_delta_mono: float | None = None
    try:
        for raw_event, event_mono, event_wall in HELPERS.parse_sse_events(response):
            parsed = HELPERS.parse_raw_event(raw_event)
            if not parsed:
                continue
            event_name, payload_obj = parsed
            event_record = {
                "event": event_name,
                "mono_ts": event_mono,
                "wall_ts": event_wall,
                "elapsed_ms": round((event_mono - request_start_mono) * 1000.0, 3),
                "iso_ts": HELPERS.utc_iso(event_wall),
                "payload": HELPERS.sanitize(payload_obj),
            }
            event_log.append(event_record)
            if event_name == "run_started":
                run_id = str(payload_obj.get("run_id") or "") or run_id
                run_started_mono = event_mono
            elif event_name == "answer_delta":
                if first_answer_delta_mono is None:
                    first_answer_delta_mono = event_mono
                last_answer_delta_mono = event_mono
            elif event_name == "run_completed":
                completed_payload = HELPERS.sanitize(payload_obj)
                run_id = str(payload_obj.get("id") or run_id or "")
                run_completed_mono = event_mono
            elif event_name == "error":
                error_payload = HELPERS.sanitize(payload_obj)
            elif event_name == "observation":
                obs = payload_obj if isinstance(payload_obj, dict) else {}
                obs_record = {
                    "event_type": obs.get("event_type"),
                    "step": obs.get("step"),
                    "status": obs.get("status"),
                    "payload": HELPERS.sanitize(obs.get("payload") if isinstance(obs.get("payload"), dict) else {}),
                    "created_at": obs.get("created_at"),
                    "arrival_ms": round((event_mono - request_start_mono) * 1000.0, 3),
                }
                observation_events.append(obs_record)
    finally:
        stream_closed_mono = mono_now()
        stream_closed_wall = wall_now()
        response.close()

    if run_completed_mono is None and last_answer_delta_mono is not None:
        run_completed_mono = last_answer_delta_mono

    run_details = fetch_run_details(session, api_base, auth_headers, run_id) if run_id else None
    if run_details is None and completed_payload and isinstance(completed_payload, dict):
        # Use the streamed payload if the follow-up run lookup is unavailable.
        run_details = completed_payload if isinstance(completed_payload, dict) else None

    return _build_stream_record(
        question=question,
        retrieval_mode=retrieval_mode,
        request_start_wall=request_start_wall,
        request_start_mono=request_start_mono,
        response_headers_mono=response_headers_mono,
        response_headers_wall=response_headers_wall,
        response_headers=response,
        run_started_mono=run_started_mono,
        run_completed_mono=run_completed_mono,
        first_answer_delta_mono=first_answer_delta_mono,
        stream_closed_mono=stream_closed_mono,
        stream_closed_wall=stream_closed_wall,
        observation_events=observation_events,
        event_log=event_log,
        completed_payload=completed_payload,
        run_details=run_details,
        request_id=request_id,
        error=error_payload,
    )


def load_existing_worker_records(path: Path) -> dict[int, dict[str, Any]]:
    records = read_jsonl(path)
    existing: dict[int, dict[str, Any]] = {}
    for record in records:
        question_id = _safe_int(record.get("question_id"))
        if question_id is not None:
            existing[question_id] = record
    return existing


def run_worker_batch(
    *,
    mode: str,
    worker_id: int,
    questions: list[dict[str, Any]],
    api_base: str,
    skill_id: str,
    auth_headers: dict[str, str],
    request_timeout_seconds: int,
) -> list[dict[str, Any]]:
    worker_dir = RUN_WORKER_ROOT / mode
    worker_dir.mkdir(parents=True, exist_ok=True)
    worker_path = worker_dir / f"worker_{worker_id}.jsonl"
    existing = load_existing_worker_records(worker_path)
    pending = [question for question in questions if int(question["question_id"]) not in existing]
    print(f"[{mode}][worker-{worker_id}] existing={len(existing)} pending={len(pending)}", file=sys.stderr)
    if not pending:
        return [existing[int(question["question_id"])] for question in questions]

    results = dict(existing)
    for question in pending:
        try:
            record = run_skill_case(
                requests.Session(),
                api_base=api_base,
                auth_headers=auth_headers,
                skill_id=skill_id,
                question=question,
                retrieval_mode=mode,
                request_timeout_seconds=request_timeout_seconds,
            )
        except Exception as exc:
            record = {
                **question,
                "retrieval_mode": mode,
                "request_start_ms": int(time.time() * 1000),
                "request_start_iso": utc_now_iso(),
                "response_headers_ms": None,
                "run_started_ms": None,
                "first_answer_delta_ms": None,
                "ttft_ms": None,
                "run_completed_ms": None,
                "total_elapsed_ms": None,
                "retrieval_ms": None,
                "build_context_ms": None,
                "final_answer_ms": None,
                "queue_ms": None,
                "sse_flush_lag_ms": None,
                "output_tokens": None,
                "input_tokens": None,
                "prompt_tokens": None,
                "total_tokens": None,
                "output_tokens_per_sec": None,
                "answer_text": "",
                "selected_sections": [],
                "citations": [],
                "context_block_count": None,
                "context_chars": None,
                "context_tokens": None,
                "provider": {},
                "model": {},
                "retrieval": {},
                "execution_context": {},
                "metrics": {},
                "step_timings": {},
                "stream_event_counts": {},
                "observation_event_counts": {},
                "event_log": [],
                "request_id": None,
                "status": "failed",
                "error": str(exc),
                "completed_payload": None,
                "response_headers": {},
            }
        results[int(question["question_id"])] = record
        append_jsonl(worker_path, record)

    ordered = [results[int(question["question_id"])] for question in questions]
    write_jsonl(worker_path, ordered)
    return ordered


def run_mode(
    *,
    mode: str,
    questions: list[dict[str, Any]],
    api_base: str,
    skill_id: str,
    auth_headers: dict[str, str],
    workers: int = DEFAULT_WORKER_COUNT,
    request_timeout_seconds: int = 3600,
) -> list[dict[str, Any]]:
    by_worker: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        by_worker[int(question["worker_id"])].append(question)
    for worker_questions in by_worker.values():
        worker_questions.sort(key=lambda item: int(item["question_id"]))

    results_by_worker: dict[int, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                run_worker_batch,
                mode=mode,
                worker_id=worker_id,
                questions=worker_questions,
                api_base=api_base,
                skill_id=skill_id,
                auth_headers=auth_headers,
                request_timeout_seconds=request_timeout_seconds,
            ): worker_id
            for worker_id, worker_questions in sorted(by_worker.items())
        }
        for future in as_completed(future_map):
            worker_id = future_map[future]
            results_by_worker[worker_id] = future.result()
            print(f"[{mode}][worker-{worker_id}] done", file=sys.stderr)

    ordered: list[dict[str, Any]] = []
    for worker_id in range(1, workers + 1):
        ordered.extend(results_by_worker.get(worker_id, []))
    ordered.sort(key=lambda item: int(item["question_id"]))
    out_path = {
        "fast": RUN_OUTPUT_FAST_PATH,
        "deep_research": RUN_OUTPUT_DEEP_PATH,
    }.get(mode)
    if out_path is None:
        out_path = RUN_OUTPUT_OPENAI_COMPAT_PATH
    write_jsonl(out_path, ordered)
    return ordered


def try_probe_openai_compat_interface(api_base: str, auth_headers: dict[str, str], session: requests.Session) -> dict[str, Any]:
    candidates = [
        f"{api_base.rstrip('/')}/chat/completions",
        f"{api_base.rstrip('/')}/v1/chat/completions",
    ]
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ],
        "stream": False,
        "temperature": 0,
    }
    for url in candidates:
        try:
            response = session.post(url, json=payload, headers=auth_headers, timeout=(10, 30))
        except Exception as exc:
            continue
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            return {
                "available": False,
                "reason": f"HTTP {response.status_code}",
                "url": url,
                "response": response.text[:2000],
            }
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:2000]}
        return {
            "available": True,
            "reason": "route_present",
            "url": url,
            "response": data,
        }
    return {
        "available": False,
        "reason": "No OpenAI-compatible chat/completions route exposed by the PageIndex API.",
        "url": None,
    }


def format_ms(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.1f}"
    except Exception:
        return "N/A"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * max(0.0, min(percentile, 100.0)) / 100.0
    lower = int(math.floor(rank))
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 3)


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 3) if values else None


def _latency_summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": round(max(values), 3) if values else None,
        "avg_ms": _avg(values),
    }


def _token_bucket(tokens: int | None) -> str:
    if tokens is None or tokens <= 0:
        return "0"
    if tokens < 1000:
        return "1-999"
    if tokens < 2000:
        return "1000-1999"
    if tokens < 4000:
        return "2000-3999"
    if tokens < 8000:
        return "4000-7999"
    return "8000+"


def _latency_bucket(ms: float | int | None) -> str:
    if ms is None:
        return "unknown"
    value = float(ms)
    if value < 10_000:
        return "<10s"
    if value < 30_000:
        return "10-30s"
    if value < 60_000:
        return "30-60s"
    if value < 120_000:
        return "60-120s"
    return "120s+"


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return round(numerator / (denom_x * denom_y), 4)


def load_score_helpers():
    eval_path = ROOT / "scripts" / "phase47" / "skill_run_eval.py"
    spec = importlib.util.spec_from_file_location("phase47_skill_run_eval_helpers", eval_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load score helpers: {eval_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resolve_eval_settings() -> tuple[str, str, str]:
    model = (
        os.getenv("PAGEINDEX_EVAL_MODEL", "").strip()
        or os.getenv("DEEPSEEK_MODEL", "").strip()
        or os.getenv("EVAL_MODEL", "").strip()
        or DEFAULT_EVAL_MODEL
    )
    api_key = (
        os.getenv("PAGEINDEX_EVAL_API_KEY", "").strip()
        or os.getenv("DEEPSEEK_API_KEY", "").strip()
        or os.getenv("EVAL_API_KEY", "").strip()
    )
    api_base = (
        os.getenv("PAGEINDEX_EVAL_API_BASE", "").strip()
        or os.getenv("DEEPSEEK_API_BASE", "").strip()
        or os.getenv("EVAL_API_BASE", "").strip()
        or DEFAULT_EVAL_API_BASE
    )
    return model, api_key, api_base.rstrip("/")


def score_single_answer(
    *,
    eval_session: requests.Session,
    eval_model: str,
    eval_api_base: str,
    eval_api_key: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    if record.get("status") != "completed" or not str(record.get("answer_text") or "").strip():
        return {
            "question_id": record["question_id"],
            "retrieval_mode": record["retrieval_mode"],
            "content_score": 0,
            "citation_score": 0,
            "structure_score": 0,
            "completeness_score": 0,
            "hallucination_risk": "high",
            "verdict": "fail",
            "evaluator_reason": record.get("error") or "Run did not complete successfully.",
            "evaluator_model": eval_model,
            "score_source": "auto_fail",
            "score_prompt_tokens": None,
            "score_completion_tokens": None,
            "score_total_tokens": None,
            "score_latency_ms": 0.0,
        }

    prompt = {
        "question": record.get("question"),
        "question_type": record.get("question_type"),
        "difficulty": record.get("difficulty"),
        "retrieval_mode": record.get("retrieval_mode"),
        "expected_answer": record.get("expected_answer"),
        "answer_text": record.get("answer_text"),
        "citations": [
            {
                "title": citation.get("title"),
                "page_start": citation.get("page_start"),
                "page_end": citation.get("page_end"),
                "document_label": citation.get("document_label"),
                "node_id": citation.get("node_id"),
                "node_key": citation.get("node_key"),
                "routing_index_version": citation.get("routing_index_version"),
                "score": citation.get("score"),
                "rerank_score": citation.get("rerank_score"),
                "route_summary": citation.get("route_summary"),
            }
            for citation in (record.get("citations") or [])
            if isinstance(citation, dict)
        ],
    }
    prompt_text = (
        "你是一个严格的中文RAG答案评审员。\n"
        "请只输出JSON，不要输出任何解释或代码块。\n"
        "你需要同时检查内容、引用、结构、完整性和幻觉风险。\n\n"
        f"【问题类型】{prompt['question_type']}\n"
        f"【难度】{prompt['difficulty']}\n"
        f"【检索模式】{prompt['retrieval_mode']}\n"
        f"【问题】{prompt['question']}\n"
        f"【答案摘要】{prompt['expected_answer']}\n"
        f"【系统回答】{prompt['answer_text']}\n"
        f"【引用】{json.dumps(prompt['citations'], ensure_ascii=False)}\n\n"
        "评分规则：\n"
        "- content_score: 2=内容正确且没有关键错误; 1=大体正确但有遗漏/轻微错误; 0=明显错误或答非所问\n"
        "- citation_score: 2=引用真实且能支撑答案; 1=引用大体正确但不够精确; 0=引用错误、缺失或编造\n"
        "- structure_score: 2=结构符合问题类型; 1=基本符合但略显冗余/不完整; 0=结构明显不符合\n"
        "- completeness_score: 2=覆盖关键限制条件/例外; 1=遗漏次要信息; 0=遗漏主要信息\n"
        "- hallucination_risk: none/low/medium/high\n"
        "- verdict: pass/weak_pass/fail\n"
        "如果答案失败、引用编造、越权推断或存在明显胡编，请直接判 fail。\n"
        "请严格输出如下JSON字段：content_score, citation_score, structure_score, completeness_score, hallucination_risk, verdict, evaluator_reason。\n"
    )
    payload = {
        "model": eval_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0,
        "stream": False,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    started = mono_now()
    response = eval_session.post(
        f"{eval_api_base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {eval_api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=(30, 300),
    )
    latency_ms = round((mono_now() - started) * 1000.0, 3)
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    content = ""
    if choices and isinstance(choices, list):
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message") or {}
            if isinstance(message, dict):
                content = str(message.get("content") or "")
    parsed = extract_json_object(content)
    usage = body.get("usage") or {}
    content_score = parsed.get("content_score")
    citation_score = parsed.get("citation_score")
    structure_score = parsed.get("structure_score")
    completeness_score = parsed.get("completeness_score")
    hallucination_risk = str(parsed.get("hallucination_risk") or "medium").strip().lower()
    verdict = str(parsed.get("verdict") or "fail").strip().lower()
    evaluator_reason = str(parsed.get("evaluator_reason") or parsed.get("reason") or "").strip()
    return {
        "question_id": record["question_id"],
        "retrieval_mode": record["retrieval_mode"],
        "content_score": int(content_score) if str(content_score).isdigit() else 0,
        "citation_score": int(citation_score) if str(citation_score).isdigit() else 0,
        "structure_score": int(structure_score) if str(structure_score).isdigit() else 0,
        "completeness_score": int(completeness_score) if str(completeness_score).isdigit() else 0,
        "hallucination_risk": hallucination_risk if hallucination_risk in {"none", "low", "medium", "high"} else "medium",
        "verdict": verdict if verdict in {"pass", "weak_pass", "fail"} else "fail",
        "evaluator_reason": evaluator_reason,
        "evaluator_model": eval_model,
        "score_source": "llm",
        "score_prompt_tokens": _safe_int(usage.get("prompt_tokens")),
        "score_completion_tokens": _safe_int(usage.get("completion_tokens")),
        "score_total_tokens": _safe_int(usage.get("total_tokens")),
        "score_latency_ms": latency_ms,
        "score_raw_content": content,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    content = text.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start : end + 1]
    return json.loads(content)


def score_mode_records(
    records: list[dict[str, Any]],
    *,
    eval_model: str,
    eval_api_base: str,
    eval_api_key: str,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    eval_session = requests.Session()
    eval_session.trust_env = True
    scored: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                score_single_answer,
                eval_session=eval_session,
                eval_model=eval_model,
                eval_api_base=eval_api_base,
                eval_api_key=eval_api_key,
                record=record,
            ): record
            for record in records
        }
        for future in as_completed(future_map):
            scored.append(future.result())
    scored.sort(key=lambda item: int(item["question_id"]))
    return scored


def load_run_records(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def attach_question_metadata(records: list[dict[str, Any]], questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    question_map = {int(question["question_id"]): question for question in questions}
    enriched: list[dict[str, Any]] = []
    for record in records:
        question_id = int(record["question_id"])
        merged = {**question_map.get(question_id, {}), **record}
        enriched.append(merged)
    return enriched


def _mean_non_null(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(mean(numeric), 3) if numeric else None


def summarize_mode(records: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> dict[str, Any]:
    merged_by_id = {int(record["question_id"]): record for record in records}
    judgments_by_id = {int(item["question_id"]): item for item in judgments}
    merged_records = []
    for question_id, record in merged_by_id.items():
        combined = {**record, **judgments_by_id.get(question_id, {})}
        merged_records.append(combined)
    merged_records.sort(key=lambda item: int(item["question_id"]))

    total = len(merged_records)
    completed = [record for record in merged_records if record.get("status") == "completed"]
    failed = [record for record in merged_records if record.get("status") != "completed"]
    content_scores = [record.get("content_score") for record in merged_records if record.get("content_score") is not None]
    citation_scores = [record.get("citation_score") for record in merged_records if record.get("citation_score") is not None]
    structure_scores = [record.get("structure_score") for record in merged_records if record.get("structure_score") is not None]
    completeness_scores = [record.get("completeness_score") for record in merged_records if record.get("completeness_score") is not None]
    total_elapsed = [float(record["total_elapsed_ms"]) for record in merged_records if record.get("total_elapsed_ms") is not None]
    ttft = [float(record["ttft_ms"]) for record in merged_records if record.get("ttft_ms") is not None]
    retrieval_ms = [float(record["retrieval_ms"]) for record in merged_records if record.get("retrieval_ms") is not None]
    build_context_ms = [float(record["build_context_ms"]) for record in merged_records if record.get("build_context_ms") is not None]
    final_answer_ms = [float(record["final_answer_ms"]) for record in merged_records if record.get("final_answer_ms") is not None]
    output_tokens = [int(record["output_tokens"]) for record in merged_records if record.get("output_tokens") is not None]
    output_tokens_per_sec = [float(record["output_tokens_per_sec"]) for record in merged_records if record.get("output_tokens_per_sec") is not None]
    input_tokens = [int(record["input_tokens"]) for record in merged_records if record.get("input_tokens") is not None]
    queue_ms = [float(record["queue_ms"]) for record in merged_records if record.get("queue_ms") is not None]
    sse_flush_lag = [float(record["sse_flush_lag_ms"]) for record in merged_records if record.get("sse_flush_lag_ms") is not None]

    verdict_counts = Counter(record.get("verdict") for record in merged_records)
    hallucination_counts = Counter(record.get("hallucination_risk") for record in merged_records)
    question_type_counts = Counter(record.get("question_type") for record in merged_records)
    difficulty_counts = Counter(record.get("difficulty") for record in merged_records)
    token_bucket_counts = Counter(_token_bucket(record.get("input_tokens")) for record in merged_records)
    latency_bucket_counts = Counter(_latency_bucket(record.get("total_elapsed_ms")) for record in merged_records)

    correlations = {
        "input_tokens_vs_final_answer_ms": _pearson(
            [float(record["input_tokens"]) for record in merged_records if record.get("input_tokens") is not None and record.get("final_answer_ms") is not None],
            [float(record["final_answer_ms"]) for record in merged_records if record.get("input_tokens") is not None and record.get("final_answer_ms") is not None],
        ),
        "input_tokens_vs_total_elapsed_ms": _pearson(
            [float(record["input_tokens"]) for record in merged_records if record.get("input_tokens") is not None and record.get("total_elapsed_ms") is not None],
            [float(record["total_elapsed_ms"]) for record in merged_records if record.get("input_tokens") is not None and record.get("total_elapsed_ms") is not None],
        ),
    }

    pass_count = sum(1 for record in judgments_by_id.values() if record.get("verdict") == "pass")
    weak_pass_count = sum(1 for record in judgments_by_id.values() if record.get("verdict") == "weak_pass")
    fail_count = sum(1 for record in judgments_by_id.values() if record.get("verdict") == "fail")

    return {
        "count": total,
        "completed_count": len(completed),
        "failed_count": len(failed),
        "verdict_counts": dict(verdict_counts),
        "hallucination_counts": dict(hallucination_counts),
        "question_type_counts": dict(question_type_counts),
        "difficulty_counts": dict(difficulty_counts),
        "token_bucket_counts": dict(token_bucket_counts),
        "latency_bucket_counts": dict(latency_bucket_counts),
        "content_score_avg": _mean_non_null(content_scores),
        "citation_score_avg": _mean_non_null(citation_scores),
        "structure_score_avg": _mean_non_null(structure_scores),
        "completeness_score_avg": _mean_non_null(completeness_scores),
        "pass_count": pass_count,
        "weak_pass_count": weak_pass_count,
        "fail_count": fail_count,
        "latency": {
            "total_elapsed_ms": _latency_summary(total_elapsed),
            "ttft_ms": _latency_summary(ttft),
            "retrieval_ms": _latency_summary(retrieval_ms),
            "build_context_ms": _latency_summary(build_context_ms),
            "final_answer_ms": _latency_summary(final_answer_ms),
            "queue_ms": _latency_summary(queue_ms),
            "sse_flush_lag_ms": _latency_summary(sse_flush_lag),
        },
        "output_tokens_avg": _mean_non_null([float(value) for value in output_tokens]),
        "output_tokens_per_sec_avg": _mean_non_null(output_tokens_per_sec),
        "input_tokens_avg": _mean_non_null([float(value) for value in input_tokens]),
        "correlations": correlations,
        "records": merged_records,
    }


def summarize_by_group(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get(key) or "unknown")].append(record)
    output: list[dict[str, Any]] = []
    for group_name, group_records in sorted(groups.items(), key=lambda item: item[0]):
        scores = [record.get("content_score") for record in group_records if record.get("content_score") is not None]
        verdicts = Counter(record.get("verdict") for record in group_records)
        output.append(
            {
                "group": group_name,
                "count": len(group_records),
                "pass_rate": round(verdicts.get("pass", 0) / len(group_records), 4) if group_records else None,
                "weak_pass_rate": round(verdicts.get("weak_pass", 0) / len(group_records), 4) if group_records else None,
                "fail_rate": round(verdicts.get("fail", 0) / len(group_records), 4) if group_records else None,
                "content_score_avg": _mean_non_null([float(value) for value in scores]),
                "citation_score_avg": _mean_non_null([float(record.get("citation_score")) for record in group_records if record.get("citation_score") is not None]),
                "structure_score_avg": _mean_non_null([float(record.get("structure_score")) for record in group_records if record.get("structure_score") is not None]),
                "completeness_score_avg": _mean_non_null([float(record.get("completeness_score")) for record in group_records if record.get("completeness_score") is not None]),
                "avg_total_elapsed_ms": _mean_non_null([record.get("total_elapsed_ms") for record in group_records]),
                "avg_ttft_ms": _mean_non_null([record.get("ttft_ms") for record in group_records]),
                "avg_output_tokens": _mean_non_null([record.get("output_tokens") for record in group_records]),
            }
        )
    return output


def summarize_fast_vs_deep(fast_records: list[dict[str, Any]], deep_records: list[dict[str, Any]]) -> dict[str, Any]:
    fast_by_id = {int(record["question_id"]): record for record in fast_records}
    deep_by_id = {int(record["question_id"]): record for record in deep_records}
    paired = []
    improvement = 0
    regression = 0
    same = 0
    for question_id in sorted(set(fast_by_id) & set(deep_by_id)):
        fast = fast_by_id[question_id]
        deep = deep_by_id[question_id]
        fast_score = (
            _safe_int(fast.get("content_score")),
            _safe_int(fast.get("citation_score")),
            _safe_int(fast.get("structure_score")),
            _safe_int(fast.get("completeness_score")),
        )
        deep_score = (
            _safe_int(deep.get("content_score")),
            _safe_int(deep.get("citation_score")),
            _safe_int(deep.get("structure_score")),
            _safe_int(deep.get("completeness_score")),
        )
        fast_sum = sum(value for value in fast_score if value is not None)
        deep_sum = sum(value for value in deep_score if value is not None)
        paired.append(
            {
                "question_id": question_id,
                "fast_verdict": fast.get("verdict"),
                "deep_verdict": deep.get("verdict"),
                "fast_total_elapsed_ms": fast.get("total_elapsed_ms"),
                "deep_total_elapsed_ms": deep.get("total_elapsed_ms"),
                "fast_ttft_ms": fast.get("ttft_ms"),
                "deep_ttft_ms": deep.get("ttft_ms"),
                "fast_score_sum": fast_sum,
                "deep_score_sum": deep_sum,
                "score_delta": deep_sum - fast_sum,
                "latency_delta_ms": _safe_float(deep.get("total_elapsed_ms")) - _safe_float(fast.get("total_elapsed_ms")) if deep.get("total_elapsed_ms") is not None and fast.get("total_elapsed_ms") is not None else None,
            }
        )
        if deep_sum > fast_sum:
            improvement += 1
        elif deep_sum < fast_sum:
            regression += 1
        else:
            same += 1
    return {
        "paired_count": len(paired),
        "improved_count": improvement,
        "regressed_count": regression,
        "same_count": same,
        "paired_records": paired,
    }


def classify_attribution(record: dict[str, Any]) -> dict[str, Any]:
    queue_ms = _safe_float(record.get("queue_ms")) or 0.0
    retrieval_ms = _safe_float(record.get("retrieval_ms")) or 0.0
    build_context_ms = _safe_float(record.get("build_context_ms")) or 0.0
    final_answer_ms = _safe_float(record.get("final_answer_ms")) or 0.0
    ttft_ms = _safe_float(record.get("ttft_ms")) or 0.0
    total_elapsed_ms = _safe_float(record.get("total_elapsed_ms")) or 0.0
    sse_flush_lag_ms = _safe_float(record.get("sse_flush_lag_ms")) or 0.0
    input_tokens = _safe_float(record.get("input_tokens")) or 0.0
    context_chars = _safe_float(record.get("context_chars")) or 0.0
    step_timings = record.get("step_timings") if isinstance(record.get("step_timings"), dict) else {}

    provider_decode_ms = max(final_answer_ms - ttft_ms, 0.0)
    context_pressure = input_tokens >= 4000 or context_chars >= 10000
    cause_scores = {
        "worker queue / concurrency contention": queue_ms,
        "retrieval 慢": retrieval_ms,
        "context build 慢": build_context_ms,
        "provider TTFT 慢": ttft_ms,
        "provider decode 慢": provider_decode_ms,
        "SSE/backend flush 慢": sse_flush_lag_ms,
        "prompt/context 过大": input_tokens / 1000.0 if context_pressure else 0.0,
    }
    if provider_decode_ms > 0 and ttft_ms <= 0:
        cause_scores["provider decode 慢"] += provider_decode_ms
    if isinstance(step_timings, dict) and "manual_gate" in step_timings:
        manual_gate = step_timings.get("manual_gate") or {}
        if isinstance(manual_gate, dict):
            manual_gate_duration = 0.0
            if manual_gate.get("started_ms") is not None and manual_gate.get("completed_ms") is not None:
                manual_gate_duration = float(manual_gate["completed_ms"]) - float(manual_gate["started_ms"])
            cause_scores["retrieval 慢"] += max(manual_gate_duration, 0.0) / 2.0
    dominant = max(cause_scores.items(), key=lambda item: item[1])[0] if cause_scores else "unknown"
    if cause_scores.get("prompt/context 过大", 0.0) >= max(cause_scores.get("retrieval 慢", 0.0), cause_scores.get("provider decode 慢", 0.0), 1.0):
        dominant = "prompt/context 过大"
    if queue_ms >= max(retrieval_ms, build_context_ms, final_answer_ms, ttft_ms, 1.0) * 0.25 and queue_ms >= 1000:
        dominant = "worker queue / concurrency contention"
    elif retrieval_ms >= max(build_context_ms, final_answer_ms, ttft_ms, 1.0) and retrieval_ms >= 1000:
        dominant = "retrieval 慢"
    elif build_context_ms >= max(retrieval_ms, final_answer_ms, ttft_ms, 1.0) and build_context_ms >= 1000:
        dominant = "context build 慢"
    elif ttft_ms >= 1500 and ttft_ms >= final_answer_ms * 0.5:
        dominant = "provider TTFT 慢"
    elif provider_decode_ms >= 1500 and provider_decode_ms >= ttft_ms * 0.6:
        dominant = "provider decode 慢"
    elif sse_flush_lag_ms >= 300:
        dominant = "SSE/backend flush 慢"
    return {
        "dominant_cause": dominant,
        "provider_decode_ms": round(provider_decode_ms, 3),
        "context_pressure": context_pressure,
        "total_elapsed_ms": total_elapsed_ms,
        "queue_ms": queue_ms,
        "retrieval_ms": retrieval_ms,
        "build_context_ms": build_context_ms,
        "final_answer_ms": final_answer_ms,
        "ttft_ms": ttft_ms,
        "sse_flush_lag_ms": sse_flush_lag_ms,
    }


def build_latency_summary(
    *,
    fast_records: list[dict[str, Any]],
    deep_records: list[dict[str, Any]],
    openai_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        total = [float(record["total_elapsed_ms"]) for record in records if record.get("total_elapsed_ms") is not None]
        ttft = [float(record["ttft_ms"]) for record in records if record.get("ttft_ms") is not None]
        retrieval = [float(record["retrieval_ms"]) for record in records if record.get("retrieval_ms") is not None]
        build_context = [float(record["build_context_ms"]) for record in records if record.get("build_context_ms") is not None]
        final_answer = [float(record["final_answer_ms"]) for record in records if record.get("final_answer_ms") is not None]
        output_tokens_per_sec = [float(record["output_tokens_per_sec"]) for record in records if record.get("output_tokens_per_sec") is not None]
        input_tokens = [int(record["input_tokens"]) for record in records if record.get("input_tokens") is not None]
        return {
            "count": len(records),
            "completed_count": sum(1 for record in records if record.get("status") == "completed"),
            "failed_count": sum(1 for record in records if record.get("status") != "completed"),
            "total_elapsed_ms": _latency_summary(total),
            "ttft_ms": _latency_summary(ttft),
            "retrieval_ms": _latency_summary(retrieval),
            "build_context_ms": _latency_summary(build_context),
            "final_answer_ms": _latency_summary(final_answer),
            "output_tokens_per_sec": _latency_summary(output_tokens_per_sec),
            "input_tokens_avg": _mean_non_null([float(value) for value in input_tokens]),
            "correlation_input_tokens_total_elapsed": _pearson(
                [float(record["input_tokens"]) for record in records if record.get("input_tokens") is not None and record.get("total_elapsed_ms") is not None],
                [float(record["total_elapsed_ms"]) for record in records if record.get("input_tokens") is not None and record.get("total_elapsed_ms") is not None],
            ),
        }

    summary = {
        "generated_at": utc_now_iso(),
        "fast": summarize(fast_records),
        "deep_research": summarize(deep_records),
    }
    if openai_records is not None:
        summary["openai_compat"] = summarize(openai_records)
    return summary


def write_latency_report(summary: dict[str, Any], question_count: int, openai_status: dict[str, Any]) -> None:
    lines = [
        "# B4.4 Skills Chat Latency Report",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Question count: {question_count}",
        f"- OpenAI-compatible interface: {openai_status.get('reason', 'unknown')}",
        "",
        "## FastSearch",
        f"- p50 total elapsed: {format_ms(summary['fast']['total_elapsed_ms']['p50_ms'])} ms",
        f"- p95 total elapsed: {format_ms(summary['fast']['total_elapsed_ms']['p95_ms'])} ms",
        f"- max total elapsed: {format_ms(summary['fast']['total_elapsed_ms']['max_ms'])} ms",
        f"- TTFT p50/p95/max: {format_ms(summary['fast']['ttft_ms']['p50_ms'])} / {format_ms(summary['fast']['ttft_ms']['p95_ms'])} / {format_ms(summary['fast']['ttft_ms']['max_ms'])} ms",
        f"- output tokens/sec avg: {format_ms(summary['fast']['output_tokens_per_sec']['avg_ms'])}",
        "",
        "## DeepResearch",
        f"- p50 total elapsed: {format_ms(summary['deep_research']['total_elapsed_ms']['p50_ms'])} ms",
        f"- p95 total elapsed: {format_ms(summary['deep_research']['total_elapsed_ms']['p95_ms'])} ms",
        f"- max total elapsed: {format_ms(summary['deep_research']['total_elapsed_ms']['max_ms'])} ms",
        f"- TTFT p50/p95/max: {format_ms(summary['deep_research']['ttft_ms']['p50_ms'])} / {format_ms(summary['deep_research']['ttft_ms']['p95_ms'])} / {format_ms(summary['deep_research']['ttft_ms']['max_ms'])} ms",
        f"- output tokens/sec avg: {format_ms(summary['deep_research']['output_tokens_per_sec']['avg_ms'])}",
        "",
    ]
    write_json(LATENCY_SUMMARY_PATH, summary)
    LATENCY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_eval_report(eval_summary: dict[str, Any], openai_status: dict[str, Any]) -> None:
    lines = [
        "# B4.4 Skills Chat Quality Report",
        "",
        f"- Generated at: {eval_summary['generated_at']}",
        f"- OpenAI-compatible interface: {openai_status.get('reason', 'unknown')}",
        "",
        "## Overall",
        f"- Fast pass rate: {format_ms(eval_summary['by_retrieval_mode']['fast']['pass_rate'] * 100 if eval_summary['by_retrieval_mode']['fast']['pass_rate'] is not None else None)}%",
        f"- Deep pass rate: {format_ms(eval_summary['by_retrieval_mode']['deep_research']['pass_rate'] * 100 if eval_summary['by_retrieval_mode']['deep_research']['pass_rate'] is not None else None)}%",
        "",
        "## Fast vs Deep",
        f"- Paired count: {eval_summary['fast_vs_deep']['paired_count']}",
        f"- Improved: {eval_summary['fast_vs_deep']['improved_count']}",
        f"- Regressed: {eval_summary['fast_vs_deep']['regressed_count']}",
        "",
        f"## GO/NO-GO: {eval_summary['go_no_go']['status']}",
        f"- Reason: {eval_summary['go_no_go']['reason']}",
        "",
    ]
    write_json(EVAL_SUMMARY_PATH, eval_summary)
    EVAL_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def build_eval_summary(
    *,
    fast_records: list[dict[str, Any]],
    deep_records: list[dict[str, Any]],
    fast_judgments: list[dict[str, Any]],
    deep_judgments: list[dict[str, Any]],
    openai_records: list[dict[str, Any]] | None,
    openai_judgments: list[dict[str, Any]] | None,
    openai_status: dict[str, Any],
) -> dict[str, Any]:
    fast_summary = summarize_mode(fast_records, fast_judgments)
    deep_summary = summarize_mode(deep_records, deep_judgments)
    by_retrieval_mode = {
        "fast": {
            "count": fast_summary["count"],
            "pass_rate": round(fast_summary["pass_count"] / fast_summary["count"], 4) if fast_summary["count"] else None,
            "weak_pass_rate": round(fast_summary["weak_pass_count"] / fast_summary["count"], 4) if fast_summary["count"] else None,
            "fail_rate": round(fast_summary["fail_count"] / fast_summary["count"], 4) if fast_summary["count"] else None,
            "content_score_avg": fast_summary["content_score_avg"],
            "citation_score_avg": fast_summary["citation_score_avg"],
            "structure_score_avg": fast_summary["structure_score_avg"],
            "completeness_score_avg": fast_summary["completeness_score_avg"],
        },
        "deep_research": {
            "count": deep_summary["count"],
            "pass_rate": round(deep_summary["pass_count"] / deep_summary["count"], 4) if deep_summary["count"] else None,
            "weak_pass_rate": round(deep_summary["weak_pass_count"] / deep_summary["count"], 4) if deep_summary["count"] else None,
            "fail_rate": round(deep_summary["fail_count"] / deep_summary["count"], 4) if deep_summary["count"] else None,
            "content_score_avg": deep_summary["content_score_avg"],
            "citation_score_avg": deep_summary["citation_score_avg"],
            "structure_score_avg": deep_summary["structure_score_avg"],
            "completeness_score_avg": deep_summary["completeness_score_avg"],
        },
    }

    by_question_type = summarize_by_group(fast_summary["records"] + deep_summary["records"], "question_type")
    by_difficulty = summarize_by_group(fast_summary["records"] + deep_summary["records"], "difficulty")
    by_token_bucket = summarize_by_group(fast_summary["records"] + deep_summary["records"], "_token_bucket")
    by_citation_correctness = summarize_by_group(
        [
            {
                **record,
                "_citation_bucket": "correct" if int(record.get("citation_score") or 0) >= 2 else "incorrect",
            }
            for record in fast_summary["records"] + deep_summary["records"]
        ],
        "_citation_bucket",
    )
    by_latency_bucket = summarize_by_group(
        [
            {
                **record,
                "_latency_bucket": _latency_bucket(record.get("total_elapsed_ms")),
            }
            for record in fast_summary["records"] + deep_summary["records"]
        ],
        "_latency_bucket",
    )

    fast_vs_deep = summarize_fast_vs_deep(fast_summary["records"], deep_summary["records"])

    merged_records = fast_summary["records"] + deep_summary["records"]
    slow_cases = sorted(
        [record for record in merged_records if record.get("status") == "completed"],
        key=lambda item: float(item.get("total_elapsed_ms") or 0.0),
        reverse=True,
    )[:15]
    wrong_cases = sorted(
        [record for record in deep_summary["records"] + fast_summary["records"]],
        key=lambda item: (
            int(item.get("content_score") or 0),
            int(item.get("citation_score") or 0),
            int(item.get("structure_score") or 0),
            int(item.get("completeness_score") or 0),
            0 if item.get("hallucination_risk") == "high" else 1,
        ),
    )[:15]

    slow_case_summaries = [
        {
            "question_id": record["question_id"],
            "retrieval_mode": record["retrieval_mode"],
            "question": record["question"],
            "total_elapsed_ms": record.get("total_elapsed_ms"),
            "ttft_ms": record.get("ttft_ms"),
            "retrieval_ms": record.get("retrieval_ms"),
            "build_context_ms": record.get("build_context_ms"),
            "final_answer_ms": record.get("final_answer_ms"),
            "queue_ms": record.get("queue_ms"),
            "dominant_cause": classify_attribution(record)["dominant_cause"],
            "question_type": record.get("question_type"),
            "difficulty": record.get("difficulty"),
        }
        for record in slow_cases
    ]
    wrong_case_summaries = [
        {
            "question_id": record["question_id"],
            "retrieval_mode": record["retrieval_mode"],
            "question": record["question"],
            "content_score": record.get("content_score"),
            "citation_score": record.get("citation_score"),
            "structure_score": record.get("structure_score"),
            "completeness_score": record.get("completeness_score"),
            "hallucination_risk": record.get("hallucination_risk"),
            "verdict": record.get("verdict"),
            "evaluator_reason": record.get("evaluator_reason"),
        }
        for record in wrong_cases
    ]

    go_no_go_reason_parts = []
    if fast_summary["pass_count"] < len(fast_summary["records"]) * 0.7:
        go_no_go_reason_parts.append("FastSearch 通过率低于 70%")
    if deep_summary["pass_count"] < len(deep_summary["records"]) * 0.7:
        go_no_go_reason_parts.append("DeepResearch 通过率低于 70%")
    if _safe_float(deep_summary["latency"]["total_elapsed_ms"]["p95_ms"]) and _safe_float(fast_summary["latency"]["total_elapsed_ms"]["p95_ms"]):
        if float(deep_summary["latency"]["total_elapsed_ms"]["p95_ms"]) > float(fast_summary["latency"]["total_elapsed_ms"]["p95_ms"]) * 2.5:
            go_no_go_reason_parts.append("DeepResearch p95 远高于 FastSearch")
    if fast_vs_deep["improved_count"] < fast_vs_deep["regressed_count"]:
        go_no_go_reason_parts.append("DeepResearch 相比 FastSearch 的质量提升不足")
    if openai_status.get("available"):
        go_no_go_reason_parts.append("OpenAI-compatible 路径存在，需要单独审计")
    if not go_no_go_reason_parts:
        go_no_go_status = "GO"
        go_no_go_reason = "FastSearch 与 DeepResearch 都达到基础可用阈值，且瓶颈可通过最小修复定位。"
    else:
        go_no_go_status = "NO-GO"
        go_no_go_reason = "；".join(go_no_go_reason_parts)

    return {
        "generated_at": utc_now_iso(),
        "by_retrieval_mode": by_retrieval_mode,
        "by_question_type": by_question_type,
        "by_difficulty": by_difficulty,
        "by_token_bucket": by_token_bucket,
        "by_citation_correctness": by_citation_correctness,
        "by_latency_bucket": by_latency_bucket,
        "fast_vs_deep": fast_vs_deep,
        "correlations": {
            "fast": fast_summary["correlations"],
            "deep_research": deep_summary["correlations"],
        },
        "latency": {
            "fast": fast_summary["latency"],
            "deep_research": deep_summary["latency"],
        },
        "slow_cases": slow_case_summaries,
        "wrong_cases": wrong_case_summaries,
        "openai_compat": openai_status,
        "go_no_go": {
            "status": go_no_go_status,
            "reason": go_no_go_reason,
            "minimum_fix": [
                "把 build_context 独立成可观测的后端步骤并输出实际 context_block_count/context_chars。",
                "如果 DeepResearch 主要卡在 provider TTFT 或 decode，优先压缩上下文而不是改检索逻辑。",
                "如果 queue_ms 偏高，先拆 worker 竞争和并发控制，再看检索链路。",
            ],
        },
    }


def write_judgments_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    write_jsonl(path, records)


def build_markdown_from_summary(latency_summary: dict[str, Any], eval_summary: dict[str, Any]) -> None:
    lines = [
        "# B4.4 Skills Chat Harness Report",
        "",
        f"- Generated at: {latency_summary['generated_at']}",
        f"- OpenAI-compatible interface: {eval_summary['openai_compat'].get('reason', 'unknown')}",
        "",
        "## Latency",
        "",
        "| Mode | p50 total | p95 total | max total | p50 TTFT | p95 TTFT | max TTFT | output tok/s avg |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("fast", "deep_research"):
        lat = latency_summary[mode]
        lines.append(
            f"| {mode} | {format_ms(lat['total_elapsed_ms']['p50_ms'])} | {format_ms(lat['total_elapsed_ms']['p95_ms'])} | {format_ms(lat['total_elapsed_ms']['max_ms'])} | "
            f"{format_ms(lat['ttft_ms']['p50_ms'])} | {format_ms(lat['ttft_ms']['p95_ms'])} | {format_ms(lat['ttft_ms']['max_ms'])} | {format_ms(lat['output_tokens_per_sec']['avg_ms'])} |"
        )
    lines.extend(
        [
            "",
            "## Quality",
            "",
            "| Mode | Pass rate | Weak pass rate | Fail rate | Content | Citation | Structure | Completeness |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in ("fast", "deep_research"):
        mode_summary = eval_summary["by_retrieval_mode"][mode]
        lines.append(
            f"| {mode} | {format_ms(mode_summary['pass_rate'] * 100 if mode_summary['pass_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['weak_pass_rate'] * 100 if mode_summary['weak_pass_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['fail_rate'] * 100 if mode_summary['fail_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['content_score_avg'])} | {format_ms(mode_summary['citation_score_avg'])} | {format_ms(mode_summary['structure_score_avg'])} | {format_ms(mode_summary['completeness_score_avg'])} |"
        )
    lines.extend(
        [
            "",
            f"## GO/NO-GO: {eval_summary['go_no_go']['status']}",
            f"- {eval_summary['go_no_go']['reason']}",
            "",
            "## Minimal Fixes",
        ]
    )
    for fix in eval_summary["go_no_go"]["minimum_fix"]:
        lines.append(f"- {fix}")
    LATENCY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    EVAL_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def build_and_write_reports(
    *,
    questions: list[dict[str, Any]],
    fast_records: list[dict[str, Any]],
    deep_records: list[dict[str, Any]],
    openai_records: list[dict[str, Any]] | None,
    openai_status: dict[str, Any],
    fast_judgments: list[dict[str, Any]],
    deep_judgments: list[dict[str, Any]],
    openai_judgments: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    latency_summary = build_latency_summary(fast_records=fast_records, deep_records=deep_records, openai_records=openai_records)
    write_json(LATENCY_SUMMARY_PATH, latency_summary)
    eval_summary = build_eval_summary(
        fast_records=fast_records,
        deep_records=deep_records,
        fast_judgments=fast_judgments,
        deep_judgments=deep_judgments,
        openai_records=openai_records,
        openai_judgments=openai_judgments,
        openai_status=openai_status,
    )
    write_json(EVAL_SUMMARY_PATH, eval_summary)

    latency_report = [
        "# B4.4 Skills Chat Latency Report",
        "",
        f"- Generated at: {latency_summary['generated_at']}",
        f"- Questions: {len(questions)}",
        f"- OpenAI-compatible interface: {openai_status.get('reason', 'unknown')}",
        "",
        "## FastSearch",
        f"- p50 total elapsed: {format_ms(latency_summary['fast']['total_elapsed_ms']['p50_ms'])} ms",
        f"- p95 total elapsed: {format_ms(latency_summary['fast']['total_elapsed_ms']['p95_ms'])} ms",
        f"- max total elapsed: {format_ms(latency_summary['fast']['total_elapsed_ms']['max_ms'])} ms",
        f"- TTFT p50/p95/max: {format_ms(latency_summary['fast']['ttft_ms']['p50_ms'])} / {format_ms(latency_summary['fast']['ttft_ms']['p95_ms'])} / {format_ms(latency_summary['fast']['ttft_ms']['max_ms'])} ms",
        f"- output tokens/sec avg: {format_ms(latency_summary['fast']['output_tokens_per_sec']['avg_ms'])}",
        "",
        "## DeepResearch",
        f"- p50 total elapsed: {format_ms(latency_summary['deep_research']['total_elapsed_ms']['p50_ms'])} ms",
        f"- p95 total elapsed: {format_ms(latency_summary['deep_research']['total_elapsed_ms']['p95_ms'])} ms",
        f"- max total elapsed: {format_ms(latency_summary['deep_research']['total_elapsed_ms']['max_ms'])} ms",
        f"- TTFT p50/p95/max: {format_ms(latency_summary['deep_research']['ttft_ms']['p50_ms'])} / {format_ms(latency_summary['deep_research']['ttft_ms']['p95_ms'])} / {format_ms(latency_summary['deep_research']['ttft_ms']['max_ms'])} ms",
        f"- output tokens/sec avg: {format_ms(latency_summary['deep_research']['output_tokens_per_sec']['avg_ms'])}",
        "",
    ]
    LATENCY_REPORT_PATH.write_text("\n".join(latency_report), encoding="utf-8")

    eval_report = [
        "# B4.4 Skills Chat Quality Report",
        "",
        f"- Generated at: {eval_summary['generated_at']}",
        f"- OpenAI-compatible interface: {openai_status.get('reason', 'unknown')}",
        "",
        "## Retrieval Modes",
        "",
        "| Mode | Count | Pass rate | Weak pass rate | Fail rate | Content avg | Citation avg | Structure avg | Completeness avg |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("fast", "deep_research"):
        mode_summary = eval_summary["by_retrieval_mode"][mode]
        eval_report.append(
            f"| {mode} | {mode_summary['count']} | {format_ms(mode_summary['pass_rate'] * 100 if mode_summary['pass_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['weak_pass_rate'] * 100 if mode_summary['weak_pass_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['fail_rate'] * 100 if mode_summary['fail_rate'] is not None else None)}% | "
            f"{format_ms(mode_summary['content_score_avg'])} | {format_ms(mode_summary['citation_score_avg'])} | {format_ms(mode_summary['structure_score_avg'])} | {format_ms(mode_summary['completeness_score_avg'])} |"
        )
    eval_report.extend(
        [
            "",
            "## Fast vs Deep",
            f"- Paired count: {eval_summary['fast_vs_deep']['paired_count']}",
            f"- Improved: {eval_summary['fast_vs_deep']['improved_count']}",
            f"- Regressed: {eval_summary['fast_vs_deep']['regressed_count']}",
            "",
            f"## GO/NO-GO: {eval_summary['go_no_go']['status']}",
            f"- {eval_summary['go_no_go']['reason']}",
            "",
            "## Minimal Fixes",
        ]
    )
    for fix in eval_summary["go_no_go"]["minimum_fix"]:
        eval_report.append(f"- {fix}")
    EVAL_REPORT_PATH.write_text("\n".join(eval_report), encoding="utf-8")
    return latency_summary, eval_summary


def load_question_artifacts() -> list[dict[str, Any]]:
    questions = read_json(QUESTION_OUTPUT_PATH, None)
    if isinstance(questions, list) and questions:
        return questions
    generated = generate_question_set()
    persist_question_artifacts(generated)
    return generated


def flatten_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: int(item["question_id"]))


def run_all(args: argparse.Namespace) -> int:
    helpers = HELPERS
    helpers.load_env_files()
    api_base = args.api_base or resolve_api_base()
    api_key = args.api_key or require_pageindex_api_key()

    question_set = load_question_artifacts()
    persist_question_artifacts(question_set)

    local_session = requests.Session()
    local_session.trust_env = False
    skill_id = resolve_skill_id(args.skill_id, api_base, local_session)
    auth_headers = {"X-API-Key": api_key}

    openai_status = try_probe_openai_compat_interface(api_base, auth_headers, local_session)

    modes = [mode.strip() for mode in (args.modes or "fast,deep_research").split(",") if mode.strip()]
    if "fast" not in modes:
        modes.insert(0, "fast")
    if "deep_research" not in modes:
        modes.append("deep_research")

    fast_records: list[dict[str, Any]] = []
    deep_records: list[dict[str, Any]] = []
    openai_records: list[dict[str, Any]] | None = None

    if "fast" in modes:
        fast_records = run_mode(
            mode="fast",
            questions=question_set,
            api_base=api_base,
            skill_id=skill_id,
            auth_headers=auth_headers,
            workers=args.workers,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    if "deep_research" in modes:
        deep_records = run_mode(
            mode="deep_research",
            questions=question_set,
            api_base=api_base,
            skill_id=skill_id,
            auth_headers=auth_headers,
            workers=args.workers,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    if openai_status.get("available"):
        # The current repository does not expose an OpenAI-compatible route; this path is present for completeness only.
        openai_records = []
    else:
        openai_records = None
        if RUN_OUTPUT_OPENAI_COMPAT_PATH.exists():
            RUN_OUTPUT_OPENAI_COMPAT_PATH.unlink()

    # Re-attach the latest question metadata so downstream scoring uses the current
    # expected_answer summaries even when run artifacts were produced earlier.
    fast_records = attach_question_metadata(fast_records, question_set) if fast_records else fast_records
    deep_records = attach_question_metadata(deep_records, question_set) if deep_records else deep_records
    if openai_records:
        openai_records = attach_question_metadata(openai_records, question_set)

    fast_judgments: list[dict[str, Any]] = []
    deep_judgments: list[dict[str, Any]] = []
    openai_judgments: list[dict[str, Any]] | None = None

    eval_model, eval_api_key, eval_api_base = resolve_eval_settings()
    if not eval_api_key:
        raise SystemExit("DeepSeek evaluation API key is required. Set DEEPSEEK_API_KEY or PAGEINDEX_EVAL_API_KEY.")

    if fast_records:
        fast_judgments = score_mode_records(
            fast_records,
            eval_model=eval_model,
            eval_api_base=eval_api_base,
            eval_api_key=eval_api_key,
            max_workers=args.eval_workers,
        )
    if deep_records:
        deep_judgments = score_mode_records(
            deep_records,
            eval_model=eval_model,
            eval_api_base=eval_api_base,
            eval_api_key=eval_api_key,
            max_workers=args.eval_workers,
        )
    if openai_records:
        openai_judgments = score_mode_records(
            openai_records,
            eval_model=eval_model,
            eval_api_base=eval_api_base,
            eval_api_key=eval_api_key,
            max_workers=args.eval_workers,
        )

    write_jsonl(JUDGMENT_OUTPUT_PATH, fast_judgments + deep_judgments + (openai_judgments or []))
    latency_summary, eval_summary = build_and_write_reports(
        questions=question_set,
        fast_records=fast_records,
        deep_records=deep_records,
        openai_records=openai_records,
        openai_status=openai_status,
        fast_judgments=fast_judgments,
        deep_judgments=deep_judgments,
        openai_judgments=openai_judgments,
    )
    print(json.dumps({"latency_summary": latency_summary, "eval_summary": eval_summary}, ensure_ascii=False, indent=2))
    return 0


def run_generate(args: argparse.Namespace) -> int:
    helpers = HELPERS
    helpers.load_env_files()
    question_set = generate_question_set()
    persist_question_artifacts(question_set)
    print(json.dumps({"question_count": len(question_set), "output": str(QUESTION_OUTPUT_PATH)}, ensure_ascii=False, indent=2))
    return 0


def run_summary(args: argparse.Namespace) -> int:
    question_set = load_question_artifacts()
    fast_records = load_run_records(RUN_OUTPUT_FAST_PATH)
    deep_records = load_run_records(RUN_OUTPUT_DEEP_PATH)
    openai_records = load_run_records(RUN_OUTPUT_OPENAI_COMPAT_PATH) if RUN_OUTPUT_OPENAI_COMPAT_PATH.exists() else None
    fast_records = attach_question_metadata(fast_records, question_set) if fast_records else fast_records
    deep_records = attach_question_metadata(deep_records, question_set) if deep_records else deep_records
    if openai_records:
        openai_records = attach_question_metadata(openai_records, question_set)
    fast_judgments = read_jsonl(JUDGMENT_OUTPUT_PATH)
    deep_judgments = []
    if fast_judgments:
        fast_judgments = [record for record in fast_judgments if record.get("retrieval_mode") == "fast"]
        deep_judgments = [record for record in read_jsonl(JUDGMENT_OUTPUT_PATH) if record.get("retrieval_mode") == "deep_research"]
    openai_status = try_probe_openai_compat_interface(resolve_api_base(), {"X-API-Key": require_pageindex_api_key()}, requests.Session())
    latency_summary, eval_summary = build_and_write_reports(
        questions=question_set,
        fast_records=fast_records,
        deep_records=deep_records,
        openai_records=openai_records,
        openai_status=openai_status,
        fast_judgments=fast_judgments,
        deep_judgments=deep_judgments,
        openai_judgments=None,
    )
    print(json.dumps({"latency_summary": latency_summary, "eval_summary": eval_summary}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="B4.4 Skills Chat Fast/Deep latency + quality harness")
    parser.add_argument("--skill-id", default=os.getenv("PAGEINDEX_SKILL_ID", "").strip() or None)
    parser.add_argument("--api-base", default=None, help="PageIndex API base, e.g. http://localhost:8000/api/v1 or http://localhost:8000")
    parser.add_argument("--api-key", default=None, help="PageIndex API key; defaults to PAGEINDEX_API_KEY or SKILL_RUN_API_KEY")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKER_COUNT)
    parser.add_argument("--eval-workers", type=int, default=DEFAULT_WORKER_COUNT)
    parser.add_argument("--request-timeout-seconds", type=int, default=3600)
    parser.add_argument("--modes", default="fast,deep_research", help="Comma-separated retrieval modes to run")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("generate-questions")
    subparsers.add_parser("run")
    subparsers.add_parser("summary")
    subparsers.add_parser("all")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "all"
    if command == "generate-questions":
        return run_generate(args)
    if command == "run":
        return run_all(args) if args.modes else run_all(args)
    if command == "summary":
        return run_summary(args)
    return run_all(args)


if __name__ == "__main__":
    raise SystemExit(main())
