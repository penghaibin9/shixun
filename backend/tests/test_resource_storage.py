from io import BytesIO
from zipfile import ZipFile

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
