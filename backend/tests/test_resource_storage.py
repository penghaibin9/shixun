from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest

from app.common.errors import ApiError
from app.resources.storage import archive_file_count


def test_archive_file_count_reads_real_zip_entries(tmp_path):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", "步骤说明")
        archive.writestr("scripts/check.sh", "echo ok")
        archive.writestr("empty/", "")
    path = tmp_path / "lab.zip"
    path.write_bytes(buffer.getvalue())
    assert archive_file_count(str(path), "application/zip") == 2


def test_archive_file_count_rejects_fake_zip(tmp_path):
    path = tmp_path / "fake.zip"
    path.write_bytes(b"not-a-zip")
    with pytest.raises(ApiError) as error:
        archive_file_count(str(path), "application/zip")
    assert error.value.code == "RESOURCE.LAB_FILE_INVALID"


@pytest.mark.parametrize("entry", ["../escape.txt", "/absolute.txt", "C:/windows.txt", "folder\\..\\escape.txt"])
def test_archive_file_count_rejects_unsafe_paths(tmp_path, entry):
    path = tmp_path / "unsafe.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(entry, "blocked")
    with pytest.raises(ApiError) as error:
        archive_file_count(str(path), "application/zip")
    assert error.value.code == "RESOURCE.LAB_FILE_UNSAFE_ENTRY"


def test_archive_file_count_rejects_symbolic_links(tmp_path):
    path = tmp_path / "link.zip"
    info = ZipInfo("link")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with ZipFile(path, "w") as archive:
        archive.writestr(info, "target")
    with pytest.raises(ApiError) as error:
        archive_file_count(str(path), "application/zip")
    assert error.value.code == "RESOURCE.LAB_FILE_UNSAFE_ENTRY"


def test_archive_file_count_enforces_uncompressed_size(monkeypatch, tmp_path):
    path = tmp_path / "large.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("large.txt", "12345")
    monkeypatch.setattr("app.resources.storage.MAX_LAB_ARCHIVE_ENTRY_BYTES", 4)
    with pytest.raises(ApiError) as error:
        archive_file_count(str(path), "application/zip")
    assert error.value.code == "RESOURCE.LAB_FILE_UNCOMPRESSED_TOO_LARGE"
