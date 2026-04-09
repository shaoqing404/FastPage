import asyncio
import json
import time

from pageindex.page_index import page_index_main
from pageindex.utils import (
    ConfigLoader,
    count_tokens,
    extract_json,
    get_page_tokens,
    get_text_of_pdf_pages_with_labels,
    llm_completion,
    structure_to_list,
)
from app.services.storage_service import read_json_artifact


def parse_pdf_to_structure(pdf_path: str, model: str) -> dict:
    opt = ConfigLoader().load(
        {
            "model": model,
            "if_add_node_summary": "no",
            "if_add_doc_description": "no",
            "if_add_node_text": "no",
            "if_add_node_id": "yes",
        }
    )
    return page_index_main(pdf_path, opt)


def build_outline_prompt(structure: list[dict], question: str) -> str:
    lines = []
    for node in structure_to_list(structure):
        lines.append(
            f"{node.get('node_id', '')} | {node.get('start_index')}-{node.get('end_index')} | {node.get('title', '')}"
        )
    outline_text = "\n".join(lines)
    return f"""
You are selecting the most relevant sections of a PDF outline for answering a user question.

Question:
{question}

Outline entries:
{outline_text}

Return JSON only in this format:
{{
  "node_ids": ["0001", "0002"],
  "why": "short reason"
}}

Rules:
- Select 1 to 5 node_ids.
- Prefer the most specific nodes over broad parent nodes.
- Only use node_ids that appear in the outline list.
"""


def choose_relevant_nodes_lexical(structure: list[dict], question: str, top_k: int) -> list[dict]:
    flat_nodes = [node for node in structure_to_list(structure) if node.get("node_id")]
    lowered_tokens = [token for token in question.lower().split() if token]
    scored = []
    for node in flat_nodes:
        title = (node.get("title") or "").lower()
        score = sum(1 for token in lowered_tokens if token in title)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [node for _, node in scored[:top_k]]
    if not selected:
        selected = flat_nodes[:top_k]
    return selected


def choose_relevant_nodes(
    structure: list[dict],
    question: str,
    model: str,
    request_options: dict | None = None,
    trace_hook=None,
    stats_hook=None,
    top_k: int = 5,
    selection_mode: str = "outline_llm",
) -> list[dict]:
    flat_nodes = {node["node_id"]: node for node in structure_to_list(structure) if node.get("node_id")}
    if selection_mode == "lexical_fallback":
        return choose_relevant_nodes_lexical(structure, question, top_k)
    response = llm_completion(
        model=model,
        prompt=build_outline_prompt(structure, question),
        request_options=request_options,
        trace_hook=trace_hook,
        trace_label="outline_selection",
        stats_hook=stats_hook,
    )
    payload = extract_json(response)
    node_ids = payload.get("node_ids", []) if isinstance(payload, dict) else []
    selected = [flat_nodes[node_id] for node_id in node_ids if node_id in flat_nodes][:top_k]

    if not selected:
        selected = choose_relevant_nodes_lexical(structure, question, top_k)

    if not selected:
        selected = list(flat_nodes.values())[:top_k]

    return selected


def build_answer_context(
    selected_nodes: list[dict],
    pdf_path: str,
    model: str,
    *,
    max_context_pages: int | None = None,
    max_context_tokens: int | None = None,
) -> str:
    pdf_pages = get_page_tokens(pdf_path, model=model)
    chunks = []
    seen = set()
    total_pages = 0
    total_tokens = 0
    for node in selected_nodes:
        start_index = node.get("start_index")
        end_index = node.get("end_index")
        if start_index is None or end_index is None:
            continue
        key = (start_index, end_index)
        if key in seen:
            continue
        seen.add(key)
        page_count = int(end_index) - int(start_index) + 1
        if max_context_pages is not None and total_pages + page_count > max_context_pages:
            break
        section_text = get_text_of_pdf_pages_with_labels(pdf_pages, start_index, end_index)
        section_tokens = sum(pdf_pages[page_num][1] for page_num in range(start_index - 1, end_index))
        if max_context_tokens is not None and chunks and total_tokens + section_tokens > max_context_tokens:
            break
        chunks.append(f"## Section: {node.get('title')} (pages {start_index}-{end_index})\n{section_text}")
        total_pages += page_count
        total_tokens += section_tokens
    return "\n\n".join(chunks)


def build_answer_prompt(question: str, selected_nodes: list[dict], context: str, system_prompt: str | None = None) -> str:
    section_list = "\n".join(
        f"- {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})" for node in selected_nodes
    )
    extra = f"System instruction:\n{system_prompt}\n\n" if system_prompt else ""
    return f"""
{extra}Answer the question using only the provided PDF excerpts.

Question:
{question}

Selected sections:
{section_list}

PDF excerpts:
{context}

Requirements:
- Be concise and factual.
- If the answer is a list, present the list directly.
- Cite page numbers in parentheses, like (pages 353-360).
- If the excerpts are insufficient, say so explicitly.
"""


def build_query_rewrite_prompt(question: str, history_context: str) -> str:
    return f"""
Rewrite the user's latest question into a standalone retrieval query using the recent conversation context.

Conversation context:
{history_context}

Latest user question:
{question}

Return JSON only:
{{
  "rewritten_query": "..."
}}

Rules:
- Preserve concrete entities, constraints, and referents from the conversation.
- Keep the rewritten query concise and retrieval-friendly.
- If no rewrite is needed, return the original question.
"""


def build_generation_prompt(
    question: str,
    selected_nodes: list[dict],
    context: str,
    *,
    system_prompt: str | None = None,
    history_context: str | None = None,
) -> str:
    section_list = "\n".join(
        f"- {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})" for node in selected_nodes
    )
    extra = f"System instruction:\n{system_prompt}\n\n" if system_prompt else ""
    history_block = f"Recent conversation context:\n{history_context}\n\n" if history_context else ""
    return f"""
{extra}{history_block}Answer the question using only the provided PDF excerpts.

Question:
{question}

Selected sections:
{section_list}

PDF excerpts:
{context}

Requirements:
- Be concise and factual.
- If the answer is a list, present the list directly.
- Cite page numbers in parentheses, like (pages 353-360).
- If the excerpts are insufficient, say so explicitly.
"""


def build_citations(selected_nodes: list[dict]) -> list[dict]:
    return [
        {
            "node_id": node.get("node_id"),
            "title": node.get("title"),
            "page_start": node.get("start_index"),
            "page_end": node.get("end_index"),
            "snippet_id": node.get("node_id"),
        }
        for node in selected_nodes
    ]


def build_answer_with_marker(answer_text: str, citations: list[dict]) -> str:
    citations_payload = {"citations": citations}
    return (
        f"{answer_text}\n\n---\n[CITATIONS_JSON_BEGIN]\n"
        f"{json.dumps(citations_payload, ensure_ascii=False)}\n"
        "[CITATIONS_JSON_END]"
    )


def format_history_context(messages: list[dict]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def estimate_history_tokens(messages: list[dict], model: str) -> int:
    history_context = format_history_context(messages)
    return count_tokens(history_context, model=model)


def answer_question_against_structure(
    *,
    pdf_path: str,
    structure: list[dict],
    question: str,
    model: str,
    system_prompt: str | None = None,
    request_options: dict | None = None,
    retrieval_options: dict | None = None,
    generation_options: dict | None = None,
    conversation_options: dict | None = None,
    history_messages: list[dict] | None = None,
    trace_hook=None,
) -> tuple[str, list[dict], dict, dict]:
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "successful_llm_calls": 0,
    }

    def stats_hook(event: dict) -> None:
        if not event.get("ok"):
            return
        usage = event.get("usage") or {}
        usage_totals["successful_llm_calls"] += 1
        usage_totals["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        usage_totals["output_tokens"] += int(usage.get("completion_tokens") or 0)
        total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            total_tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        usage_totals["total_tokens"] += int(total_tokens or 0)

    started = time.perf_counter()
    retrieve_started = time.perf_counter()
    shared_options = dict(request_options or {})
    retrieval_request_options = {**shared_options, **dict(retrieval_options or {})}
    generation_request_options = {**shared_options, **dict(generation_options or {})}
    conversation_request_options = dict(conversation_options or {})

    top_k = int(retrieval_request_options.pop("top_k", 5) or 5)
    selection_mode = retrieval_request_options.pop("selection_mode", "outline_llm")
    max_context_pages = retrieval_request_options.pop("max_context_pages", None)
    max_context_tokens = retrieval_request_options.pop("max_context_tokens", None)
    query_rewrite_with_history = bool(conversation_request_options.pop("query_rewrite_with_history", True))
    include_history = bool(conversation_request_options.pop("include_history", True))

    prepared_history_messages = list(history_messages or [])
    history_context = format_history_context(prepared_history_messages) if include_history and prepared_history_messages else ""
    history_token_estimate = estimate_history_tokens(prepared_history_messages, model=model) if history_context else 0
    retrieval_query = question
    rewritten_query = None
    rewrite_applied = False

    if query_rewrite_with_history and history_context:
        try:
            rewrite_response = llm_completion(
                model=model,
                prompt=build_query_rewrite_prompt(question, history_context),
                request_options=retrieval_request_options,
                trace_hook=trace_hook,
                trace_label="query_rewrite",
                stats_hook=stats_hook,
            )
            rewrite_payload = extract_json(rewrite_response)
            candidate = rewrite_payload.get("rewritten_query") if isinstance(rewrite_payload, dict) else None
            if isinstance(candidate, str) and candidate.strip():
                rewritten_query = candidate.strip()
                retrieval_query = rewritten_query
                rewrite_applied = retrieval_query != question
        except Exception:
            retrieval_query = question

    selected_nodes = choose_relevant_nodes(
        structure,
        retrieval_query,
        model,
        request_options=retrieval_request_options,
        trace_hook=trace_hook,
        stats_hook=stats_hook,
        top_k=top_k,
        selection_mode=selection_mode,
    )
    context = build_answer_context(
        selected_nodes,
        pdf_path,
        model,
        max_context_pages=int(max_context_pages) if max_context_pages is not None else None,
        max_context_tokens=int(max_context_tokens) if max_context_tokens is not None else None,
    )
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)

    answer_started = time.perf_counter()
    answer = llm_completion(
        model=model,
        prompt=build_generation_prompt(
            question,
            selected_nodes,
            context,
            system_prompt=system_prompt,
            history_context=history_context,
        ),
        raise_on_error=True,
        request_options=generation_request_options,
        trace_hook=trace_hook,
        trace_label="final_answer",
        stats_hook=stats_hook,
    ).strip()
    answer_ms = int((time.perf_counter() - answer_started) * 1000)
    total_ms = int((time.perf_counter() - started) * 1000)
    citations = build_citations(selected_nodes)
    execution_context = {
        "history": {
            "used": bool(history_context),
            "messages_used": len(prepared_history_messages),
            "history_turns_used": len([m for m in prepared_history_messages if m.get("role") == "user"]),
            "history_token_estimate": history_token_estimate,
            "query_rewrite_with_history": query_rewrite_with_history,
            "include_history": include_history,
        },
        "retrieval": {
            "query": retrieval_query,
            "rewritten_query": rewritten_query,
            "rewrite_applied": rewrite_applied,
            "top_k": top_k,
            "selection_mode": selection_mode,
            "max_context_pages": int(max_context_pages) if max_context_pages is not None else None,
            "max_context_tokens": int(max_context_tokens) if max_context_tokens is not None else None,
        },
        "generation": {
            "temperature": generation_request_options.get("temperature"),
        },
    }
    return answer, selected_nodes, {
        "retrieve_ms": retrieve_ms,
        "answer_ms": answer_ms,
        "total_ms": total_ms,
        "input_tokens": usage_totals["input_tokens"],
        "output_tokens": usage_totals["output_tokens"],
        "total_tokens": usage_totals["total_tokens"],
        "manual_count": 1,
        "selected_section_count": len(selected_nodes),
        "successful_llm_calls": usage_totals["successful_llm_calls"],
        "citations_count": len(citations),
    }, execution_context


async def parse_pdf_to_structure_async(pdf_path: str, model: str) -> dict:
    return await asyncio.to_thread(parse_pdf_to_structure, pdf_path, model)


async def answer_question_against_structure_async(
    *,
    pdf_path: str,
    structure: list[dict],
    question: str,
    model: str,
    system_prompt: str | None = None,
    request_options: dict | None = None,
    retrieval_options: dict | None = None,
    generation_options: dict | None = None,
    conversation_options: dict | None = None,
    history_messages: list[dict] | None = None,
    trace_hook=None,
) -> tuple[str, list[dict], dict, dict]:
    return await asyncio.to_thread(
        answer_question_against_structure,
        pdf_path=pdf_path,
        structure=structure,
        question=question,
        model=model,
        system_prompt=system_prompt,
        request_options=request_options,
        retrieval_options=retrieval_options,
        generation_options=generation_options,
        conversation_options=conversation_options,
        history_messages=history_messages,
        trace_hook=trace_hook,
    )


def load_structure_file(path: str) -> list[dict]:
    data = read_json_artifact(path)
    return data["structure"] if isinstance(data, dict) and "structure" in data else data
