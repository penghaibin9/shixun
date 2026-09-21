from io import BytesIO
from zipfile import BadZipFile, ZipFile


MAX_XLSX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_XLSX_ARCHIVE_ENTRIES = 256
MAX_XLSX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


class XlsxValidationError(ValueError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def validate_xlsx_archive(
    data: bytes,
    *,
    max_upload_bytes: int = MAX_XLSX_UPLOAD_BYTES,
    max_entries: int = MAX_XLSX_ARCHIVE_ENTRIES,
    max_uncompressed_bytes: int = MAX_XLSX_UNCOMPRESSED_BYTES,
) -> None:
    if len(data) > max_upload_bytes:
        raise XlsxValidationError("FILE_TOO_LARGE", "XLSX（电子表格）文件不能超过 10 MB")
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise XlsxValidationError("ARCHIVE_TOO_COMPLEX", "XLSX（电子表格）内部文件数超出限制")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise XlsxValidationError("ENCRYPTED_XLSX", "不支持加密的 XLSX（电子表格）")
            if sum(entry.file_size for entry in entries) > max_uncompressed_bytes:
                raise XlsxValidationError("ARCHIVE_TOO_LARGE", "XLSX（电子表格）解压后内容超出限制")
    except BadZipFile as exc:
        raise XlsxValidationError("INVALID_XLSX", "文件不是有效的 XLSX（电子表格）") from exc


async def read_xlsx_upload(upload, *, max_upload_bytes: int = MAX_XLSX_UPLOAD_BYTES) -> bytes:
    if not (upload.filename or "").lower().endswith(".xlsx"):
        await upload.close()
        raise XlsxValidationError("FILE_TYPE_INVALID", "仅支持 .xlsx 电子表格文件")
    content = bytearray()
    try:
        while chunk := await upload.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > max_upload_bytes:
                raise XlsxValidationError("FILE_TOO_LARGE", "XLSX（电子表格）文件不能超过 10 MB")
    finally:
        await upload.close()
    return bytes(content)
