from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from os import getenv
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from app.common.errors import ApiError
from app.common.models import FileObject


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class BundleEntry:
    reference_id: str
    original_name: str
    expected_sha256: str
    expected_size_bytes: int
    file_object: FileObject | None = None
    content: bytes | None = None


def artifact_root() -> Path:
    configured = getenv("YUEKE_RUNTIME_ARTIFACT_DIR")
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / "var" / "runtime_artifacts"
    return root.resolve()


def _managed_file_path(file_object: FileObject) -> Path:
    if file_object.storage_provider != "local" or file_object.bucket != "runtime-artifacts":
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_UNAVAILABLE", "日志制品不在受控本地存储中", 503, {"file_id": file_object.file_id})
    root = artifact_root()
    candidate = Path(file_object.object_key)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if root not in path.parents:
        raise ApiError("RUNTIME.ARTIFACT_PATH_INVALID", "日志制品路径已越出受控存储目录", 409, {"file_id": file_object.file_id})
    if not path.is_file():
        raise ApiError("RUNTIME.ARTIFACT_FILE_MISSING", "日志制品文件不存在", 404, {"file_id": file_object.file_id})
    return path


def _archive_name(index: int, entry: BundleEntry) -> str:
    original = Path(entry.original_name.replace("\\", "/")).name.replace("\x00", "")
    original = _SAFE_NAME.sub("_", original).strip("._") or "artifact.bin"
    reference = _SAFE_NAME.sub("_", entry.reference_id).strip("._") or "reference"
    return f"{index:03d}_{reference}_{original}"


def _write_file(archive: ZipFile, archive_name: str, path: Path, entry: BundleEntry) -> None:
    digest = sha256()
    size = 0
    with path.open("rb") as source, archive.open(archive_name, "w") as target:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
            target.write(chunk)
    if size != entry.expected_size_bytes or digest.hexdigest() != entry.expected_sha256:
        raise ApiError(
            "RUNTIME.ARTIFACT_INTEGRITY_FAILED",
            "日志制品文件完整性校验失败",
            409,
            {"reference_id": entry.reference_id, "file_id": entry.file_object.file_id if entry.file_object else None},
        )


def build_bundle(entries: list[BundleEntry], assignment_id: str) -> Path:
    if not entries or len(entries) > 200:
        raise ApiError("RUNTIME.INVALID_ARTIFACT_BUNDLE", "制品列表不能为空且最多 200 项", 422)
    maximum = int(getenv("YUEKE_RUNTIME_ARTIFACT_BUNDLE_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
    declared_size = sum(entry.expected_size_bytes for entry in entries)
    if declared_size > maximum:
        raise ApiError("RUNTIME.ARTIFACT_BUNDLE_TOO_LARGE", "日志制品打包大小超过平台限制", 413, {"max_bytes": maximum})

    temporary = NamedTemporaryFile(prefix=f"yueke-{_SAFE_NAME.sub('_', assignment_id)}-", suffix=".zip", delete=False)
    path = Path(temporary.name)
    temporary.close()
    try:
        with ZipFile(path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for index, entry in enumerate(entries, start=1):
                archive_name = _archive_name(index, entry)
                if entry.file_object is not None:
                    _write_file(archive, archive_name, _managed_file_path(entry.file_object), entry)
                else:
                    content = entry.content or b""
                    if len(content) != entry.expected_size_bytes or sha256(content).hexdigest() != entry.expected_sha256:
                        raise ApiError("RUNTIME.ARTIFACT_INTEGRITY_FAILED", "审计日志内容完整性校验失败", 409, {"reference_id": entry.reference_id})
                    archive.writestr(archive_name, content)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise
