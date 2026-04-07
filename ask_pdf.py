import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import litellm
from pageindex.page_index import page_index_main
from pageindex.utils import (
    ConfigLoader,
    extract_json,
    get_page_tokens,
    get_text_of_pdf_pages_with_labels,
    llm_completion,
    structure_to_list,
)


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"


class MetricsCollector:
    def __init__(self):
        self.start_time = 0.0
        self.end_time = 0.0
        self.calls = []

    def start(self):
        self.start_time = time.time()

    def stop(self):
        self.end_time = time.time()

    def add_call(self, model: str, duration: float, first_token_latency: float | None, tokens: int):
        self.calls.append({
            "model": model,
            "duration": duration,
            "first_token_latency": first_token_latency,
            "tokens": tokens
        })

    def report(self):
        total_duration = self.end_time - self.start_time
        num_calls = len(self.calls)
        models_used = sorted(list(set(c["model"] for c in self.calls)))
        total_tokens = sum(c["tokens"] for c in self.calls)
        
        longest_call = max(self.calls, key=lambda x: x["duration"]) if self.calls else None

        print("\n" + "="*30)
        print("📊 PERFORMANCE METRICS")
        print(f"Total Time:      {total_duration:.2f}s")
        print(f"Total Calls:     {num_calls}")
        print(f"Models Used:     {', '.join(models_used)}")
        if self.calls and self.calls[-1]["first_token_latency"]:
            print(f"First Token:     {self.calls[-1]['first_token_latency']:.2f}s (last call)")
        print(f"Answer Length:   {self.calls[-1]['tokens'] if self.calls else 0} tokens")
        
        if longest_call:
            print(f"Longest Call:    {longest_call['duration']:.2f}s ({longest_call['model']})")
        print("="*30 + "\n")


def find_default_pdf() -> Path | None:
    pdfs = sorted(ROOT.glob("*.pdf"))
    if len(pdfs) == 1:
        return pdfs[0]
    manual_pdf = ROOT / "《运行手册》（第1版）.pdf"
    if manual_pdf.exists():
        return manual_pdf
    return None


def default_model() -> str:
    api_base = (os.getenv("OPENAI_API_BASE") or "").lower()
    if "dashscope" in api_base:
        return "openai/qwen-plus"
    config = ConfigLoader().load()
    return config.model


def cache_path_for(pdf_path: Path) -> Path:
    return RESULTS_DIR / f"{pdf_path.stem}_ask_index.json"


def build_or_load_index(pdf_path: Path, model: str, rebuild: bool) -> dict:
    RESULTS_DIR.mkdir(exist_ok=True)
    cache_path = cache_path_for(pdf_path)
    if cache_path.exists() and not rebuild:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    opt = ConfigLoader().load(
        {
            "model": model,
            "if_add_node_summary": "no",
            "if_add_doc_description": "no",
            "if_add_node_text": "no",
            "if_add_node_id": "yes",
        }
    )
    result = page_index_main(str(pdf_path), opt)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_outline_prompt(structure: list[dict], question: str) -> str:
    lines = []
    for node in structure_to_list(structure):
        node_id = node.get("node_id", "")
        title = node.get("title", "")
        start_index = node.get("start_index")
        end_index = node.get("end_index")
        lines.append(f"{node_id} | {start_index}-{end_index} | {title}")
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


def tracked_completion(model: str, prompt: str, metrics: MetricsCollector, stream: bool = False) -> str:
    start_time = time.time()
    first_token_time = None
    full_content = ""
    
    try:
        if stream:
            response = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}], stream=True, temperature=0)
            for chunk in response:
                content = chunk.choices[0].delta.content or ""
                if content and first_token_time is None:
                    first_token_time = time.time()
                full_content += content
                print(content, end="", flush=True)
            print() # New line after stream
        else:
            full_content = llm_completion(model=model, prompt=prompt)
    except Exception as e:
        print(f"\nError during LLM completion: {e}")
    
    end_time = time.time()
    duration = end_time - start_time
    first_token_latency = (first_token_time - start_time) if first_token_time else None
    
    # Estimate tokens if not provided by litellm metadata (simplified)
    token_count = litellm.token_counter(model=model, text=full_content)
    metrics.add_call(model, duration, first_token_latency, token_count)
    
    return full_content


def choose_relevant_nodes(structure: list[dict], question: str, model: str, metrics: MetricsCollector) -> list[dict]:
    flat_nodes = {node["node_id"]: node for node in structure_to_list(structure) if node.get("node_id")}

    response = tracked_completion(model=model, prompt=build_outline_prompt(structure, question), metrics=metrics)
    payload = extract_json(response)
    node_ids = payload.get("node_ids", []) if isinstance(payload, dict) else []
    selected = [flat_nodes[node_id] for node_id in node_ids if node_id in flat_nodes]

    # Simple fallback
    if not selected:
        lowered = question.lower()
        selected = [
            node for node in flat_nodes.values()
            if any(token and token in node.get("title", "").lower() for token in lowered.split())
        ][:5]

    if not selected:
        selected = list(flat_nodes.values())[:3]

    return selected


def build_answer_context(selected_nodes: list[dict], pdf_pages: list[tuple[str, int]]) -> str:
    chunks = []
    seen_ranges = set()
    for node in selected_nodes:
        start_index = node.get("start_index")
        end_index = node.get("end_index")
        if start_index is None or end_index is None:
            continue
        page_range = (start_index, end_index)
        if page_range in seen_ranges:
            continue
        seen_ranges.add(page_range)
        text = get_text_of_pdf_pages_with_labels(pdf_pages, start_index, end_index)
        chunks.append(
            f"## Section: {node.get('title')} (pages {start_index}-{end_index})\n{text}"
        )
    return "\n\n".join(chunks)


def build_answer_prompt(question: str, selected_nodes: list[dict], context: str) -> str:
    section_list = "\n".join(
        f"- {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})"
        for node in selected_nodes
    )
    return f"""
Answer the question using only the provided PDF excerpts.

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask a question against a PDF using a cached PageIndex structure.")
    parser.add_argument("--question", default=None, help="Question to ask. If not provided, starts interactive mode.")
    parser.add_argument("--pdf_path", default=None, help="Path to the PDF file.")
    parser.add_argument("--model", default=None, help="LLM model for section selection and answering.")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild cached index instead of reusing it.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve() if args.pdf_path else find_default_pdf()
    if pdf_path is None or not pdf_path.exists():
        raise ValueError("No default PDF found. Pass --pdf_path explicitly.")

    model = args.model or default_model()
    print(f"Loading structure for {pdf_path}...")
    index_result = build_or_load_index(pdf_path, model, args.rebuild_index)
    structure = index_result["structure"]

    print("Extracting PDF text...")
    pdf_pages = get_page_tokens(str(pdf_path), model=model)
    
    print(f"\nWelcome to PDF Explorer!")
    print(f"PDF: {pdf_path}")
    print(f"Model: {model}")
    print("Type 'exit' or 'quit' to stop.\n")

    def run_query(question: str):
        metrics = MetricsCollector()
        metrics.start()

        selected_nodes = choose_relevant_nodes(structure, question, model, metrics)
        context = build_answer_context(selected_nodes, pdf_pages)

        # Context Token Limit check
        prompt_est = build_answer_prompt(question, selected_nodes, context)
        tokens = litellm.token_counter(model=model, text=prompt_est)
        if tokens > 120000:
             print(f"⚠️ Warning: Context size ({tokens} tokens) is very large. Consider a more specific question.")

        print("\nSelected sections:")
        for node in selected_nodes:
            print(f"- [{node.get('node_id')}] {node.get('title')} ({node.get('start_index')}-{node.get('end_index')})")

        print("\nAnswer:\n")
        tracked_completion(
            model=model, 
            prompt=build_answer_prompt(question, selected_nodes, context), 
            metrics=metrics, 
            stream=True
        )

        metrics.stop()
        metrics.report()

    if args.question:
        run_query(args.question)
    else:
        while True:
            try:
                q = input("Question: ").strip()
                if not q:
                    continue
                if q.lower() in ("exit", "quit", "q"):
                    break
                run_query(q)
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    main()
