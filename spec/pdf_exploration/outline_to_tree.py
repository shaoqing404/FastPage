import json
from pathlib import Path

from PyPDF2 import PdfReader


ROOT = Path("/Users/shaoqing/workspace/PageIndex")
PDF_PATH = ROOT / "《运行手册》（第1版）.pdf"
TREE_OUT_PATH = ROOT / "spec" / "pdf_exploration" / "outline_tree.json"
MATCH_OUT_PATH = ROOT / "spec" / "pdf_exploration" / "outline_matches.json"


def destination_title(dest) -> str:
    title = getattr(dest, "title", None)
    if title is None and hasattr(dest, "get"):
        title = dest.get("/Title")
    return (title or "").replace("\r", "").strip()


def destination_page(reader: PdfReader, dest) -> int | None:
    try:
        page = reader.get_destination_page_number(dest) + 1
        return page if page > 0 else None
    except Exception:
        return None


def parse_outline_items(reader: PdfReader, items, depth: int = 1):
    nodes = []
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, list):
            i += 1
            continue

        node = {
            "title": destination_title(item),
            "start_index": destination_page(reader, item),
            "depth": depth,
            "nodes": [],
        }

        if i + 1 < len(items) and isinstance(items[i + 1], list):
            node["nodes"] = parse_outline_items(reader, items[i + 1], depth + 1)
            if node["start_index"] is None:
                for child in node["nodes"]:
                    if child.get("start_index") is not None:
                        node["start_index"] = child["start_index"]
                        break
            i += 1

        nodes.append(node)
        i += 1
    return nodes


def assign_end_indexes(nodes, fallback_end: int) -> None:
    for idx, node in enumerate(nodes):
        next_start = None
        for sibling in nodes[idx + 1:]:
            if sibling.get("start_index") is not None:
                next_start = sibling["start_index"]
                break

        if node["nodes"]:
            child_fallback_end = (next_start - 1) if next_start else fallback_end
            assign_end_indexes(node["nodes"], child_fallback_end)
            child_end_candidates = [child.get("end_index") for child in node["nodes"] if child.get("end_index") is not None]
            node["end_index"] = max(child_end_candidates) if child_end_candidates else child_fallback_end
        else:
            node["end_index"] = (next_start - 1) if next_start else fallback_end


def flatten(nodes):
    for node in nodes:
        yield node
        if node["nodes"]:
            yield from flatten(node["nodes"])


def main() -> None:
    reader = PdfReader(str(PDF_PATH))
    tree = parse_outline_items(reader, reader.outline)
    assign_end_indexes(tree, len(reader.pages))

    for node_id, node in enumerate(flatten(tree), start=1):
        node["node_id"] = str(node_id).zfill(4)

    matches = [
        {
            "title": node["title"],
            "start_index": node.get("start_index"),
            "end_index": node.get("end_index"),
            "depth": node.get("depth"),
        }
        for node in flatten(tree)
        if "特殊机场" in node["title"]
    ]

    TREE_OUT_PATH.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    MATCH_OUT_PATH.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(TREE_OUT_PATH))
    print(str(MATCH_OUT_PATH))


if __name__ == "__main__":
    main()
