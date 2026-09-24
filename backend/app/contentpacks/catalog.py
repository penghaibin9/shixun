from __future__ import annotations

import json
from pathlib import Path

from .schemas import CoursePackManifest


CONTENT_DIR = Path(__file__).with_name("content")


def load_bundled_course_pack(filename: str) -> CoursePackManifest:
    if "/" in filename or "\\" in filename or not filename.endswith(".json"):
        raise ValueError("课程包文件名非法")
    path = CONTENT_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CoursePackManifest.model_validate(payload)
