from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentOrigin(StrEnum):
    ORIGINAL = "ORIGINAL"
    THIRD_PARTY = "THIRD_PARTY"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class LicenseDecision(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class SourceRef(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=1000)
    license_id: str | None = Field(default=None, max_length=80)
    use_mode: Literal["BUNDLED", "EXTERNAL_RUNTIME", "REFERENCE_ONLY"]


class CoursePackLesson(StrictModel):
    lesson_code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    lesson_type: Literal["THEORY", "LAB"]
    summary: str = Field(min_length=1, max_length=2000)
    objectives: list[str] = Field(min_length=1, max_length=12)
    difficulty: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = "BEGINNER"
    category: str = Field(min_length=1, max_length=80)
    lab_profile: str | None = Field(default=None, max_length=80)
    challenge_mode: bool = False
    source_refs: list[SourceRef] = Field(default_factory=list, max_length=8)


class CoursePackManifest(StrictModel):
    schema_version: Literal["1.0"]
    pack_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    course_id: str = Field(pattern=r"^course_[a-z0-9_]{3,48}$")
    title: str = Field(min_length=1, max_length=160)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    language: Literal["zh-CN"] = "zh-CN"
    content_origin: ContentOrigin
    commercial_bundle_allowed: bool
    copyright_notice: str
    sources: list[SourceRef] = Field(default_factory=list, max_length=32)
    lessons: list[CoursePackLesson] = Field(min_length=1, max_length=300)


class ExternalLabCandidate(StrictModel):
    source: str
    source_path: str
    source_url: str
    name: str
    app: str
    cves: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    license_id: str | None = None
    import_status: Literal["CANDIDATE", "REVIEW_REQUIRED", "BLOCKED"] = "CANDIDATE"
