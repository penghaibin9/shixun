from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import FileObject
from app.common.outbox import enqueue_event
from app.teaching.models import Course, CourseLesson

from .catalog import COURSE_ID
from .models import (
    LabFilePack,
    LessonResource,
    PptAsset,
    Question,
    QuestionBank,
    QuestionExplanation,
    QuestionImportJob,
    QuestionImportRow,
    QuestionLessonMap,
    QuestionOption,
    QuestionReview,
    Resource,
    ResourceDeliveryManifest,
    ResourceQualityCheck,
    ResourceReview,
    ResourceVersion,
    VideoAsset,
)
from .media import probe_local_video
from .question_xlsx import MAX_XLSX_UPLOAD_BYTES, InvalidQuestionWorkbook, error_rows_bytes, parse_question_workbook, template_bytes
from .repository import ResourceLesson, ResourceRepository
from .schemas import QuestionCreate, QuestionPatch, ResourceCreate, VersionCreate
from .storage import archive_file_count, save_upload, upload_root

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
        if not self.session.get(Course, course_id):
            raise ApiError("RESOURCE.COURSE_NOT_FOUND", "课程不存在，请先在教学核心中创建课程", 404)

    def list_resources(self, course_id: str, status: str | None, name: str | None, resource_type: str | None) -> dict:
        self._course(course_id)
        items = self.repo.list_resources(course_id=course_id, status=status, name=name, resource_type=resource_type)
        if self.user.role == "student":
            items = [item for item in items if item.status in {"PUBLISHED", "FROZEN"}]
        values = []
        for item in items:
            value = self.resource_dict(item)
            latest = self.repo.latest_version(item.resource_id)
            value["latest_version"] = self.version_dict(latest) if latest else None
            values.append(value)
        return {"items": values, "page": 1, "page_size": len(items), "total": len(items)}

    async def upload_file(self, course_id: str, upload) -> dict:
        self._course(course_id, "resources:write")
        stored = await save_upload(upload)
        existing = self.session.scalar(select(FileObject).where(FileObject.sha256 == stored["sha256"], FileObject.size_bytes == stored["size_bytes"]))
        if existing:
            stored["path"].unlink(missing_ok=True)
            if existing.storage_provider == "local":
                existing_path = Path(existing.object_key).resolve()
                root = upload_root()
                if existing.bucket == "course-resources" and existing_path.is_file() and root in existing_path.parents:
                    return self.file_dict(existing)
            raise ApiError("RESOURCE.FILE_CONTENT_CONFLICT", "相同内容已由其他受控存储登记，不能跨域复用", 409)
        item = FileObject(file_id=str(uuid4()), storage_provider="local", bucket="course-resources", object_key=str(stored["path"]), original_name=stored["original_name"], mime_type=stored["mime_type"], size_bytes=stored["size_bytes"], sha256=stored["sha256"], created_by=self.user.user_id, created_at=now())
        self.session.add(item)
        self.session.commit()
        return self.file_dict(item)

    def download(self, resource_id: str) -> tuple[str, str, str]:
        item = self._managed_resource(resource_id, "resources:read")
        if self.user.role == "student" and item.status not in {"PUBLISHED", "FROZEN"}:
            raise ApiError("RESOURCE.NOT_FOUND", "资源不存在或不可访问", 404)
        version = self.repo.latest_version(resource_id)
        if not version:
            raise ApiError("RESOURCE.VERSION_REQUIRED", "资源尚无文件版本", 409)
        file_object = self.session.get(FileObject, version.file_id)
        if not file_object or file_object.storage_provider != "local":
            raise ApiError("RESOURCE.FILE_STORAGE_UNAVAILABLE", "资源文件当前不能由本节点下载", 503)
        path = Path(file_object.object_key).resolve()
        root = upload_root()
        if not path.is_file() or root not in path.parents:
            raise ApiError("RESOURCE.FILE_NOT_AVAILABLE", "资源文件不存在或已移出受控存储目录", 404)
        return str(path), file_object.original_name, file_object.mime_type

    def readiness(self, course_id: str) -> dict:
        self._course(course_id)
        lessons = self.repo.lessons(course_id)
        kinds = {row.lesson_id: row.lesson_kind for row in lessons}
        audit = self.audit(course_id, persist=False)

        def count(requirement: str, kind: str) -> int:
            return sum(check["passed"] for check in audit["checks"] if check["requirement"] == requirement and kinds.get(check["lesson_id"]) == kind)

        question_total = sum(len(items) for items in self.repo.question_evidence(course_id).values())
        theory_total = sum(kind == "THEORY" for kind in kinds.values())
        lab_total = sum(kind == "LAB" for kind in kinds.values())
        lesson_total = len(lessons)
        return {
            "course_id": course_id,
            "theory_lessons": theory_total,
            "lab_lessons": lab_total,
            "ppt": {"ready": count("PPT", "THEORY"), "required": theory_total},
            "theory_video": {"ready": count("VIDEO", "THEORY"), "required": theory_total},
            "lab_file": {"ready": count("LAB_FILE", "LAB"), "required": lab_total},
            "lab_video": {"ready": count("VIDEO", "LAB"), "required": lab_total},
            "question_lessons": {"ready": sum(check["passed"] for check in audit["checks"] if check["requirement"] == "QUESTION_BANK"), "required": lesson_total},
            "published_questions": {"ready": question_total, "required": lesson_total * len(QUESTION_TYPES)},
            "blocking": audit["blocking"],
        }

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
        if data.lesson_id and not self.session.scalar(select(CourseLesson).where(CourseLesson.course_id == data.course_id, CourseLesson.lesson_id == data.lesson_id)):
            raise ApiError("RESOURCE.LESSON_NOT_FOUND", "课时标识不属于该课程资源目录", 422)
        stamp = now()
        item = Resource(resource_id=str(uuid4()), **data.model_dump(), status="DRAFT", created_by=self.user.user_id, created_at=stamp, updated_at=stamp)
        self.repo.add(item)
        enqueue_event(self.session, event_type="resource.created", aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-created:{item.resource_id}", payload={"course_id": item.course_id, "lesson_id": item.lesson_id, "resource_type": item.resource_type, "actor_role": self.user.role})
        self.session.commit()
        return self.resource_dict(item)

    def create_version(self, resource_id: str, data: VersionCreate) -> dict:
        item = self._managed_resource(resource_id, "resources:write")
        if item.status == "FROZEN":
            raise ApiError("RESOURCE.VERSION_FROZEN", "冻结资源不可覆盖或新增版本", 409)
        file_object = self.session.get(FileObject, data.file_id)
        if not file_object or file_object.sha256 != data.sha256:
            raise ApiError("RESOURCE.FILE_SHA256_MISMATCH", "文件不存在或 SHA256（文件校验值）不匹配", 422)
        if file_object.bucket != "course-resources":
            raise ApiError("RESOURCE.FILE_SCOPE_MISMATCH", "文件对象不属于课程资源受控存储", 422)
        allowed_mime = {
            "PPT": {"application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"},
            "VIDEO": {"video/mp4", "video/webm", "video/quicktime"},
            "LAB_FILE": {"application/zip", "application/x-tar", "application/gzip"},
        }
        if item.resource_type not in allowed_mime or file_object.mime_type not in allowed_mime[item.resource_type]:
            raise ApiError("RESOURCE.FILE_TYPE_MISMATCH", "上传文件类型与资源类型不匹配", 422, {"resource_type": item.resource_type, "mime_type": file_object.mime_type})
        latest = self.repo.latest_version(resource_id)
        version = ResourceVersion(resource_version_id=str(uuid4()), resource_id=resource_id, version_no=(latest.version_no + 1 if latest else 1), file_id=data.file_id, status="DRAFT", sha256=data.sha256, created_by=self.user.user_id, created_at=now(), reviewed_by=None, reviewed_at=None, published_at=None)
        self.repo.add(version)
        self.session.flush()
        if item.resource_type == "VIDEO":
            if file_object.storage_provider != "local":
                raise ApiError("RESOURCE.VIDEO_PROBE_PENDING", "对象存储视频须由媒体解析任务写入真实时长后再建版本", 409)
            duration, width, height = probe_local_video(file_object.object_key)
            self.repo.add(VideoAsset(video_asset_id=str(uuid4()), resource_version_id=version.resource_version_id, duration_seconds=duration, width=width, height=height, probed_at=now()))
        elif item.resource_type == "PPT":
            self.repo.add(PptAsset(ppt_asset_id=str(uuid4()), resource_version_id=version.resource_version_id, knowledge_complete=False, layout_overflow_passed=False, animation_occlusion_passed=False, copyright_noted=False, checked_by=None, checked_at=None))
        elif item.resource_type == "LAB_FILE":
            file_count = archive_file_count(file_object.object_key, file_object.mime_type)
            if data.lab_file_count is not None and data.lab_file_count != file_count:
                raise ApiError("RESOURCE.LAB_FILE_COUNT_MISMATCH", "填写的文件数量与真实压缩包不一致", 422, {"actual_file_count": file_count})
            pack = LabFilePack(lab_file_pack_id=str(uuid4()), resource_version_id=version.resource_version_id, file_count=file_count, total_size_bytes=file_object.size_bytes)
            self.repo.add(pack)
            lesson = self.session.scalar(select(LessonResource).where(LessonResource.course_id == item.course_id, LessonResource.lesson_id == item.lesson_id))
            if not lesson and item.lesson_id:
                authority = next((row for row in self.repo.lessons(item.course_id) if row.lesson_id == item.lesson_id), None)
                if authority:
                    lesson = LessonResource(
                        lesson_resource_id=str(uuid4()),
                        course_id=authority.course_id,
                        lesson_id=authority.lesson_id,
                        purpose=None,
                        environment=None,
                        principle=None,
                        steps_summary=None,
                        core_experiment=None,
                    )
                    self.repo.add(lesson)
            if lesson:
                lesson.linked_file_pack_id = pack.lab_file_pack_id
        item.status, item.updated_at = "DRAFT", now()
        enqueue_event(self.session, event_type="resource.version.created", aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-version:{version.resource_version_id}", payload={"course_id": item.course_id, "resource_version_id": version.resource_version_id, "version_no": version.version_no, "sha256": version.sha256, "actor_role": self.user.role})
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
        enqueue_event(self.session, event_type=event_type, aggregate_type="resource", aggregate_id=item.resource_id, actor_user_id=self.user.user_id, idempotency_key=f"{event_type}:{latest.resource_version_id}", payload={"course_id": item.course_id, "resource_version_id": latest.resource_version_id, "actor_role": self.user.role, "comment": comment})
        self.session.commit()
        return self.resource_dict(item)

    def lessons(self, course_id: str, kind: str | None = None) -> dict:
        self._course(course_id)
        rows = self.repo.lessons(course_id, kind)
        return {"items": [self.lesson_dict(row) for row in rows], "page": 1, "page_size": len(rows), "total": len(rows)}

    def question_template(self, course_id: str) -> bytes:
        self._course(course_id, "resources:write")
        return template_bytes(self._question_catalog(course_id))

    def list_questions(self, course_id: str) -> dict:
        self._course(course_id)
        rows = self.repo.list_questions(course_id, published_only=self.user.role == "student")
        items = []
        for question, lesson_id, explanation in rows:
            options = [self.option_dict(option) for option in self.repo.question_options(question.question_id)]
            item = self.question_dict(question, lesson_id, explanation, options=options)
            if self.user.role == "student":
                item.pop("answer", None)
                item.pop("explanation", None)
                for option in item["options"]:
                    option.pop("is_correct", None)
            items.append(item)
        return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}

    def import_questions(self, course_id: str, data: bytes, filename: str, idempotency_key: str) -> dict:
        self._course(course_id, "resources:write")
        if not idempotency_key:
            raise ApiError("REQUEST.IDEMPOTENCY_REQUIRED", "题库导入必须提供 Idempotency-Key", 400)
        if not filename.lower().endswith(".xlsx"):
            raise ApiError("QUESTION_IMPORT.INVALID_FILE_TYPE", "题库导入只接受 XLSX（电子表格）文件", 422)
        if not data:
            raise ApiError("QUESTION_IMPORT.FILE_EMPTY", "题库导入文件不能为空", 422)
        if len(data) > MAX_XLSX_UPLOAD_BYTES:
            raise ApiError("QUESTION_IMPORT.FILE_TOO_LARGE", "题库导入文件不能超过 10 MB", 413)

        request_sha256 = sha256(data).hexdigest()
        previous = self.repo.question_import_job(course_id, idempotency_key)
        if previous:
            if previous.request_sha256 != request_sha256:
                raise ApiError(
                    "REQUEST.IDEMPOTENCY_CONFLICT",
                    "同一 Idempotency-Key 已用于不同的题库文件",
                    409,
                    {"import_job_id": previous.import_job_id},
                )
            return self.import_job_dict(previous)

        lessons = self._question_catalog(course_id)
        try:
            parsed_rows, total_rows = parse_question_workbook(data, lessons)
        except InvalidQuestionWorkbook as exc:
            raise ApiError(exc.code, exc.message, 422) from exc

        bank = self._ensure_question_bank(course_id)
        bank = self.repo.lock_question_bank(course_id) or bank
        locked_previous = self.repo.question_import_job(course_id, idempotency_key, lock=True)
        if locked_previous:
            if locked_previous.request_sha256 != request_sha256:
                raise ApiError(
                    "REQUEST.IDEMPOTENCY_CONFLICT",
                    "同一 Idempotency-Key 已用于不同的题库文件",
                    409,
                    {"import_job_id": locked_previous.import_job_id},
                )
            return self.import_job_dict(locked_previous)

        existing_slots = self.repo.existing_question_slots(course_id, lock=True)
        for row in parsed_rows:
            normalized = row.get("normalized_data")
            if normalized and (normalized["lesson_id"], normalized["question_type"]) in existing_slots:
                row["errors"].append(
                    {
                        "field": "题型*",
                        "code": "QUESTION_IMPORT.SLOT_CONFLICT",
                        "message": "该课时的此题型已存在，不能重复导入",
                    }
                )
                row["status"] = "ERROR"

        validation_failed = any(row["errors"] for row in parsed_rows)
        stamp = now()
        job = QuestionImportJob(
            import_job_id=str(uuid4()),
            course_id=course_id,
            question_bank_id=bank.question_bank_id,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            original_filename=filename[:255],
            status="VALIDATION_FAILED" if validation_failed else "COMPLETED",
            total_rows=total_rows,
            success_count=0 if validation_failed else total_rows,
            failure_count=(
                sum(1 for row in parsed_rows if row["row_number"] > 0 and row["errors"])
                or (1 if validation_failed else 0)
            ),
            created_by=self.user.user_id,
            created_at=stamp,
            completed_at=stamp,
        )
        self.repo.add(job)
        self.session.flush()

        for parsed in parsed_rows:
            question = None
            normalized = parsed.get("normalized_data")
            if not validation_failed and normalized:
                question = Question(
                    question_id=str(uuid4()),
                    question_bank_id=bank.question_bank_id,
                    import_job_id=job.import_job_id,
                    source_row_number=parsed["row_number"],
                    question_type=normalized["question_type"],
                    stem=normalized["stem"],
                    answer_json=normalized["answer"],
                    status="PENDING_REVIEW",
                    created_by=self.user.user_id,
                    created_at=stamp,
                    submitted_at=stamp,
                    reviewed_by=None,
                    reviewed_at=None,
                )
                self.repo.add(question)
                self.repo.add(QuestionExplanation(question_id=question.question_id, explanation=normalized["explanation"]))
                self.repo.add(
                    QuestionLessonMap(
                        question_lesson_map_id=str(uuid4()),
                        question_id=question.question_id,
                        lesson_id=normalized["lesson_id"],
                    )
                )
                for option in normalized["options"]:
                    self.repo.add(
                        QuestionOption(
                            question_option_id=str(uuid4()),
                            question_id=question.question_id,
                            option_key=option["key"],
                            option_text=option["text"],
                            is_correct=option["is_correct"],
                        )
                    )
                enqueue_event(
                    self.session,
                    event_type="question.created",
                    aggregate_type="question",
                    aggregate_id=question.question_id,
                    actor_user_id=self.user.user_id,
                    idempotency_key=f"question-imported:{job.import_job_id}:{parsed['row_number']}",
                    payload={
                        "course_id": course_id,
                        "lesson_id": normalized["lesson_id"],
                        "question_type": normalized["question_type"],
                        "import_job_id": job.import_job_id,
                        "source_row_number": parsed["row_number"],
                        "actor_role": self.user.role,
                    },
                )
            self.repo.add(
                QuestionImportRow(
                    import_row_id=str(uuid4()),
                    import_job_id=job.import_job_id,
                    row_number=parsed["row_number"],
                    status=("ERROR" if parsed["errors"] else ("VALID" if validation_failed else "IMPORTED")),
                    raw_data_json=parsed["raw_data"],
                    normalized_data_json=normalized,
                    errors_json=parsed["errors"],
                    question_id=question.question_id if question else None,
                    created_at=stamp,
                )
            )

        enqueue_event(
            self.session,
            event_type="question.import.validation_failed" if validation_failed else "question.import.completed",
            aggregate_type="question_import_job",
            aggregate_id=job.import_job_id,
            actor_user_id=self.user.user_id,
            idempotency_key=f"question-import:{job.import_job_id}",
            payload={
                "course_id": course_id,
                "import_job_id": job.import_job_id,
                "status": job.status,
                "total_rows": job.total_rows,
                "success_count": job.success_count,
                "failure_count": job.failure_count,
                "actor_role": self.user.role,
            },
        )
        self.session.commit()
        return self.import_job_dict(job)

    def get_question_import_job(self, import_job_id: str) -> dict:
        job = self.repo.get_question_import_job(import_job_id)
        if not job:
            raise ApiError("QUESTION_IMPORT.NOT_FOUND", "题库导入任务不存在", 404)
        self._course(job.course_id, "resources:write")
        return self.import_job_dict(job)

    def question_import_errors_xlsx(self, import_job_id: str) -> bytes:
        job = self.repo.get_question_import_job(import_job_id)
        if not job:
            raise ApiError("QUESTION_IMPORT.NOT_FOUND", "题库导入任务不存在", 404)
        self._course(job.course_id, "resources:write")
        rows = [self.import_row_dict(row) for row in self.repo.question_import_rows(import_job_id, "ERROR")]
        return error_rows_bytes(rows)

    def review_queue(self, course_id: str, page: int, page_size: int) -> dict:
        self._course(course_id, "resources:review")
        rows, total = self.repo.review_queue(course_id, offset=(page - 1) * page_size, limit=page_size)
        items = []
        for question, lesson_id, explanation, lesson_code, lesson_title in rows:
            options = [self.option_dict(option) for option in self.repo.question_options(question.question_id)]
            item = self.question_dict(question, lesson_id, explanation, options=options)
            item.update(
                {
                    "course_id": course_id,
                    "lesson_code": lesson_code,
                    "lesson_title": lesson_title,
                    "can_review": question.created_by != self.user.user_id,
                }
            )
            items.append(item)
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def create_question(self, data: QuestionCreate) -> dict:
        self._course(data.course_id, "resources:write")
        if not any(row.lesson_id == data.lesson_id for row in self.repo.lessons(data.course_id)):
            raise ApiError("QUESTION.LESSON_NOT_FOUND", "题目必须关联课程资源目录中的课时", 422)
        bank = self._ensure_question_bank(data.course_id)
        bank = self.repo.lock_question_bank(data.course_id) or bank
        if (data.lesson_id, data.question_type) in self.repo.existing_question_slots(data.course_id, lock=True):
            raise ApiError("QUESTION.SLOT_CONFLICT", "该课时的此题型已存在，不能重复创建", 409)
        question = Question(question_id=str(uuid4()), question_bank_id=bank.question_bank_id, question_type=data.question_type, stem=data.stem, answer_json=data.answer, status="DRAFT", created_by=self.user.user_id, created_at=now(), reviewed_by=None, reviewed_at=None)
        self.repo.add(question)
        self.repo.add(QuestionExplanation(question_id=question.question_id, explanation=data.explanation))
        self.repo.add(QuestionLessonMap(question_lesson_map_id=str(uuid4()), question_id=question.question_id, lesson_id=data.lesson_id))
        for index, option in enumerate(data.options):
            values = option.model_dump()
            self.repo.add(QuestionOption(question_option_id=str(uuid4()), question_id=question.question_id, option_key=str(values.get("key", index + 1)), option_text=str(values.get("text", "")), is_correct=bool(values.get("is_correct", False))))
        enqueue_event(self.session, event_type="question.created", aggregate_type="question", aggregate_id=question.question_id, actor_user_id=self.user.user_id, idempotency_key=f"question-created:{question.question_id}", payload={"course_id": data.course_id, "lesson_id": data.lesson_id, "question_type": data.question_type, "actor_role": self.user.role})
        self.session.commit()
        return self.question_dict(question, data.lesson_id, data.explanation)

    def patch_question(self, question_id: str, data: QuestionPatch) -> dict:
        question = self.session.get(Question, question_id)
        if not question or question.status not in {"DRAFT", "REJECTED"}:
            raise ApiError("QUESTION.NOT_EDITABLE", "题目不存在或已审核，不能覆盖修改", 409)
        bank = self.session.get(QuestionBank, question.question_bank_id)
        self._course(bank.course_id, "resources:write")
        question = self.repo.lock_question(question_id)
        if not question or question.status not in {"DRAFT", "REJECTED"}:
            raise ApiError("QUESTION.NOT_EDITABLE", "题目不存在或已审核，不能覆盖修改", 409)
        if data.stem is not None: question.stem = data.stem
        if data.answer is not None:
            if not data.answer: raise ApiError("QUESTION.ANSWER_REQUIRED", "答案不能为空", 422)
            question.answer_json = data.answer
        if data.explanation is not None:
            self.session.get(QuestionExplanation, question_id).explanation = data.explanation
        if question.status == "REJECTED":
            question.status = "PENDING_REVIEW"
            question.reviewed_by = None
            question.reviewed_at = None
            question.submitted_at = now()
        enqueue_event(self.session, event_type="question.updated", aggregate_type="question", aggregate_id=question.question_id, actor_user_id=self.user.user_id, idempotency_key=f"question-updated:{question.question_id}:{uuid4()}", payload={"course_id": bank.course_id, "actor_role": self.user.role})
        self.session.commit()
        return {"question_id": question.question_id, "status": question.status}

    def review_question(self, question_id: str, data=None) -> dict:
        question = self.session.get(Question, question_id)
        if not question: raise ApiError("QUESTION.NOT_FOUND", "题目不存在", 404)
        bank = self.session.get(QuestionBank, question.question_bank_id)
        self._course(bank.course_id, "resources:review")
        question = self.repo.lock_question(question_id)
        if not question: raise ApiError("QUESTION.NOT_FOUND", "题目不存在", 404)
        if question.created_by == self.user.user_id: raise ApiError("QUESTION.REVIEWER_MUST_BE_INDEPENDENT", "出题人不能审核自己的题目", 409)
        decision = data.decision if data else "APPROVED"
        comment = data.comment.strip() if data and data.comment else None
        expected_status = "PUBLISHED" if decision == "APPROVED" else "REJECTED"
        if question.status == expected_status:
            return {"question_id": question.question_id, "status": question.status, "reviewed_by": question.reviewed_by, "reviewed_at": question.reviewed_at.isoformat() if question.reviewed_at else None}
        if question.status not in {"DRAFT", "PENDING_REVIEW"}:
            raise ApiError("QUESTION.INVALID_REVIEW_STATE", "当前题目状态不能执行审核", 409, {"status": question.status})
        if decision == "REJECTED" and not comment:
            raise ApiError("QUESTION.REJECTION_COMMENT_REQUIRED", "驳回题目时必须填写原因", 422)
        explanation = self.session.get(QuestionExplanation, question_id)
        mapping = self.session.scalar(select(QuestionLessonMap).where(QuestionLessonMap.question_id == question_id))
        if not question.answer_json or not explanation or not explanation.explanation or not mapping:
            raise ApiError("QUESTION.INCOMPLETE", "答案、解析和课时映射必须完整", 422)
        reviewed_at = now()
        review = QuestionReview(question_review_id=str(uuid4()), question_id=question.question_id, decision=decision, comment=comment, reviewer_id=self.user.user_id, reviewed_at=reviewed_at)
        self.repo.add(review)
        question.status, question.reviewed_by, question.reviewed_at = expected_status, self.user.user_id, reviewed_at
        question.submitted_at = question.submitted_at or reviewed_at
        enqueue_event(
            self.session,
            event_type="question.published" if decision == "APPROVED" else "question.rejected",
            aggregate_type="question",
            aggregate_id=question.question_id,
            actor_user_id=self.user.user_id,
            idempotency_key=f"question-review:{review.question_review_id}",
            payload={"course_id": bank.course_id, "lesson_id": mapping.lesson_id, "decision": decision, "comment": comment, "actor_role": self.user.role},
        )
        self.session.commit()
        return {"question_id": question.question_id, "status": question.status, "reviewed_by": question.reviewed_by, "reviewed_at": reviewed_at.isoformat()}

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
        evidence = self.repo.asset_evidence(course_id)
        question_evidence = self.repo.question_evidence(course_id)
        checks, blockers = [], []
        for lesson in lessons:
            lesson_assets = evidence.get(lesson.lesson_id, {})
            lesson_questions = question_evidence.get(lesson.lesson_id, [])
            question_types = {item["question_type"] for item in lesson_questions}
            questions_pass = question_types == QUESTION_TYPES and len(lesson_questions) == 4
            if lesson.lesson_kind == "THEORY":
                requirements = {"PPT": "PPT", "VIDEO": "讲解视频", "QUESTION_BANK": "四类题型", "REVIEW": "审核发布"}
                passed = {
                    "PPT": bool(lesson_assets.get("PPT")),
                    "VIDEO": bool(lesson_assets.get("VIDEO")),
                    "QUESTION_BANK": questions_pass,
                    "REVIEW": bool(lesson_assets.get("PPT")) and bool(lesson_assets.get("VIDEO")) and questions_pass,
                }
            else:
                requirements = {"INTRO": "介绍四段", "LAB_FILE": "实验文件", "VIDEO": "讲解视频", "QUESTION_BANK": "四类题型"}
                passed = {
                    "INTRO": bool(lesson.purpose and lesson.environment and lesson.principle and lesson.steps_summary),
                    "LAB_FILE": bool(lesson_assets.get("LAB_FILE")),
                    "VIDEO": bool(lesson_assets.get("VIDEO")),
                    "QUESTION_BANK": questions_pass,
                }
            for key, label in requirements.items():
                if key == "QUESTION_BANK":
                    item_evidence = lesson_questions
                elif key == "REVIEW":
                    item_evidence = lesson_assets.get("PPT", []) + lesson_assets.get("VIDEO", []) + lesson_questions
                elif key == "INTRO":
                    item_evidence = [{"lesson_resource_id": lesson.lesson_resource_id}] if passed[key] else []
                else:
                    item_evidence = lesson_assets.get(key, [])
                check = {"lesson_id": lesson.lesson_id, "lesson_code": lesson.lesson_code, "requirement": key, "passed": passed[key], "evidence": item_evidence}
                checks.append(check)
                if not passed[key]: blockers.append(f"{lesson.lesson_code} 缺少{label}")
        result = {"course_id": course_id, "total": len(checks), "pass": sum(x["passed"] for x in checks), "warning": 0, "blocking": len(blockers), "blocking_items": blockers, "checks": checks, "procurement_mapping": self.procurement_mapping(), "checked_at": now().isoformat() + "Z"}
        if persist:
            self.repo.add(ResourceQualityCheck(resource_quality_check_id=str(uuid4()), course_id=course_id, resource_version_id=None, check_type="COURSE_AUDIT", result="PASS" if not blockers else "BLOCKING", details_json=result, checked_by=self.user.user_id, checked_at=now()))
            enqueue_event(self.session, event_type="resource.audit.completed", aggregate_type="course_resource", aggregate_id=course_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-audit:{uuid4()}", payload={"course_id": course_id, "blocking": len(blockers), "pass": result["pass"], "total": result["total"], "actor_role": self.user.role})
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
        enqueue_event(self.session, event_type="resource.delivery.frozen", aggregate_type="course_resource", aggregate_id=course_id, actor_user_id=self.user.user_id, idempotency_key=f"resource-delivery:{course_id}:{row.version_no}", payload={"course_id": course_id, "manifest_id": row.resource_delivery_manifest_id, "version_no": row.version_no, "actor_role": self.user.role})
        self.session.commit()
        return manifest

    def manifest(self, course_id: str, audit: dict | None = None) -> dict:
        self._course(course_id)
        audit = audit or self.latest_audit(course_id)
        latest = self.repo.latest_manifest(course_id)
        lessons = self.repo.lessons(course_id)
        return {"course_id": course_id, "theory_lessons": sum(row.lesson_kind == "THEORY" for row in lessons), "lab_lessons": sum(row.lesson_kind == "LAB" for row in lessons), "audit": audit, "status": latest.status if latest else ("READY" if audit["blocking"] == 0 else "BLOCKED"), "version_no": latest.version_no if latest else None, "generated_at": now().isoformat() + "Z", "content_declaration": "目录结构已建立；只有已上传、校验、审核的真实文件才计入完成。"}

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

    def _ensure_question_bank(self, course_id: str) -> QuestionBank:
        bank = self.repo.question_bank(course_id)
        if bank:
            return bank
        bank = QuestionBank(
            question_bank_id=f"qb_{course_id}" if len(f"qb_{course_id}") <= 36 else str(uuid4()),
            course_id=course_id,
            name="课程统一题库",
            status="DRAFT",
            created_by=self.user.user_id,
            created_at=now(),
        )
        try:
            with self.session.begin_nested():
                self.repo.add(bank)
                self.session.flush()
            return bank
        except IntegrityError:
            existing = self.repo.lock_question_bank(course_id)
            if existing:
                return existing
            raise

    def _question_catalog(self, course_id: str) -> list[ResourceLesson]:
        lessons = self.repo.lessons(course_id)
        theory_count = sum(item.lesson_kind == "THEORY" for item in lessons)
        lab_count = sum(item.lesson_kind == "LAB" for item in lessons)
        if theory_count != 37 or lab_count != 12:
            raise ApiError(
                "QUESTION_IMPORT.CATALOG_INCOMPLETE",
                "当前课程必须先具备完整的 37 个理论课时和 12 个实验课时目录",
                409,
                {
                    "lesson_count": len(lessons),
                    "theory_lesson_count": theory_count,
                    "lab_lesson_count": lab_count,
                },
            )
        return lessons

    def import_job_dict(self, job: QuestionImportJob) -> dict:
        rows = [self.import_row_dict(row) for row in self.repo.question_import_rows(job.import_job_id)]
        error_rows = [
            {"row_number": row["row_number"], **error}
            for row in rows
            for error in row["errors"]
        ]
        return {
            "import_job_id": job.import_job_id,
            "job_id": job.import_job_id,
            "course_id": job.course_id,
            "status": job.status,
            "total_rows": job.total_rows,
            "total_count": job.total_rows,
            "success_count": job.success_count,
            "imported_count": job.success_count,
            "failure_count": job.failure_count,
            "error_count": job.failure_count,
            "review_queue_count": job.success_count if job.status == "COMPLETED" else 0,
            "original_filename": job.original_filename,
            "request_sha256": job.request_sha256,
            "created_by": job.created_by,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "rows": rows,
            "error_rows": error_rows,
        }

    @staticmethod
    def import_row_dict(row: QuestionImportRow) -> dict:
        return {
            "row_number": row.row_number,
            "status": row.status,
            "question_id": row.question_id,
            "raw_data": row.raw_data_json,
            "normalized_data": row.normalized_data_json,
            "errors": row.errors_json or [],
        }

    @staticmethod
    def resource_dict(item: Resource) -> dict:
        return {"resource_id": item.resource_id, "course_id": item.course_id, "lesson_id": item.lesson_id, "name": item.name, "resource_type": item.resource_type, "status": item.status, "created_by": item.created_by, "created_at": item.created_at.isoformat()}

    @staticmethod
    def version_dict(item: ResourceVersion) -> dict:
        return {"resource_version_id": item.resource_version_id, "version_no": item.version_no, "file_id": item.file_id, "status": item.status, "sha256": item.sha256, "created_by": item.created_by, "created_at": item.created_at.isoformat()}

    @staticmethod
    def file_dict(item: FileObject) -> dict:
        return {"file_id": item.file_id, "original_name": item.original_name, "mime_type": item.mime_type, "size_bytes": item.size_bytes, "sha256": item.sha256}

    @staticmethod
    def lesson_dict(item) -> dict:
        return {key: getattr(item, key) for key in ["course_id", "lesson_id", "lesson_kind", "chapter_no", "lesson_code", "title", "purpose", "environment", "principle", "steps_summary", "core_experiment", "linked_file_pack_id", "linked_video_resource_id", "linked_lab_definition_id"]}

    @staticmethod
    def option_dict(item: QuestionOption) -> dict:
        return {"key": item.option_key, "text": item.option_text, "is_correct": item.is_correct}

    @staticmethod
    def question_dict(item, lesson_id: str, explanation: str, *, options: list[dict] | None = None) -> dict:
        return {
            "question_id": item.question_id,
            "question_type": item.question_type,
            "stem": item.stem,
            "answer": item.answer_json,
            "status": item.status,
            "lesson_id": lesson_id,
            "explanation": explanation,
            "options": options or [],
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
            "import_job_id": item.import_job_id,
            "source_row_number": item.source_row_number,
            "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
            "reviewed_by": item.reviewed_by,
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        }

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
