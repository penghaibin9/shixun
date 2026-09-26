from __future__ import annotations

import json
from pathlib import Path

from .schemas import CoursePackManifest


CONTENT_DIR = Path(__file__).with_name("content")
INDEX_PATH = CONTENT_DIR / "course-pack-index-v1.json"


def load_bundled_course_pack(filename: str) -> CoursePackManifest:
    if "/" in filename or "\\" in filename or not filename.endswith(".json"):
        raise ValueError("课程包文件名非法")
    path = CONTENT_DIR / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CoursePackManifest.model_validate(payload)


def course_pack_registry() -> list[dict[str, str]]:
    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    items = payload.get("catalogs") or []
    keys = [str(item.get("catalog_key") or "") for item in items]
    files = [str(item.get("filename") or "") for item in items]
    if not items or not all(keys) or len(keys) != len(set(keys)):
        raise ValueError("课程包索引 catalog_key 缺失或重复")
    if not all(files) or len(files) != len(set(files)):
        raise ValueError("课程包索引 filename 缺失或重复")
    for item in items:
        pack = load_bundled_course_pack(item["filename"])
        if pack.pack_id != item["catalog_key"]:
            raise ValueError(f"课程包索引与 Manifest 不一致：{item['catalog_key']}")
    return items


def load_course_pack_by_catalog(catalog_key: str) -> CoursePackManifest:
    for item in course_pack_registry():
        if item["catalog_key"] == catalog_key:
            return load_bundled_course_pack(item["filename"])
    raise ValueError(f"未知课程模板：{catalog_key}")
