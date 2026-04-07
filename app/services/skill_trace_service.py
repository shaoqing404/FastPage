import json
from datetime import datetime
from typing import Any

from app.models import ChatSkill, Document, DocumentVersion, User
from app.services.storage_service import read_json_artifact, write_skill_trace


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return _json_safe(value.dict())
    if hasattr(value, "json"):
        try:
            return json.loads(value.json())
        except Exception:
            return value.json()
    return str(value)


class SkillTraceRecorder:
    def __init__(
        self,
        *,
        tenant_id: str,
        run_id: str,
        user: User,
        skill: ChatSkill,
        document: Document,
        version: DocumentVersion,
        question: str,
        model: str,
        request_config: dict[str, Any],
    ) -> None:
        self.tenant_id = tenant_id
        self.skill_id = skill.id
        self.run_id = run_id
        self.payload: dict[str, Any] = {
            "trace_type": "skill_model_trace",
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user": {
                "id": user.id,
                "username": user.username,
            },
            "skill": {
                "id": skill.id,
                "name": skill.name,
                "model": skill.model,
                "system_prompt": skill.system_prompt,
                "request_config": _json_safe(request_config),
            },
            "document": {
                "id": document.id,
                "display_name": document.display_name,
                "source_filename": document.source_filename,
            },
            "version": {
                "id": version.id,
                "version_no": version.version_no,
                "storage_path": version.storage_path,
                "parsed_structure_path": version.parsed_structure_path,
            },
            "question": question,
            "resolved_model": model,
            "status": "accepted",
            "started_at": _utcnow(),
            "finished_at": None,
            "final_answer": None,
            "metrics": {},
            "selected_sections": [],
            "llm_calls": [],
        }
        self._flush()

    def append_llm_call(self, event: dict[str, Any]) -> None:
        self.payload["llm_calls"].append(_json_safe(event))
        self._flush()

    def finalize(
        self,
        *,
        status: str,
        answer: str | None = None,
        metrics: dict[str, Any] | None = None,
        selected_sections: list[dict[str, Any]] | None = None,
        execution_context: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.payload["status"] = status
        self.payload["finished_at"] = _utcnow()
        self.payload["final_answer"] = answer
        self.payload["metrics"] = _json_safe(metrics or {})
        self.payload["selected_sections"] = _json_safe(selected_sections or [])
        self.payload["execution_context"] = _json_safe(execution_context or {})
        self.payload["error"] = error
        self._flush()

    def _flush(self) -> None:
        write_skill_trace(
            tenant_id=self.tenant_id,
            skill_id=self.skill_id,
            run_id=self.run_id,
            data=self.payload,
        )


def load_skill_trace(uri: str) -> dict[str, Any]:
    return read_json_artifact(uri)
