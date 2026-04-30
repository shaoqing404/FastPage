#!/usr/bin/env python3
"""Direct DeepSeek/LiteLLM latency probe for B4.4.

This script intentionally reads API credentials only from the environment.
It builds a prompt that mirrors PageIndex's final-answer prompt shape and
records streaming timing without going through Skills Chat.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm


QUESTION = "同一航班上，无成人陪伴儿童（8 岁）最多可承运几名？其中 5 至 10 岁年龄段有何特别限制？"


def _selected_sections(markdown: str) -> str:
    sections: list[str] = []
    pattern = re.compile(
        r"^# Fast Search Result \d+\n"
        r"Title: (?P<title>.+?)\n"
        r"Node ID: (?P<node_id>.+?)\n"
        r"Pages: (?P<pages>.+?)\n",
        re.MULTILINE,
    )
    for match in pattern.finditer(markdown):
        title = match.group("title").strip()
        pages = match.group("pages").strip()
        sections.append(f"- {title} ({pages})")
    return "\n".join(sections)


def build_prompt(context_markdown: str) -> str:
    selected_sections = _selected_sections(context_markdown)
    return f"""Answer the question using only the provided PDF excerpts.

Question:
{QUESTION}

Selected sections:
{selected_sections}

PDF excerpts:
{context_markdown}

Requirements:
- Be concise and factual.
- If the answer is a list, present the list directly.
- Cite page numbers in parentheses, like (pages 353-360).
- If the excerpts are insufficient, say so explicitly.
"""


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if not usage:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    data: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            data[key] = value
    return data or None


def run_probe(
    *,
    prompt: str,
    model: str,
    api_base: str,
    stream: bool,
    thinking: bool,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": stream,
        "api_base": api_base,
        "api_key": api_key,
    }
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    if thinking:
        kwargs["thinking"] = {"type": "enabled"}
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

    started = time.perf_counter()
    first_delta_ms: int | None = None
    first_chunk_ms: int | None = None
    delta_count = 0
    nonempty_delta_count = 0
    max_delta_gap_ms = 0
    last_delta_at: float | None = None
    answer_parts: list[str] = []
    usage: dict[str, Any] | None = None

    if stream:
        response = litellm.completion(**kwargs)
        for chunk in response:
            now = time.perf_counter()
            if first_chunk_ms is None:
                first_chunk_ms = int((now - started) * 1000)
            chunk_usage = _usage_to_dict(getattr(chunk, "usage", None))
            if chunk_usage:
                usage = chunk_usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = ""
            if getattr(choice, "delta", None) is not None:
                delta = getattr(choice.delta, "content", None) or ""
            delta_count += 1
            if not delta:
                continue
            if first_delta_ms is None:
                first_delta_ms = int((now - started) * 1000)
            if last_delta_at is not None:
                gap_ms = int((now - last_delta_at) * 1000)
                max_delta_gap_ms = max(max_delta_gap_ms, gap_ms)
            last_delta_at = now
            nonempty_delta_count += 1
            answer_parts.append(delta)
        ended = time.perf_counter()
    else:
        response = litellm.completion(**kwargs)
        ended = time.perf_counter()
        usage = _usage_to_dict(getattr(response, "usage", None))
        choices = getattr(response, "choices", None) or []
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None) if message is not None else None
            if content:
                answer_parts.append(content)

    answer = "".join(answer_parts)
    total_ms = int((ended - started) * 1000)
    completion_tokens = (usage or {}).get("completion_tokens")
    tokens_per_sec = None
    if completion_tokens and total_ms > 0:
        tokens_per_sec = round(float(completion_tokens) / (total_ms / 1000), 3)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "api_base": api_base,
        "stream": stream,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort if thinking else None,
        "prompt_chars": len(prompt),
        "first_chunk_ms": first_chunk_ms,
        "ttft_ms": first_delta_ms,
        "total_ms": total_ms,
        "answer_ms_from_first_delta": total_ms - first_delta_ms if first_delta_ms is not None else None,
        "delta_count": delta_count if stream else None,
        "nonempty_delta_count": nonempty_delta_count if stream else None,
        "max_delta_gap_ms": max_delta_gap_ms if stream else None,
        "usage": usage,
        "tokens_per_sec_total": tokens_per_sec,
        "answer_chars": len(answer),
        "answer_preview": answer[:800],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-file", default="scripts/testforFastSearch5.md")
    parser.add_argument("--out", default=None)
    parser.add_argument("--model", default="openai/deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--include-thinking", action="store_true")
    parser.add_argument("--reasoning-effort", default="high")
    args = parser.parse_args()

    context = Path(args.context_file).read_text(encoding="utf-8")
    prompt = build_prompt(context)
    probes = [
        run_probe(
            prompt=prompt,
            model=args.model,
            api_base=args.api_base,
            stream=True,
            thinking=False,
            reasoning_effort=None,
        ),
        run_probe(
            prompt=prompt,
            model=args.model,
            api_base=args.api_base,
            stream=False,
            thinking=False,
            reasoning_effort=None,
        ),
    ]
    if args.include_thinking:
        probes.append(
            run_probe(
                prompt=prompt,
                model=args.model,
                api_base=args.api_base,
                stream=True,
                thinking=True,
                reasoning_effort=args.reasoning_effort,
            )
        )

    out = {
        "question": QUESTION,
        "context_file": args.context_file,
        "probes": probes,
    }
    out_path = Path(args.out) if args.out else Path("results") / (
        "b4_4_deepseek_direct_probe_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
