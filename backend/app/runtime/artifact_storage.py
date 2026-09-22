from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from os import getenv
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from app.common.errors import ApiError
from app.common.models import FileObject


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_PCAP_MAGICS = {b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"}


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
    if not root.is_absolute():
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_CONFIG_INVALID", "运行制品目录必须是绝对路径", 503)
    if root.exists() and root.is_symlink():
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_CONFIG_INVALID", "运行制品目录不能是符号链接", 503)
    return root.resolve()


def _verify_capture_file(path: Path, expected_sha256: str, expected_size_bytes: int) -> None:
    descriptor = None
    try:
        if path.is_symlink():
            raise OSError("capture artifact is a symlink")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size_bytes:
            raise OSError("capture artifact size mismatch")
        digest = sha256()
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_WRITE_FAILED", "流量制品文件无法安全校验", 503) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if digest.hexdigest() != expected_sha256:
        raise ApiError("RUNTIME.ARTIFACT_INTEGRITY_FAILED", "流量制品落盘后完整性校验失败", 503)


def store_capture_artifact(content: bytes, expected_sha256: str, expected_size_bytes: int) -> str:
    """原子写入已验证的 PCAP，并返回相对受控根目录的对象键。"""
    try:
        maximum = int(getenv("YUEKE_RUNTIME_ARTIFACT_MAX_BYTES", str(128 * 1024 * 1024)))
    except ValueError as error:
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_CONFIG_INVALID", "运行制品大小限制配置无效", 503) from error
    if (
        not isinstance(content, bytes)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or expected_size_bytes != len(content)
        or not 24 < expected_size_bytes <= maximum
        or content[:4] not in _PCAP_MAGICS
        or sha256(content).hexdigest() != expected_sha256
    ):
        raise ApiError("RUNTIME.ARTIFACT_INTEGRITY_FAILED", "节点抓包产物摘要、大小或格式校验失败", 503)
    root = artifact_root()
    directory = root / "traffic"
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink() or directory.is_symlink() or not root.is_dir() or not directory.is_dir():
            raise OSError("runtime artifact directory is unsafe")
    except OSError as error:
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_UNAVAILABLE", "运行制品目录不可用", 503) from error
    object_key = f"traffic/{expected_sha256}.pcap"
    destination = directory / f"{expected_sha256}.pcap"
    if destination.exists() or destination.is_symlink():
        _verify_capture_file(destination, expected_sha256, expected_size_bytes)
        return object_key

    try:
        temporary = NamedTemporaryFile(prefix=".capture-", suffix=".tmp", dir=directory, delete=False)
    except OSError as error:
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_WRITE_FAILED", "流量制品无法安全写入", 503) from error
    temporary_path = Path(temporary.name)
    try:
        os.chmod(temporary_path, 0o600)
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary.close()
        try:
            os.link(temporary_path, destination, follow_symlinks=False)
        except FileExistsError:
            pass
        _verify_capture_file(destination, expected_sha256, expected_size_bytes)
        return object_key
    except ApiError:
        raise
    except OSError as error:
        raise ApiError("RUNTIME.ARTIFACT_STORAGE_WRITE_FAILED", "流量制品无法安全写入", 503) from error
    finally:
        try:
            temporary.close()
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)


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
