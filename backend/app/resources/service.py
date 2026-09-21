from datetime import datetime
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import FileObject
from app.common.outbox import enqueue_event

from .catalog import COURSE_ID
from .models import (LabFilePack, LessonResource, PptAsset, Question, QuestionBank, QuestionExplanation, QuestionLessonMap,
                     QuestionOption, Resource, ResourceDeliveryManifest, ResourceQualityCheck, ResourceReview, ResourceVersion, VideoAsset)
from .media import probe_local_video
from .repository import ResourceRepository
from .schemas import QuestionCreate, QuestionPatch, ResourceCreate, VersionCreate

QUESTION_TYPES = {"FILL", "SINGLE", "MULTIPLE", "TRUE_FALSE"}


def now() -> datetime:
    return datetime.utcnow()


class ResourceService:
    def __init__(self, session: Session, user: UserContext):
        self.session, self.user = session, user
        self.repo = ResourceRepository(session)

    def _course(self, course_id: str, permission: str = "resources:read") -> None:
        if course_id not in self.user.course_ids and "resources:all-courses" not in self.user.permissions:
            raise ApiError("RESOURCE.COURSE_SCOPE_DENIED", "无权访问该课程资源", 403)
        if permission not in self.user.permissions and "resources:manage" not in self.user.permissions:
            raise ApiError("AUTH.PERMISSION_DENIED", "缺少课程资源操作权限", 403)

    def list_resources(self, course_id: str, status: str | None, name: str | None, resource_type: str | None) -> dict:
        self._course(course_id)
        items = self.repo.list_resources(course_id=course_id, status=status, name=name, resource_type=resource_type)
        if self.user.role == "student":
            items = [item for item in items if item.status in {"PUBLISHED", "FROZEN"}]
        return {"items": [self.resource_dict(item) for item in items], "page": 1, "page_size": len(items), "total": len(items)}

    def get_resource(self, resource_id: str) -> dict:
        item = self.repo.get_resource(resource_id)
        if not item:
            raise ApiError("RESOURCE.NOT_FOUND", "资源不存在或不可访问", 404)
        self._course(item.course_id)
        if self.user.role == "student" and item.status not in {"PUBLISHED", "FROZEN"}:
            raise ApiError("RESOURCE.NOT_FOUND", "资源不存在或不可访问", 404)
        latest = self.repo.latest_version(item.resource_id)
        result = self.resource_dict(item)
        result["latest_version"] = self.version_dict(latest) if latest else None
        return result

    def create_resource(self, data: ResourceCreate) -> dict:
        self._course(data.course_id, "resources:write")
        if data.lesson_id and not self.session.scalar(select(LessonResource).where(LessonResource.course_id == data.course_id, LessonResource.lesson_id == data.lesson_id)):
            raise ApiError("RESOURCE.LESSON_NOT_FOUND", "课时标识不属于该课程资源目录", 422)
        stamp = now()
        item = Resource(resource_id=str(uuid4()), **data.model_dump(), status="DRAFT", created_by=self.user.user_id, created_at=stamp, updated_at=stamp)
        self.repo.add(item)
        enqueue_event(self.session, event_type="resource.created", aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-created:{item.resource_id}", payload={"course_id": item.course_id, "lesson_id": item.lesson_id, "resource_type": item.resource_type})
        self.session.commit()
        return self.resource_dict(item)

    def create_version(self, resource_id: str, data: VersionCreate) -> dict:
        item = self._managed_resource(resource_id, "resources:write")
        if item.status == "FROZEN":
            raise ApiError("RESOURCE.VERSION_FROZEN", "冻结资源不可覆盖或新增版本", 409)
        file_object = self.session.get(FileObject, data.file_id)
        if not file_object or file_object.sha256 != data.sha256:
            raise ApiError("RESOURCE.FILE_SHA256_MISMATCH", "文件不存在或 SHA256（文件校验值）不匹配", 422)
        latest = self.repo.latest_version(resource_id)
        version = ResourceVersion(resource_version_id=str(uuid4()), resource_id=resource_id, version_no=(latest.version_no + 1 if latest else 1), file_id=data.file_id, status="DRAFT", sha256=data.sha256, created_by=self.user.user_id, created_at=now(), reviewed_by=None, reviewed_at=None, published_at=None)
        self.repo.add(version)
        if item.resource_type == "VIDEO":
            if file_object.storage_provider != "local":
                raise ApiError("RESOURCE.VIDEO_PROBE_PENDING", "对象存储视频须由媒体解析任务写入真实时长后再建版本", 409)
            duration, width, height = probe_local_video(file_object.object_key)
            self.repo.add(VideoAsset(video_asset_id=str(uuid4()), resource_version_id=version.resource_version_id, duration_seconds=duration, width=width, height=height, probed_at=now()))
        elif item.resource_type == "PPT":
            self.repo.add(PptAsset(ppt_asset_id=str(uuid4()), resource_version_id=version.resource_version_id, knowledge_complete=False, layout_overflow_passed=False, animation_occlusion_passed=False, copyright_noted=False, checked_by=None, checked_at=None))
        elif item.resource_type == "LAB_FILE":
            if not data.lab_file_count:
                raise ApiError("RESOURCE.LAB_FILE_COUNT_REQUIRED", "实验文件包必须记录文件数量", 422)
            self.repo.add(LabFilePack(lab_file_pack_id=str(uuid4()), resource_version_id=version.resource_version_id, file_count=data.lab_file_count, total_size_bytes=file_object.size_bytes))
        item.updated_at = now()
        enqueue_event(self.session, event_type="resource.version.created", aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-version:{version.resource_version_id}", payload={"resource_version_id": version.resource_version_id, "version_no": version.version_no, "sha256": version.sha256})
        self.session.commit()
        return self.version_dict(version)

    def check_ppt_quality(self, resource_id: str, version_id: str, data) -> dict:
        item = self._managed_resource(resource_id, "resources:review")
        version = self.session.get(ResourceVersion, version_id)
        asset = self.session.scalar(select(PptAsset).where(PptAsset.resource_version_id == version_id))
        if item.resource_type != "PPT" or not version or version.resource_id != resource_id or not asset:
            raise ApiError("RESOURCE.PPT_VERSION_NOT_FOUND", "PPT（演示文稿）版本不存在", 404)
        for key, value in data.model_dump().items(): setattr(asset, key, value)
        asset.checked_by, asset.checked_at = self.user.user_id, now()
        result = "PASS" if all(data.model_dump().values()) else "BLOCKING"
        self.repo.add(ResourceQualityCheck(resource_quality_check_id=str(uuid4()), course_id=item.course_id, resource_version_id=version_id, check_type="PPT_MANUAL_REVIEW", result=result, details_json=data.model_dump(), checked_by=self.user.user_id, checked_at=now()))
        self.session.commit()
        return {"resource_version_id": version_id, "result": result, **data.model_dump()}

    def transition(self, resource_id: str, action: str, comment: str | None = None) -> dict:
        permission = "resources:review" if action in {"approve", "reject"} else "resources:write"
        item = self._managed_resource(resource_id, permission)
        latest = self.repo.latest_version(resource_id)
        if not latest:
            raise ApiError("RESOURCE.VERSION_REQUIRED", "资源尚无可审核版本", 409)
        if action == "submit-review":
            if item.status == "PENDING_REVIEW": return self.resource_dict(item)
            if item.status not in {"DRAFT", "REJECTED"}:
                raise ApiError("RESOURCE.INVALID_TRANSITION", "当前状态不能提交审核", 409)
            item.status = latest.status = "PENDING_REVIEW"
        elif action in {"approve", "reject"}:
            existing = self.session.scalar(select(ResourceReview).where(ResourceReview.resource_version_id == latest.resource_version_id, ResourceReview.decision == ("APPROVED" if action == "approve" else "REJECTED")))
            if existing: return self.resource_dict(item)
            if item.status != "PENDING_REVIEW":
                raise ApiError("RESOURCE.INVALID_TRANSITION", "只有待审核资源可执行审核", 409)
            if action == "approve" and latest.created_by == self.user.user_id:
                raise ApiError("RESOURCE.REVIEWER_MUST_BE_INDEPENDENT", "资源制作者不能审核自己的版本", 409)
            decision = "APPROVED" if action == "approve" else "REJECTED"
            self.repo.add(ResourceReview(resource_review_id=str(uuid4()), resource_version_id=latest.resource_version_id, decision=decision, comment=comment, reviewer_id=self.user.user_id, reviewed_at=now()))
            latest.reviewed_by, latest.reviewed_at = self.user.user_id, now()
            if action == "reject":
                item.status = latest.status = "REJECTED"
        elif action == "publish":
            if item.status == "PUBLISHED": return self.resource_dict(item)
            approved = self.session.scalar(select(ResourceReview).where(ResourceReview.resource_version_id == latest.resource_version_id, ResourceReview.decision == "APPROVED"))
            if item.status != "PENDING_REVIEW" or not approved:
                raise ApiError("RESOURCE.APPROVAL_REQUIRED", "发布前必须通过独立审核", 409)
            item.status = latest.status = "PUBLISHED"
            latest.published_at = now()
        event_type = f"resource.{action.replace('-', '.')}"
        enqueue_event(self.session, event_type=event_type, aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"{event_type}:{latest.resource_version_id}", payload={"course_id": item.course_id, "resource_version_id": latest.resource_version_id})
        self.session.commit()
        return self.resource_dict(item)

    def lessons(self, course_id: str, kind: str | None = None) -> dict:
        self._course(course_id)
        rows = self.repo.lessons(course_id, kind)
        return {"items": [self.lesson_dict(row) for row in rows], "page": 1, "page_size": len(rows), "total": len(rows)}

    def create_question(self, data: QuestionCreate) -> dict:
        self._course(data.course_id, "resources:write")
        if not any(row.lesson_id == data.lesson_id for row in self.repo.lessons(data.course_id)):
            raise ApiError("QUESTION.LESSON_NOT_FOUND", "题目必须关联课程资源目录中的课时", 422)
        if not self.session.scalar(select(QuestionBank).where(QuestionBank.course_id == data.course_id)):
            self.repo.add(QuestionBank(question_bank_id=f"qb_{data.course_id}", course_id=data.course_id, name="课程统一题库", status="DRAFT", created_by=self.user.user_id, created_at=now()))
            self.session.flush()
        bank = self.session.scalar(select(QuestionBank).where(QuestionBank.course_id == data.course_id))
        question = Question(question_id=str(uuid4()), question_bank_id=bank.question_bank_id, question_type=data.question_type, stem=data.stem, answer_json=data.answer, status="DRAFT", created_by=self.user.user_id, created_at=now(), reviewed_by=None, reviewed_at=None)
        self.repo.add(question)
        self.repo.add(QuestionExplanation(question_id=question.question_id, explanation=data.explanation))
        self.repo.add(QuestionLessonMap(question_lesson_map_id=str(uuid4()), question_id=question.question_id, lesson_id=data.lesson_id))
        for index, option in enumerate(data.options):
            self.repo.add(QuestionOption(question_option_id=str(uuid4()), question_id=question.question_id, option_key=str(option.get("key", index + 1)), option_text=str(option.get("text", "")), is_correct=bool(option.get("is_correct", False))))
        enqueue_event(self.session, event_type="question.created", aggregate_type="question", aggregate_id=question.question_id, actor_user_id=self.user.user_id, idempotency_key=f"question-created:{question.question_id}", payload={"course_id": data.course_id, "lesson_id": data.lesson_id, "question_type": data.question_type})
        self.session.commit()
        return self.question_dict(question, data.lesson_id, data.explanation)

    def patch_question(self, question_id: str, data: QuestionPatch) -> dict:
        question = self.session.get(Question, question_id)
        if not question or question.status != "DRAFT":
            raise ApiError("QUESTION.NOT_EDITABLE", "题目不存在或已审核，不能覆盖修改", 409)
        bank = self.session.get(QuestionBank, question.question_bank_id)
        self._course(bank.course_id, "resources:write")
        if data.stem is not None: question.stem = data.stem
        if data.answer is not None:
            if not data.answer: raise ApiError("QUESTION.ANSWER_REQUIRED", "答案不能为空", 422)
            question.answer_json = data.answer
        if data.explanation is not None:
            self.session.get(QuestionExplanation, question_id).explanation = data.explanation
        enqueue_event(self.session, event_type="question.updated", aggregate_type="question", aggregate_id=question.question_id, actor_user_id=self.user.user_id, idempotency_key=f"question-updated:{question.question_id}:{uuid4()}", payload={"course_id": bank.course_id})
        self.session.commit()
        return {"question_id": question.question_id, "status": question.status}

    def review_question(self, question_id: str) -> dict:
        question = self.session.get(Question, question_id)
        if not question: raise ApiError("QUESTION.NOT_FOUND", "题目不存在", 404)
        bank = self.session.get(QuestionBank, question.question_bank_id)
        self._course(bank.course_id, "resources:review")
        if question.created_by == self.user.user_id: raise ApiError("QUESTION.REVIEWER_MUST_BE_INDEPENDENT", "出题人不能审核自己的题目", 409)
        explanation = self.session.get(QuestionExplanation, question_id)
        mapping = self.session.scalar(select(QuestionLessonMap).where(QuestionLessonMap.question_id == question_id))
        if not question.answer_json or not explanation or not explanation.explanation or not mapping:
            raise ApiError("QUESTION.INCOMPLETE", "答案、解析和课时映射必须完整", 422)
        question.status, question.reviewed_by, question.reviewed_at = "PUBLISHED", self.user.user_id, now()
        enqueue_event(self.session, event_type="question.published", aggregate_type="question", aggregate_id=question.question_id, actor_user_id=self.user.user_id, idempotency_key=f"question-published:{question.question_id}", payload={"course_id": bank.course_id, "lesson_id": mapping.lesson_id})
        self.session.commit()
        return {"question_id": question.question_id, "status": question.status}

    def coverage(self, course_id: str) -> dict:
        self._course(course_id)
        coverage = self.repo.question_coverage(course_id)
        counts = self.repo.question_counts(course_id)
        lessons = self.repo.lessons(course_id)
        items = [{"lesson_id": row.lesson_id, "lesson_code": row.lesson_code, "types": sorted(coverage.get(row.lesson_id, set())), "question_count": counts.get(row.lesson_id, 0), "passed": coverage.get(row.lesson_id, set()) == QUESTION_TYPES and counts.get(row.lesson_id, 0) == 4} for row in lessons]
        return {"items": items, "total": len(items), "passed": sum(item["passed"] for item in items)}

    def audit(self, course_id: str, *, persist: bool = True) -> dict:
        self._course(course_id)
        lessons = self.repo.lessons(course_id)
        assets, coverage, counts, durations = self.repo.asset_counts(course_id), self.repo.question_coverage(course_id), self.repo.question_counts(course_id), self.repo.video_durations(course_id)
        checks, blockers = [], []
        for lesson in lessons:
            if lesson.lesson_kind == "THEORY":
                requirements = {"PPT": "PPT", "VIDEO": "讲解视频", "QUESTION_BANK": "四类题型", "REVIEW": "审核发布"}
                passed = {
                    "PPT": "PPT" in assets.get(lesson.lesson_id, set()),
                    "VIDEO": "VIDEO" in assets.get(lesson.lesson_id, set()) and durations.get(lesson.lesson_id, 0) > 0,
                    "QUESTION_BANK": coverage.get(lesson.lesson_id, set()) == QUESTION_TYPES and counts.get(lesson.lesson_id, 0) == 4,
                    "REVIEW": {"PPT", "VIDEO"}.issubset(assets.get(lesson.lesson_id, set())) and coverage.get(lesson.lesson_id, set()) == QUESTION_TYPES and counts.get(lesson.lesson_id, 0) == 4,
                }
            else:
                requirements = {"INTRO": "介绍三段", "LAB_FILE": "实验文件", "VIDEO": "讲解视频", "QUESTION_BANK": "四类题型"}
                passed = {
                    "INTRO": bool(lesson.purpose and lesson.environment and lesson.principle),
                    "LAB_FILE": "LAB_FILE" in assets.get(lesson.lesson_id, set()),
                    "VIDEO": "VIDEO" in assets.get(lesson.lesson_id, set()) and durations.get(lesson.lesson_id, 0) > 0,
                    "QUESTION_BANK": coverage.get(lesson.lesson_id, set()) == QUESTION_TYPES and counts.get(lesson.lesson_id, 0) == 4,
                }
            for key, label in requirements.items():
                check = {"lesson_id": lesson.lesson_id, "lesson_code": lesson.lesson_code, "requirement": key, "passed": passed[key]}
                checks.append(check)
                if not passed[key]: blockers.append(f"{lesson.lesson_code} 缺少{label}")
        result = {"course_id": course_id, "total": len(checks), "pass": sum(x["passed"] for x in checks), "warning": 0, "blocking": len(blockers), "blocking_items": blockers, "procurement_mapping": self.procurement_mapping(), "checked_at": now().isoformat() + "Z"}
        if persist:
            self.repo.add(ResourceQualityCheck(resource_quality_check_id=str(uuid4()), course_id=course_id, resource_version_id=None, check_type="COURSE_AUDIT", result="PASS" if not blockers else "BLOCKING", details_json=result, checked_by=self.user.user_id, checked_at=now()))
            enqueue_event(self.session, event_type="resource.audit.completed", aggregate_type="course_resource", aggregate_id=course_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-audit:{uuid4()}", payload={"blocking": len(blockers), "pass": result["pass"], "total": result["total"]})
            self.session.commit()
        return result

    def latest_audit(self, course_id: str) -> dict:
        self._course(course_id)
        row = self.repo.latest_audit(course_id)
        return row.details_json if row else self.audit(course_id, persist=False)

    def freeze(self, course_id: str) -> dict:
        self._course(course_id, "resources:freeze")
        audit = self.audit(course_id, persist=False)
        if audit["blocking"]:
            raise ApiError("RESOURCE.DELIVERY_BLOCKED", "存在资源阻断项，不能冻结交付", 409, {"blocking": audit["blocking"], "blocking_items": audit["blocking_items"]})
        latest = self.repo.latest_manifest(course_id)
        version_no = latest.version_no + 1 if latest else 1
        manifest = self.manifest(course_id, audit)
        manifest.update({"status": "FROZEN", "version_no": version_no})
        row = ResourceDeliveryManifest(resource_delivery_manifest_id=str(uuid4()), course_id=course_id, version_no=version_no, status="FROZEN", manifest_json=manifest, frozen_by=self.user.user_id, frozen_at=now())
        self.repo.add(row)
        for resource in self.repo.list_resources(course_id=course_id, status="PUBLISHED", name=None, resource_type=None):
            resource.status = "FROZEN"
            for version in self.session.scalars(select(ResourceVersion).where(ResourceVersion.resource_id == resource.resource_id, ResourceVersion.status == "PUBLISHED")): version.status = "FROZEN"
        enqueue_event(self.session, event_type="resource.delivery.frozen", aggregate_type="course_resource", aggregate_id=course_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-delivery:{course_id}:{row.version_no}", payload={"course_id": course_id, "manifest_id": row.resource_delivery_manifest_id, "version_no": row.version_no})
        self.session.commit()
        return manifest

    def manifest(self, course_id: str, audit: dict | None = None) -> dict:
        self._course(course_id)
        audit = audit or self.latest_audit(course_id)
        latest = self.repo.latest_manifest(course_id)
        return {"course_id": course_id, "theory_lessons": 37, "lab_lessons": 12, "audit": audit, "status": latest.status if latest else ("READY" if audit["blocking"] == 0 else "BLOCKED"), "version_no": latest.version_no if latest else None, "generated_at": now().isoformat() + "Z", "content_declaration": "目录结构已建立；只有已上传、校验、审核的真实文件才计入完成。"}

    def manifest_xlsx(self, course_id: str) -> bytes:
        data = self.manifest(course_id)
        book = Workbook(); sheet = book.active; sheet.title = "交付清单"
        sheet.append(["课程标识", data["course_id"]]); sheet.append(["理论课时", data["theory_lessons"]]); sheet.append(["实验课时", data["lab_lessons"]]); sheet.append(["状态", data["status"]]); sheet.append(["阻断项", data["audit"]["blocking"]])
        sheet.append([]); sheet.append(["阻断明细"])
        for item in data["audit"]["blocking_items"]: sheet.append([item])
        buffer = BytesIO(); book.save(buffer); return buffer.getvalue()

    def _managed_resource(self, resource_id: str, permission: str) -> Resource:
        item = self.repo.get_resource(resource_id)
        if not item: raise ApiError("RESOURCE.NOT_FOUND", "资源不存在或不可访问", 404)
        self._course(item.course_id, permission); return item

    @staticmethod
    def resource_dict(item: Resource) -> dict:
        return {"resource_id": item.resource_id, "course_id": item.course_id, "lesson_id": item.lesson_id, "name": item.name, "resource_type": item.resource_type, "status": item.status, "created_by": item.created_by, "created_at": item.created_at.isoformat()}

    @staticmethod
    def version_dict(item: ResourceVersion) -> dict:
        return {"resource_version_id": item.resource_version_id, "version_no": item.version_no, "file_id": item.file_id, "status": item.status, "sha256": item.sha256, "created_by": item.created_by, "created_at": item.created_at.isoformat()}

    @staticmethod
    def lesson_dict(item) -> dict:
        return {key: getattr(item, key) for key in ["course_id", "lesson_id", "lesson_kind", "chapter_no", "lesson_code", "title", "purpose", "environment", "principle", "steps_summary", "core_experiment", "linked_file_pack_id", "linked_video_resource_id", "linked_lab_definition_id"]}

    @staticmethod
    def question_dict(item, lesson_id: str, explanation: str) -> dict:
        return {"question_id": item.question_id, "question_type": item.question_type, "stem": item.stem, "answer": item.answer_json, "status": item.status, "lesson_id": lesson_id, "explanation": explanation}

    @staticmethod
    def procurement_mapping() -> list[dict]:
        return [
            {"requirement": "课程资源管理", "owner": "B", "evidence": "状态/名称/类型三维筛选"},
            {"requirement": "理论课程资源", "owner": "B", "evidence": "37 理论课时资源门禁"},
            {"requirement": "实验课程资源", "owner": "B", "evidence": "12 实验课时与 8 类核心映射"},
            {"requirement": "签到、投票", "owner": "A", "evidence": "只读 API 聚合，B 不读取 A 表"},
            {"requirement": "知识点讲解图、场景、DAG", "owner": "C", "evidence": "冻结标识引用"},
            {"requirement": "实例", "owner": "D/E", "evidence": "只读 API 聚合"},
            {"requirement": "日志、学情", "owner": "E/F", "evidence": "只读 API 聚合"},
        ]
