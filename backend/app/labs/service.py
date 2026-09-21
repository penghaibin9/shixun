from datetime import datetime, timezone
from os import getenv
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event
from app.common.models import FileObject
from app.common.models import DomainEventOutbox

from . import models
from .repository import LabRepository, new_id
from .schemas import CloneVersionInput, KnowledgeInput, LabCreate, LabDefinitionSpec, LabVersionPatch, ReleaseCreate, TemplateCreate


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LabService:
    def __init__(self, session: Session, user: UserContext):
        self.session = session
        self.user = user
        self.repo = LabRepository(session)

    def _permission(self, name: str) -> None:
        if name not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "当前账号没有此操作权限", 403, {"required_permission": name})

    def _course_scope(self, course_id: str) -> None:
        if course_id not in self.user.course_ids:
            raise ApiError("AUTH.COURSE_SCOPE_DENIED", "无权访问该课程的实验", 403, {"course_id": course_id})

    def _class_scope(self, class_id: str) -> None:
        if class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "发布班级不在当前账号的数据范围内", 403, {"class_id": class_id})

    def list_labs(self) -> list[dict]:
        self._permission("labs.read")
        result = []
        for item in self.repo.definitions(self.user.course_ids):
            version = self.repo.latest_version(item.lab_definition_id)
            result.append(self._definition_view(item, version))
        return result

    def get_lab(self, definition_id: str) -> dict:
        self._permission("labs.read")
        definition = self._definition(definition_id)
        return self._definition_view(definition, self.repo.latest_version(definition_id))

    def create_lab(self, data: LabCreate, idempotency_key: str) -> dict:
        self._permission("labs.write")
        self._course_scope(data.course_id)
        previous = self._idempotent_aggregate("lab.definition.created", idempotency_key)
        if previous:
            return self.get_lab(previous)
        if data.spec.version != 1:
            raise ApiError("LAB.INVALID_INITIAL_VERSION", "新实验的首个版本必须是 1", 422)
        stamp = now()
        definition_id = data.spec.lab_definition_id
        definition = models.LabDefinition(
            lab_definition_id=definition_id, course_id=data.course_id, code=data.code,
            name=data.spec.name, category=data.category, objective=data.objective,
            created_by=self.user.user_id, created_at=stamp, updated_at=stamp,
        )
        version = models.LabVersion(
            lab_version_id=new_id("labv"), lab_definition_id=definition_id, version=1,
            status="DRAFT", spec_json=data.spec.model_dump(mode="json"), validation_errors_json=[],
            created_by=self.user.user_id, created_at=stamp, updated_at=stamp,
        )
        try:
            self.repo.add_definition(definition, version, data.spec)
            enqueue_event(self.session, event_type="lab.definition.created", aggregate_type="lab_definition", aggregate_id=definition_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"course_id": data.course_id, "lab_version_id": version.lab_version_id})
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise ApiError("LAB.DUPLICATE", "实验编号、标识或幂等键已存在", 409) from error
        return self._definition_view(definition, version)

    def get_version(self, version_id: str) -> dict:
        self._permission("labs.read")
        version = self._version(version_id)
        return self._version_view(version)

    def clone_version(self, definition_id: str, data: CloneVersionInput, idempotency_key: str) -> dict:
        self._permission("labs.write")
        definition = self._definition(definition_id)
        previous = self._idempotent_aggregate("lab.version.cloned", idempotency_key)
        if previous:
            return self._version_view(self._version(previous))
        source = self._version(data.source_lab_version_id) if data.source_lab_version_id else self.repo.latest_version(definition_id)
        if not source or source.lab_definition_id != definition_id:
            raise ApiError("LAB.VERSION_NOT_FOUND", "克隆来源版本不存在", 404)
        number = self.repo.next_version_number(definition_id)
        cloned_spec = {**source.spec_json, "version": number}
        cloned_spec["checkpoints"] = [
            {**checkpoint, "checkpoint_id": new_id("cp")}
            for checkpoint in source.spec_json["checkpoints"]
        ]
        spec = LabDefinitionSpec.model_validate(cloned_spec)
        stamp = now()
        clone = models.LabVersion(lab_version_id=new_id("labv"), lab_definition_id=definition_id, version=number, status="DRAFT", spec_json=spec.model_dump(mode="json"), validation_errors_json=[], created_by=self.user.user_id, created_at=stamp, updated_at=stamp)
        self.session.add(clone)
        self.session.flush()
        self.repo.replace_version_detail(clone.lab_version_id, spec)
        enqueue_event(self.session, event_type="lab.version.cloned", aggregate_type="lab_version", aggregate_id=clone.lab_version_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"source_lab_version_id": source.lab_version_id, "version": number})
        self.session.commit()
        return self._version_view(clone)

    def patch_version(self, version_id: str, data: LabVersionPatch, idempotency_key: str) -> dict:
        self._permission("labs.write")
        if self._idempotent_aggregate("lab.version.updated", idempotency_key):
            return self._version_view(self._version(version_id))
        version = self._version(version_id, lock=True)
        if version.status == "PUBLISHED":
            raise ApiError("LAB.VERSION_IMMUTABLE", "已发布实验版本不可修改，请克隆为新草稿", 409)
        definition = self._definition(version.lab_definition_id)
        if data.spec.lab_definition_id != definition.lab_definition_id or data.spec.version != version.version:
            raise ApiError("LAB.VERSION_ID_MISMATCH", "实验标识或版本号与目标版本不一致", 422)
        version.spec_json = data.spec.model_dump(mode="json")
        version.status = "DRAFT"
        version.validation_errors_json = []
        version.updated_at = now()
        definition.name = data.spec.name
        definition.updated_at = version.updated_at
        self.repo.replace_version_detail(version_id, data.spec)
        enqueue_event(self.session, event_type="lab.version.updated", aggregate_type="lab_version", aggregate_id=version_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"version": version.version})
        self.session.commit()
        return self._version_view(version)

    def validate_version(self, version_id: str, idempotency_key: str) -> dict:
        self._permission("labs.write")
        if self._idempotent_aggregate("lab.version.validated", idempotency_key):
            return self._version_view(self._version(version_id))
        version = self._version(version_id, lock=True)
        if version.status == "PUBLISHED":
            return self._version_view(version)
        spec = LabDefinitionSpec.model_validate(version.spec_json)
        errors = publishability_errors(spec)
        version.validation_errors_json = errors
        version.status = "READY" if not errors else "DRAFT"
        version.updated_at = now()
        enqueue_event(self.session, event_type="lab.version.validated", aggregate_type="lab_version", aggregate_id=version_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"ready": not errors, "errors": errors})
        self.session.commit()
        if errors:
            raise ApiError("LAB.VALIDATION_FAILED", "实验版本未通过发布门禁", 422, {"errors": errors})
        return self._version_view(version)

    def publish_version(self, version_id: str, idempotency_key: str) -> dict:
        self._permission("labs.publish")
        if self._idempotent_aggregate("lab.version.published", idempotency_key):
            return self._version_view(self._version(version_id))
        version = self._version(version_id, lock=True)
        if version.status != "READY":
            raise ApiError("LAB.VERSION_NOT_READY", "仅已通过校验的版本可以发布", 409, {"status": version.status})
        if publishability_errors(LabDefinitionSpec.model_validate(version.spec_json)):
            raise ApiError("LAB.VALIDATION_STALE", "实验定义已不满足发布门禁，请重新校验", 409)
        version.status = "PUBLISHED"
        version.published_at = now()
        version.updated_at = version.published_at
        enqueue_event(self.session, event_type="lab.version.published", aggregate_type="lab_version", aggregate_id=version_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"lab_definition_id": version.lab_definition_id, "version": version.version})
        self.session.commit()
        return self._version_view(version)

    def templates(self) -> list[dict]:
        self._permission("labs.read")
        return [{"template_id": x.template_id, "name": x.name, "description": x.description, "spec": x.spec_json} for x in self.repo.templates()]

    def create_template(self, data: TemplateCreate, idempotency_key: str) -> dict:
        self._permission("labs.write")
        previous = self._idempotent_aggregate("lab.template.created", idempotency_key)
        if previous:
            item = self.session.get(models.LabTemplate, previous)
            if item:
                return {"template_id": item.template_id, "name": item.name, "description": item.description, "spec": item.spec_json}
        item = models.LabTemplate(template_id=new_id("labt"), name=data.name, description=data.description, spec_json=data.spec, created_by=self.user.user_id, created_at=now())
        self.session.add(item)
        enqueue_event(self.session, event_type="lab.template.created", aggregate_type="lab_template", aggregate_id=item.template_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"name": item.name})
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise ApiError("LAB.TEMPLATE_DUPLICATE", "模板名称已存在", 409) from error
        return {"template_id": item.template_id, "name": item.name, "description": item.description, "spec": item.spec_json}

    def knowledge(self) -> list[dict]:
        self._permission("labs.read")
        return [self._knowledge_view(item) for item in self.repo.knowledge(self.user.course_ids)]

    def create_knowledge(self, data: KnowledgeInput, idempotency_key: str) -> dict:
        self._permission("labs.knowledge.write")
        self._course_scope(data.course_id)
        previous = self._idempotent_aggregate("lab.knowledge.created", idempotency_key)
        if previous:
            item = self.session.get(models.LabKnowledgePoint, previous)
            if item:
                return self._knowledge_view(item)
        stamp = now()
        item = models.LabKnowledgePoint(knowledge_point_id=new_id("kp"), course_id=data.course_id, title=data.title, explain_text=data.explain_text, created_by=self.user.user_id, created_at=stamp, updated_at=stamp)
        self.session.add(item)
        self.session.flush()
        self.repo.replace_knowledge_children(item.knowledge_point_id, data.question_ids, data.diagrams)
        enqueue_event(self.session, event_type="lab.knowledge.created", aggregate_type="lab_knowledge_point", aggregate_id=item.knowledge_point_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"course_id": data.course_id})
        self.session.commit()
        return self._knowledge_view(item)

    def patch_knowledge(self, knowledge_id: str, data: KnowledgeInput, idempotency_key: str) -> dict:
        self._permission("labs.knowledge.write")
        if self._idempotent_aggregate("lab.knowledge.updated", idempotency_key):
            item = self.session.get(models.LabKnowledgePoint, knowledge_id)
            if item:
                return self._knowledge_view(item)
        item = self.session.get(models.LabKnowledgePoint, knowledge_id)
        if not item:
            raise ApiError("LAB.KNOWLEDGE_NOT_FOUND", "知识点不存在", 404)
        self._course_scope(item.course_id)
        if data.course_id != item.course_id:
            raise ApiError("LAB.KNOWLEDGE_COURSE_IMMUTABLE", "知识点所属课程不可变更", 409)
        item.title, item.explain_text, item.updated_at = data.title, data.explain_text, now()
        self.repo.replace_knowledge_children(knowledge_id, data.question_ids, data.diagrams)
        enqueue_event(self.session, event_type="lab.knowledge.updated", aggregate_type="lab_knowledge_point", aggregate_id=knowledge_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"course_id": item.course_id})
        self.session.commit()
        return self._knowledge_view(item)

    def diagram_download(self, knowledge_id: str, diagram_id: str) -> tuple[Path, str, str]:
        self._permission("labs.read")
        item = self.session.get(models.LabKnowledgePoint, knowledge_id)
        if not item:
            raise ApiError("LAB.KNOWLEDGE_NOT_FOUND", "知识点不存在", 404)
        self._course_scope(item.course_id)
        diagram = self.session.get(models.LabExplainDiagram, diagram_id)
        if not diagram or diagram.knowledge_point_id != knowledge_id:
            raise ApiError("LAB.DIAGRAM_NOT_FOUND", "讲解图不存在", 404)
        file_object = self.session.get(FileObject, diagram.file_id)
        if not file_object or file_object.storage_provider != "BUNDLED":
            raise ApiError("FILE.NOT_AVAILABLE", "讲解图文件当前不可下载", 404)
        path = Path(__file__).with_name("fixtures") / Path(file_object.object_key).name
        if not path.is_file():
            raise ApiError("FILE.NOT_AVAILABLE", "讲解图文件当前不可下载", 404)
        return path, file_object.original_name, file_object.mime_type

    def create_release(self, data: ReleaseCreate, idempotency_key: str) -> dict:
        self._permission("labs.publish")
        self._course_scope(data.course_id)
        self._class_scope(data.class_id)
        previous = self._idempotent_aggregate("lab.release.created", idempotency_key)
        if previous:
            item = self._release(previous)
            return self._release_view(item, self.repo.publish_config(previous))
        version = self._version(data.lab_version_id)
        definition = self._definition(version.lab_definition_id)
        if definition.course_id != data.course_id:
            raise ApiError("LAB.RELEASE_COURSE_MISMATCH", "实验版本不属于发布课程", 422)
        if version.status != "PUBLISHED":
            raise ApiError("LAB.RELEASE_VERSION_NOT_PUBLISHED", "只能发布不可变的已发布实验版本", 409)
        release = models.LabRelease(lab_release_id=new_id("labr"), lab_version_id=version.lab_version_id, course_id=data.course_id, class_id=data.class_id, lesson_id=data.lesson_id, status="SCHEDULED", created_by=self.user.user_id, created_at=now())
        self.session.add(release)
        self.session.flush()
        config = models.LabPublishConfig(publish_config_id=new_id("lpc"), lab_release_id=release.lab_release_id, opens_at=data.opens_at.replace(tzinfo=None), closes_at=data.closes_at.replace(tzinfo=None), max_attempts=data.max_attempts, timeout_minutes=data.timeout_minutes, max_concurrency=data.max_concurrency, teacher_preview_required=data.teacher_preview_required, preflight_json={}, preview_request_id=None)
        self.session.add(config)
        enqueue_event(self.session, event_type="lab.release.created", aggregate_type="lab_release", aggregate_id=release.lab_release_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"class_id": data.class_id, "lab_version_id": version.lab_version_id})
        self.session.commit()
        return self._release_view(release, config)

    def preflight_release(self, release_id: str, idempotency_key: str) -> dict:
        self._permission("labs.publish")
        release = self._release(release_id)
        config = self.repo.publish_config(release_id)
        if self._idempotent_aggregate("lab.release.preflighted", idempotency_key):
            return config.preflight_json
        version = self._version(release.lab_version_id)
        errors = publishability_errors(LabDefinitionSpec.model_validate(version.spec_json))
        checks = {"version_published": version.status == "PUBLISHED", "definition_valid": not errors, "class_in_scope": release.class_id in self.user.class_ids, "time_window_valid": config.closes_at > config.opens_at}
        config.preflight_json = {"passed": all(checks.values()), "checks": checks, "errors": errors, "checked_at": now().isoformat()}
        enqueue_event(self.session, event_type="lab.release.preflighted", aggregate_type="lab_release", aggregate_id=release_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"passed": config.preflight_json["passed"]})
        self.session.commit()
        if not config.preflight_json["passed"]:
            raise ApiError("LAB.RELEASE_PREFLIGHT_FAILED", "实验发布预检未通过", 422, config.preflight_json)
        return config.preflight_json

    async def teacher_preview(self, release_id: str, idempotency_key: str) -> dict:
        self._permission("labs.publish")
        release = self._release(release_id)
        config = self.repo.publish_config(release_id)
        if self._idempotent_aggregate("lab.release.preview.requested", idempotency_key) and config.preview_request_id:
            return {"status": "QUEUED", "runtime_request_id": config.preview_request_id}
        if not config.preflight_json.get("passed"):
            raise ApiError("LAB.PREFLIGHT_REQUIRED", "请先通过发布预检", 409)
        provider = getenv("YUEKE_RUNTIME_PROVIDER_URL")
        if not provider:
            raise ApiError("LAB.RUNTIME_PROVIDER_UNAVAILABLE", "实验运行服务尚未就绪，教师预演未执行", 503, {"provider": "D 实验运行底座"})
        payload = {"lab_release_id": release_id, "lab_version_id": release.lab_version_id, "mode": "TEACHER_PREVIEW", "requested_by": self.user.user_id, "idempotency_key": idempotency_key}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(f"{provider.rstrip('/')}/api/v1/runtime/preview-requests", json=payload)
            if response.status_code >= 400:
                raise RuntimeError(f"status={response.status_code}")
            result = response.json()
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            raise ApiError("LAB.RUNTIME_PROVIDER_UNAVAILABLE", "实验运行服务不可用，教师预演未执行", 503) from error
        config.preview_request_id = result["runtime_request_id"]
        enqueue_event(self.session, event_type="lab.release.preview.requested", aggregate_type="lab_release", aggregate_id=release_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"runtime_request_id": config.preview_request_id, "lab_version_id": release.lab_version_id})
        self.session.commit()
        return {"status": "QUEUED", "runtime_request_id": config.preview_request_id}

    def publish_release(self, release_id: str, idempotency_key: str) -> dict:
        self._permission("labs.publish")
        if self._idempotent_aggregate("lab.release.published", idempotency_key):
            item = self._release(release_id)
            return self._release_view(item, self.repo.publish_config(release_id))
        release = self._release(release_id, lock=True)
        config = self.repo.publish_config(release_id)
        if not config.preflight_json.get("passed"):
            raise ApiError("LAB.PREFLIGHT_REQUIRED", "请先通过发布预检", 409)
        if config.teacher_preview_required and not config.preview_request_id:
            raise ApiError("LAB.TEACHER_PREVIEW_REQUIRED", "教师预演尚未由运行服务受理", 409)
        release.status = "OPEN" if config.opens_at <= now() < config.closes_at else "SCHEDULED"
        release.published_at = now()
        enqueue_event(self.session, event_type="lab.release.published", aggregate_type="lab_release", aggregate_id=release_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key, payload={"lab_version_id": release.lab_version_id, "course_id": release.course_id, "class_id": release.class_id, "lesson_id": release.lesson_id})
        self.session.commit()
        return self._release_view(release, config)

    def _definition(self, definition_id: str) -> models.LabDefinition:
        item = self.repo.definition(definition_id)
        if not item:
            raise ApiError("LAB.NOT_FOUND", "实验不存在", 404)
        self._course_scope(item.course_id)
        return item

    def _idempotent_aggregate(self, event_type: str, idempotency_key: str) -> str | None:
        return self.session.scalar(select(DomainEventOutbox.aggregate_id).where(DomainEventOutbox.event_type == event_type, DomainEventOutbox.idempotency_key == idempotency_key))

    def _version(self, version_id: str | None, *, lock: bool = False) -> models.LabVersion:
        item = self.repo.version(version_id or "", lock=lock)
        if not item:
            raise ApiError("LAB.VERSION_NOT_FOUND", "实验版本不存在", 404)
        self._definition(item.lab_definition_id)
        return item

    def _release(self, release_id: str, *, lock: bool = False) -> models.LabRelease:
        item = self.repo.release(release_id, lock=lock)
        if not item:
            raise ApiError("LAB.RELEASE_NOT_FOUND", "实验发布不存在", 404)
        self._course_scope(item.course_id)
        self._class_scope(item.class_id)
        return item

    @staticmethod
    def _definition_view(item: models.LabDefinition, version: models.LabVersion | None) -> dict:
        return {"lab_definition_id": item.lab_definition_id, "course_id": item.course_id, "code": item.code, "name": item.name, "category": item.category, "objective": item.objective, "latest_version": LabService._version_view(version) if version else None}

    @staticmethod
    def _version_view(item: models.LabVersion | None) -> dict | None:
        if not item:
            return None
        return {"lab_version_id": item.lab_version_id, "lab_definition_id": item.lab_definition_id, "version": item.version, "status": item.status, "spec": item.spec_json, "validation_errors": item.validation_errors_json, "published_at": item.published_at.isoformat() if item.published_at else None}

    def _knowledge_view(self, item: models.LabKnowledgePoint) -> dict:
        return {"knowledge_point_id": item.knowledge_point_id, "course_id": item.course_id, "title": item.title, "explain_text": item.explain_text, "question_ids": self.repo.question_ids(item.knowledge_point_id), "diagrams": [{"diagram_id": x.diagram_id, "file_id": x.file_id, "title": x.title, "order_no": x.order_no} for x in self.repo.diagrams(item.knowledge_point_id)]}

    @staticmethod
    def _release_view(item: models.LabRelease, config: models.LabPublishConfig) -> dict:
        return {"lab_release_id": item.lab_release_id, "lab_version_id": item.lab_version_id, "course_id": item.course_id, "class_id": item.class_id, "lesson_id": item.lesson_id, "status": item.status, "publish_config": {"opens_at": config.opens_at.isoformat(), "closes_at": config.closes_at.isoformat(), "max_attempts": config.max_attempts, "timeout_minutes": config.timeout_minutes, "max_concurrency": config.max_concurrency, "teacher_preview_required": config.teacher_preview_required, "preflight": config.preflight_json, "preview_request_id": config.preview_request_id}}


def publishability_errors(spec: LabDefinitionSpec) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    score = sum(item.score for item in spec.checkpoints)
    if score != spec.total_score:
        errors.append({"code": "CHECKPOINT_SCORE_MISMATCH", "message": f"得分点合计 {score}，实验总分 {spec.total_score}"})
    if not spec.nodes or not spec.networks:
        errors.append({"code": "SCENE_INCOMPLETE", "message": "场景至少需要一个节点和一个网络"})
    if not spec.steps:
        errors.append({"code": "DAG_EMPTY", "message": "实验至少需要一个 DAG 步骤"})
    graph = {node.node_key: [] for node in spec.steps}
    indegree = {node.node_key: 0 for node in spec.steps}
    for edge in spec.edges:
        graph[edge.from_node_key].append(edge.to_node_key)
        indegree[edge.to_node_key] += 1
    queue = [key for key, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        key = queue.pop()
        visited += 1
        for target in graph[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(graph):
        errors.append({"code": "DAG_CYCLE", "message": "实验步骤存在循环依赖"})
    return errors
