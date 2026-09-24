from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, UploadFile

from app.common.context import CurrentUser
from app.common.errors import ApiError

from .adapters.atomic_red_team import parse_atomic_technique
from .adapters.pwncollege import parse_dojo_manifest
from .adapters.vulhub import parse_environment_index
from .catalog import CONTENT_DIR, course_pack_registry, load_course_pack_by_catalog
from .license_policy import evaluate_license
from .security import scan_compose_manifest
from .schemas import (
    AtomicTechniquePreviewResponse,
    ComposeScanResponse,
    ContentPackListResponse,
    ContentSourcePolicyListResponse,
    CoursePackManifest,
    DojoPreviewResponse,
    ExternalLabCandidateListResponse,
    SeedDomainMapResponse,
    WebLabReadinessRegistryResponse,
)


router = APIRouter(prefix="/api/v1", tags=["内容包"])


SOURCES = [
    {"name": "Vulhub", "url": "https://github.com/vulhub/vulhub", "license_id": "MIT", "use_mode": "EXTERNAL_RUNTIME"},
    {"name": "OWASP Juice Shop", "url": "https://github.com/juice-shop/juice-shop", "license_id": "MIT", "use_mode": "EXTERNAL_RUNTIME"},
    {"name": "WebGoat", "url": "https://github.com/WebGoat/WebGoat", "license_id": "GPL-2.0-or-later", "use_mode": "REVIEW_REQUIRED"},
    {"name": "pwn.college dojo", "url": "https://github.com/pwncollege/dojo", "license_id": "BSD-2-Clause", "use_mode": "FEATURE_REFERENCE"},
    {"name": "CTFd", "url": "https://github.com/CTFd/CTFd", "license_id": "Apache-2.0", "use_mode": "FEATURE_REFERENCE"},
    {"name": "Atomic Red Team", "url": "https://github.com/redcanaryco/atomic-red-team", "license_id": "MIT", "use_mode": "EXTERNAL_RUNTIME_OR_REFERENCE"},
    {"name": "SEED Labs", "url": "https://github.com/seed-labs/seed-labs", "license_id": "CC-BY-NC-SA-4.0", "use_mode": "REFERENCE_ONLY"},
]


def _require(user, *permissions: str) -> None:
    if not any(permission in user.permissions for permission in permissions):
        raise ApiError("AUTH.PERMISSION_DENIED", "缺少内容包读取权限", 403)


@router.get("/content-packs", response_model=ContentPackListResponse)
def list_content_packs(user: CurrentUser):
    _require(user, "teaching.course.read", "resources:read")
    items = []
    for registry_item in course_pack_registry():
        pack = load_course_pack_by_catalog(registry_item["catalog_key"])
        items.append({
            "pack_id": pack.pack_id,
            "course_id": pack.course_id,
            "title": pack.title,
            "version": pack.version,
            "language": pack.language,
            "content_origin": pack.content_origin,
            "commercial_bundle_allowed": pack.commercial_bundle_allowed,
            "theory_lessons": sum(item.lesson_type == "THEORY" for item in pack.lessons),
            "lab_lessons": sum(item.lesson_type == "LAB" for item in pack.lessons),
        })
    return {"items": items}


@router.get("/content-packs/{pack_id}", response_model=CoursePackManifest)
def get_content_pack(pack_id: str, user: CurrentUser):
    _require(user, "teaching.course.read", "resources:read")
    try:
        return load_course_pack_by_catalog(pack_id).model_dump(mode="json")
    except ValueError as error:
        raise ApiError("CONTENT_PACK.NOT_FOUND", "内容包不存在", 404) from error


@router.get("/content-sources", response_model=ContentSourcePolicyListResponse)
def list_content_sources(user: CurrentUser):
    _require(user, "teaching.course.read", "resources:read")
    items = []
    for source in SOURCES:
        decision = evaluate_license(source["license_id"])
        items.append({**source, "license_decision": decision.decision, "license_reason": decision.reason})
    return {"items": items}


@router.get("/content-packs/web_security_v1/lab-candidates", response_model=WebLabReadinessRegistryResponse)
def web_lab_candidates(user: CurrentUser):
    _require(user, "labs.read", "teaching.course.read")
    path = CONTENT_DIR / "web-security-lab-candidates-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/content-source-maps/seed", response_model=SeedDomainMapResponse)
def seed_domain_map(user: CurrentUser):
    _require(user, "teaching.course.read", "resources:read")
    path = CONTENT_DIR / "seed-domain-map-zh-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/content-sources/vulhub/index/preview", response_model=ExternalLabCandidateListResponse)
async def preview_vulhub_index(user: CurrentUser, file: Annotated[UploadFile, File()]):
    _require(user, "labs.read")
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ApiError("CONTENT_PACK.FILE_TOO_LARGE", "Vulhub 索引文件不得超过 2MB", 413)
    try:
        candidates = parse_environment_index(raw)
    except Exception as exc:
        raise ApiError("CONTENT_PACK.VULHUB_INDEX_INVALID", "Vulhub 索引解析失败", 422) from exc
    return {"items": [item.model_dump(mode="json") for item in candidates], "total": len(candidates)}


@router.post("/content-sources/compose/scan", response_model=ComposeScanResponse)
async def scan_compose(user: CurrentUser, file: Annotated[UploadFile, File()]):
    _require(user, "labs.read")
    raw = await file.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ApiError("CONTENT_PACK.FILE_TOO_LARGE", "Compose 文件不得超过 512KB", 413)
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except Exception as exc:
        raise ApiError("CONTENT_PACK.COMPOSE_INVALID", "Compose YAML 解析失败", 422) from exc
    if not isinstance(payload, dict):
        raise ApiError("CONTENT_PACK.COMPOSE_INVALID", "Compose 根节点必须是对象", 422)
    findings = scan_compose_manifest(payload)
    return {
        "passed": not any(item.blocking for item in findings),
        "findings": [
            {"code": item.code, "message": item.message, "service": item.service, "blocking": item.blocking}
            for item in findings
        ],
    }


@router.post("/content-sources/atomic-red-team/preview", response_model=AtomicTechniquePreviewResponse)
async def preview_atomic_red_team(user: CurrentUser, file: Annotated[UploadFile, File()]):
    _require(user, "labs.read", "teaching.course.read")
    raw = await file.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ApiError("CONTENT_PACK.FILE_TOO_LARGE", "Atomic YAML 不得超过 512KB", 413)
    try:
        return parse_atomic_technique(raw)
    except Exception as exc:
        raise ApiError("CONTENT_PACK.ATOMIC_INVALID", "Atomic Red Team 元数据解析失败", 422) from exc


@router.post("/content-sources/pwncollege/dojo/preview", response_model=DojoPreviewResponse)
async def preview_pwncollege_dojo(user: CurrentUser, file: Annotated[UploadFile, File()]):
    _require(user, "teaching.course.read")
    raw = await file.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ApiError("CONTENT_PACK.FILE_TOO_LARGE", "dojo.yml 不得超过 512KB", 413)
    try:
        return parse_dojo_manifest(raw)
    except Exception as exc:
        raise ApiError("CONTENT_PACK.DOJO_INVALID", "pwn.college dojo 元数据解析失败", 422) from exc
