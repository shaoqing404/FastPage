import copy
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from fastapi import UploadFile

from app.core.config import get_settings
from app.models.routing_asset_contract import normalize_routing_index_payload
from pageindex.utils import ensure_run_reuse_cache


settings = get_settings()


def _normalize_prefix(prefix: str) -> str:
    cleaned = prefix.strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


class BaseArtifactStorage:
    def save_upload(self, file: UploadFile, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        raise NotImplementedError

    def save_file_path(self, source_path: Path, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        raise NotImplementedError

    def write_json(self, data: Any, *, tenant_id: str, object_path: str) -> str:
        raise NotImplementedError

    def read_json(self, uri: str) -> Any:
        raise NotImplementedError

    def exists(self, uri: str) -> bool:
        raise NotImplementedError

    def delete_document_tree(self, tenant_id: str, document_id: str) -> None:
        raise NotImplementedError

    def delete_skill_trace_tree(self, tenant_id: str, skill_id: str) -> None:
        raise NotImplementedError

    @contextmanager
    def local_path(self, uri: str) -> Iterator[Path]:
        raise NotImplementedError


class LocalArtifactStorage(BaseArtifactStorage):
    def tenant_dir(self, tenant_id: str) -> Path:
        path = settings.data_dir / "tenants" / tenant_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def document_dir(self, tenant_id: str, document_id: str) -> Path:
        path = self.tenant_dir(tenant_id) / "documents" / document_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def version_dir(self, tenant_id: str, document_id: str, version_id: str) -> Path:
        path = self.document_dir(tenant_id, document_id) / "versions" / version_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def skill_trace_dir(self, tenant_id: str, skill_id: str) -> Path:
        path = self.tenant_dir(tenant_id) / "skill_traces" / skill_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_upload(self, file: UploadFile, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        target_path = self.version_dir(tenant_id, document_id, version_id) / filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return str(target_path)

    def save_file_path(self, source_path: Path, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        target_path = self.version_dir(tenant_id, document_id, version_id) / filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        return str(target_path)

    def write_json(self, data: Any, *, tenant_id: str, object_path: str) -> str:
        target_path = self.tenant_dir(tenant_id) / object_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target_path)

    def read_json(self, uri: str) -> Any:
        return json.loads(Path(uri).read_text(encoding="utf-8"))

    def exists(self, uri: str) -> bool:
        return Path(uri).exists()

    def delete_document_tree(self, tenant_id: str, document_id: str) -> None:
        path = self.document_dir(tenant_id, document_id)
        if path.exists():
            shutil.rmtree(path)

    def delete_skill_trace_tree(self, tenant_id: str, skill_id: str) -> None:
        path = self.skill_trace_dir(tenant_id, skill_id)
        if path.exists():
            shutil.rmtree(path)

    @contextmanager
    def local_path(self, uri: str) -> Iterator[Path]:
        yield Path(uri)


class MinioArtifactStorage(BaseArtifactStorage):
    def __init__(self) -> None:
        if not settings.minio_endpoint or not settings.minio_bucket:
            raise RuntimeError("MINIO_ENDPOINT and MINIO_BUCKET are required for minio storage backend")
        from minio import Minio

        self.bucket = settings.minio_bucket
        self.prefix = _normalize_prefix(settings.minio_prefix_path)
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _key(self, tenant_id: str, object_path: str) -> str:
        return f"{self.prefix}tenants/{tenant_id}/{object_path.lstrip('/')}"

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        return parsed.netloc, parsed.path.lstrip("/")

    def save_upload(self, file: UploadFile, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        object_path = f"documents/{document_id}/versions/{version_id}/{filename}"
        key = self._key(tenant_id, object_path)
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            shutil.copyfileobj(file.file, temp)
            temp_path = Path(temp.name)
        try:
            self.client.fput_object(self.bucket, key, str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        return f"minio://{self.bucket}/{key}"

    def save_file_path(self, source_path: Path, *, tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
        object_path = f"documents/{document_id}/versions/{version_id}/{filename}"
        key = self._key(tenant_id, object_path)
        self.client.fput_object(self.bucket, key, str(source_path))
        return f"minio://{self.bucket}/{key}"

    def write_json(self, data: Any, *, tenant_id: str, object_path: str) -> str:
        key = self._key(tenant_id, object_path)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        from io import BytesIO

        self.client.put_object(self.bucket, key, BytesIO(payload), len(payload), content_type="application/json")
        return f"minio://{self.bucket}/{key}"

    def read_json(self, uri: str) -> Any:
        bucket, key = self._parse_uri(uri)
        response = self.client.get_object(bucket, key)
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
            response.release_conn()

    def exists(self, uri: str) -> bool:
        bucket, key = self._parse_uri(uri)
        try:
            self.client.stat_object(bucket, key)
            return True
        except Exception:
            return False

    def delete_document_tree(self, tenant_id: str, document_id: str) -> None:
        prefix = self._key(tenant_id, f"documents/{document_id}/")
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        for obj in objects:
            self.client.remove_object(self.bucket, obj.object_name)

    def delete_skill_trace_tree(self, tenant_id: str, skill_id: str) -> None:
        prefix = self._key(tenant_id, f"skill_traces/{skill_id}/")
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        for obj in objects:
            self.client.remove_object(self.bucket, obj.object_name)

    @contextmanager
    def local_path(self, uri: str) -> Iterator[Path]:
        cache = ensure_run_reuse_cache()
        if cache is not None:
            def load_temp_path() -> Path:
                bucket, key = self._parse_uri(uri)
                suffix = Path(key).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                    temp_path = Path(temp.name)
                try:
                    self.client.fget_object(bucket, key, str(temp_path))
                except Exception:
                    temp_path.unlink(missing_ok=True)
                    raise
                cache.register_temp_path(temp_path)
                return temp_path

            yield cache.load_once("minio_local_path", uri, load_temp_path)
            return

        bucket, key = self._parse_uri(uri)
        suffix = Path(key).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = Path(temp.name)
        try:
            self.client.fget_object(bucket, key, str(temp_path))
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)


def get_storage_backend() -> BaseArtifactStorage:
    if settings.storage_backend == "minio":
        return MinioArtifactStorage()
    return LocalArtifactStorage()


_storage_backend: BaseArtifactStorage | None = None


def _get_storage_backend() -> BaseArtifactStorage:
    """Lazy singleton — defers MinIO connection to first actual use."""
    global _storage_backend
    if _storage_backend is None:
        _storage_backend = get_storage_backend()
    return _storage_backend


def save_uploaded_pdf(file: UploadFile, *, tenant_id: str, document_id: str, version_id: str) -> str:
    return _get_storage_backend().save_upload(
        file,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="source.pdf",
    )


def copy_source_pdf_to_version(*, source_uri: str, tenant_id: str, document_id: str, version_id: str) -> str:
    backend = _get_storage_backend()
    with backend.local_path(source_uri) as source_path:
        return backend.save_file_path(
            source_path,
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            filename="source.pdf",
        )


def write_document_structure(*, tenant_id: str, document_id: str, version_id: str, data: Any) -> str:
    return _get_storage_backend().write_json(
        data,
        tenant_id=tenant_id,
        object_path=f"documents/{document_id}/versions/{version_id}/structure.json",
    )


def write_document_routing_index(*, tenant_id: str, document_id: str, version_id: str, data: Any) -> str:
    normalized = normalize_routing_index_payload(data)
    return _get_storage_backend().write_json(
        normalized,
        tenant_id=tenant_id,
        object_path=f"documents/{document_id}/versions/{version_id}/routing_index.json",
    )


def write_skill_trace(*, tenant_id: str, skill_id: str, run_id: str, data: Any) -> str:
    return _get_storage_backend().write_json(
        data,
        tenant_id=tenant_id,
        object_path=f"skill_traces/{skill_id}/{run_id}.json",
    )


def get_trace_uri_for_run(tenant_id: str, skill_id: str, run_id: str) -> str:
    if settings.storage_backend == "minio":
        prefix = _normalize_prefix(settings.minio_prefix_path)
        key = f"{prefix}tenants/{tenant_id}/skill_traces/{skill_id}/{run_id}.json"
        return f"minio://{settings.minio_bucket}/{key}"
    return str(settings.data_dir / "tenants" / tenant_id / "skill_traces" / skill_id / f"{run_id}.json")


def read_json_artifact(uri: str) -> Any:
    cache = ensure_run_reuse_cache()
    if cache is None:
        return _get_storage_backend().read_json(uri)

    def load_json() -> Any:
        return _get_storage_backend().read_json(uri)

    data = cache.load_once("json_artifact", uri, load_json)
    return copy.deepcopy(data)


def read_document_routing_index(uri: str) -> dict[str, Any]:
    return normalize_routing_index_payload(read_json_artifact(uri))


def artifact_exists(uri: str) -> bool:
    return _get_storage_backend().exists(uri)


@contextmanager
def local_artifact_path(uri: str) -> Iterator[Path]:
    with _get_storage_backend().local_path(uri) as path:
        yield path


def delete_document_tree(tenant_id: str, document_id: str) -> None:
    _get_storage_backend().delete_document_tree(tenant_id, document_id)


def delete_skill_trace_tree(tenant_id: str, skill_id: str) -> None:
    _get_storage_backend().delete_skill_trace_tree(tenant_id, skill_id)
