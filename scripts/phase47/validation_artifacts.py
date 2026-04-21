#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = ROOT / "results"
ARTIFACT_PREFIX = "phase4_7_backend_validation"
WORKING_FILE = f"{ARTIFACT_PREFIX}_latest.json"


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _artifact_status(payload: dict[str, object]) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise SystemExit("artifact 缺少 summary。")
    status = str(summary.get("status", "")).strip().lower()
    if status not in {"passed", "failed"}:
        raise SystemExit(f"artifact status 不受支持: {status!r}")
    return status


def _artifact_stamp(payload: dict[str, object]) -> str:
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    for key in ("finished_at", "started_at"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return _parse_iso8601(value).strftime("%Y%m%dT%H%M%SZ")
    raise SystemExit("artifact 缺少 started_at / finished_at，无法生成规范文件名。")


def _canonical_path(results_dir: Path, payload: dict[str, object]) -> Path:
    status = _artifact_status(payload)
    stamp = _artifact_stamp(payload)
    return results_dir / f"{ARTIFACT_PREFIX}_{status}_{stamp}.json"


def _latest_status_path(results_dir: Path, status: str) -> Path:
    return results_dir / f"{ARTIFACT_PREFIX}_latest_{status}.json"


def _iter_canonical_artifacts(results_dir: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted(results_dir.glob(f"{ARTIFACT_PREFIX}_passed_*.json")))
    paths.extend(sorted(results_dir.glob(f"{ARTIFACT_PREFIX}_failed_*.json")))
    return paths


def _sort_key(path: Path) -> tuple[float, str]:
    return (path.stat().st_mtime, path.name)


def finalize(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    if not source.exists():
        raise SystemExit(f"artifact 不存在: {source}")

    payload = _read_json(source)
    status = _artifact_status(payload)

    results_dir = Path(args.results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    canonical = _canonical_path(results_dir, payload)
    latest_status = _latest_status_path(results_dir, status)
    shutil.copy2(source, canonical)
    shutil.copy2(source, latest_status)

    deleted: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
    grouped: dict[str, list[Path]] = {"passed": [], "failed": []}
    for artifact in _iter_canonical_artifacts(results_dir):
        if "_passed_" in artifact.name:
            grouped["passed"].append(artifact)
        elif "_failed_" in artifact.name:
            grouped["failed"].append(artifact)

    for group_status, files in grouped.items():
        files.sort(key=_sort_key, reverse=True)
        keep: set[Path] = set(files[:1])
        if group_status == status:
            keep.add(canonical)
        for path in files[1:]:
            if path in keep:
                continue
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified_at < cutoff:
                path.unlink()
                deleted.append(path.name)

    payload_out = {
        "source": str(source),
        "canonical_artifact": str(canonical),
        "latest_status_alias": str(latest_status),
        "retention_days": args.retention_days,
        "deleted_artifacts": deleted,
    }
    _print_json(payload_out)
    return 0


def audit(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, object]] = []
    for path in sorted(results_dir.glob(f"{ARTIFACT_PREFIX}*.json")):
        item: dict[str, object] = {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }
        try:
            payload = _read_json(path)
            item["status"] = _artifact_status(payload)
            item["started_at"] = payload.get("summary", {}).get("started_at")
            item["finished_at"] = payload.get("summary", {}).get("finished_at")
        except Exception as exc:
            item["status"] = "unreadable"
            item["error"] = str(exc)
        entries.append(item)

    _print_json(
        {
            "results_dir": str(results_dir),
            "artifact_prefix": ARTIFACT_PREFIX,
            "artifacts": entries,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 4.7 validation artifact helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    finalize_parser = subparsers.add_parser("finalize", help="把 latest artifact 固化为规范文件名并清理超期结果")
    finalize_parser.add_argument("source", nargs="?", default=str(DEFAULT_RESULTS_DIR / WORKING_FILE))
    finalize_parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    finalize_parser.add_argument("--retention-days", type=int, default=14)
    finalize_parser.set_defaults(func=finalize)

    audit_parser = subparsers.add_parser("audit", help="列出当前 results/ 下的验证 artifact")
    audit_parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    audit_parser.set_defaults(func=audit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
