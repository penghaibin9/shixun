import pytest
from pydantic import ValidationError

from app.runtime.schemas import ImageRegister, RuntimeStart


def test_runtime_start_requires_student_subject():
    with pytest.raises(ValidationError):
        RuntimeStart(lab_release_id="release", lab_version_id="version", mode="STUDENT")


def test_image_requires_fixed_sha256_digest():
    with pytest.raises(ValidationError):
        ImageRegister(image_id="image", name="test", tag="latest", digest="latest", size_bytes=1, scan_status="PASSED", startup_check_status="PASSED", teaching_validation_status="PASSED", enabled=True)
