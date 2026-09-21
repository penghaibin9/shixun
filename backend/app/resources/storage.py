from hashlib import sha256
from os import getenv
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
from tarfile import TarError, open as open_tar
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import UploadFile

from app.common.errors import ApiError


MIME_BY_SUFFIX = {
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
}
MAX_LAB_ARCHIVE_ENTRIES = 500
MAX_LAB_ARCHIVE_ENTRY_BYTES = 256 * 1024 * 1024
MAX_LAB_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


def upload_root() -> Path:
    configured = getenv("YUEKE_RESOURCE_UPLOAD_DIR")
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / "var" / "resource_uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


async def save_upload(upload: UploadFile) -> dict:
    original_name = Path(upload.filename or "").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in MIME_BY_SUFFIX:
        raise ApiError("RESOURCE.FILE_TYPE_UNSUPPORTED", "仅允许上传 PPT、PPTX、MP4、WebM、MOV、ZIP、TAR 或 TAR.GZ 文件", 422, {"suffix": suffix})
    maximum = int(getenv("YUEKE_RESOURCE_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
    destination = upload_root() / f"{uuid4().hex}{suffix}"
    digest = sha256()
    size = 0
    try:
        with destination.open("xb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise ApiError("RESOURCE.FILE_TOO_LARGE", "上传文件超过平台限制", 413, {"max_bytes": maximum})
                digest.update(chunk)
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if size == 0:
        destination.unlink(missing_ok=True)
        raise ApiError("RESOURCE.FILE_EMPTY", "不能上传空文件", 422)
    return {"path": destination, "original_name": original_name, "mime_type": MIME_BY_SUFFIX[suffix], "size_bytes": size, "sha256": digest.hexdigest()}


def _safe_archive_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(
        normalized
        and "\x00" not in normalized
        and not path.is_absolute()
        and ".." not in path.parts
        and not (path.parts and path.parts[0].endswith(":"))
    )


def _enforce_archive_limits(count: int, total_size: int, entry_size: int) -> None:
    if count > MAX_LAB_ARCHIVE_ENTRIES:
        raise ApiError("RESOURCE.LAB_FILE_TOO_MANY_ENTRIES", "实验文件包内文件数量超过平台限制", 422, {"max_entries": MAX_LAB_ARCHIVE_ENTRIES})
    if entry_size > MAX_LAB_ARCHIVE_ENTRY_BYTES or total_size > MAX_LAB_ARCHIVE_UNCOMPRESSED_BYTES:
        raise ApiError(
            "RESOURCE.LAB_FILE_UNCOMPRESSED_TOO_LARGE",
            "实验文件包解压后大小超过平台限制",
            422,
            {"max_entry_bytes": MAX_LAB_ARCHIVE_ENTRY_BYTES, "max_total_bytes": MAX_LAB_ARCHIVE_UNCOMPRESSED_BYTES},
        )


def archive_file_count(path_text: str, mime_type: str) -> int:
    path = Path(path_text)
    try:
        if mime_type == "application/zip":
            with ZipFile(path) as archive:
                corrupt = archive.testzip()
                if corrupt:
                    raise BadZipFile(corrupt)
                count = total_size = 0
                for item in archive.infolist():
                    if not _safe_archive_path(item.filename):
                        raise ApiError("RESOURCE.LAB_FILE_UNSAFE_ENTRY", "实验文件包包含不安全路径", 422, {"entry": item.filename})
                    unix_mode = item.external_attr >> 16
                    if item.flag_bits & 0x1 or (unix_mode and S_ISLNK(unix_mode)):
                        raise ApiError("RESOURCE.LAB_FILE_UNSAFE_ENTRY", "实验文件包不能包含加密文件或符号链接", 422, {"entry": item.filename})
                    if item.is_dir():
                        continue
                    count += 1
                    total_size += item.file_size
                    _enforce_archive_limits(count, total_size, item.file_size)
        elif mime_type in {"application/x-tar", "application/gzip"}:
            with open_tar(path, mode="r:*") as archive:
                count = total_size = 0
                for item in archive.getmembers():
                    if not _safe_archive_path(item.name) or item.issym() or item.islnk() or item.isdev():
                        raise ApiError("RESOURCE.LAB_FILE_UNSAFE_ENTRY", "实验文件包包含不安全路径或链接", 422, {"entry": item.name})
                    if not item.isfile():
                        continue
                    count += 1
                    total_size += item.size
                    _enforce_archive_limits(count, total_size, item.size)
        else:
            raise ApiError("RESOURCE.LAB_FILE_TYPE_UNSUPPORTED", "实验文件包格式不受支持", 422)
    except (BadZipFile, TarError, OSError) as exc:
        raise ApiError("RESOURCE.LAB_FILE_INVALID", "实验文件包损坏或无法读取", 422) from exc
    if count < 1:
        raise ApiError("RESOURCE.LAB_FILE_EMPTY", "实验文件包内没有可用文件", 422)
    return count
