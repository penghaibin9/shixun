from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.common.models import FileObject

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
    Resource,
    ResourceDeliveryManifest,
    ResourceQualityCheck,
    ResourceReview,
    ResourceVersion,
    VideoAsset,
)


class ResourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_resources(self, *, course_id: str, status: str | None, name: str | None, resource_type: str | None) -> list[Resource]:
        query: Select = select(Resource).where(Resource.course_id == course_id)
        if status:
            query = query.where(Resource.status == status)
        if name:
            query = query.where(Resource.name.contains(name))
        if resource_type:
            query = query.where(Resource.resource_type == resource_type)
        return list(self.session.scalars(query.order_by(Resource.created_at.desc())))

    def get_resource(self, resource_id: str) -> Resource | None:
        return self.session.get(Resource, resource_id)

    def add(self, entity):
        self.session.add(entity)
        return entity

    def latest_version(self, resource_id: str) -> ResourceVersion | None:
        return self.session.scalar(select(ResourceVersion).where(ResourceVersion.resource_id == resource_id).order_by(ResourceVersion.version_no.desc()).limit(1))

    def lessons(self, course_id: str, kind: str | None = None) -> list[LessonResource]:
        query = select(LessonResource).where(LessonResource.course_id == course_id)
        if kind:
            query = query.where(LessonResource.lesson_kind == kind)
        return list(self.session.scalars(query.order_by(LessonResource.lesson_kind, LessonResource.chapter_no, LessonResource.lesson_code)))

    def question_bank(self, course_id: str) -> QuestionBank | None:
        return self.session.scalar(select(QuestionBank).where(QuestionBank.course_id == course_id).limit(1))

    def lock_question_bank(self, course_id: str) -> QuestionBank | None:
        return self.session.scalar(
            select(QuestionBank)
            .where(QuestionBank.course_id == course_id)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_question(self, question_id: str) -> Question | None:
        return self.session.scalar(
            select(Question)
            .where(Question.question_id == question_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def list_questions(self, course_id: str, *, published_only: bool = False):
        query = (
            select(Question, QuestionLessonMap.lesson_id, QuestionExplanation.explanation)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .join(QuestionLessonMap, QuestionLessonMap.question_id == Question.question_id)
            .join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id)
            .where(QuestionBank.course_id == course_id)
        )
        if published_only:
            query = query.where(Question.status == "PUBLISHED")
        return self.session.execute(query.order_by(Question.created_at, Question.question_id)).all()

    def question_options(self, question_id: str) -> list[QuestionOption]:
        return list(self.session.scalars(select(QuestionOption).where(QuestionOption.question_id == question_id).order_by(QuestionOption.option_key)))

    def existing_question_slots(self, course_id: str, *, lock: bool = False) -> set[tuple[str, str]]:
        query = (
            select(QuestionLessonMap.lesson_id, Question.question_type)
            .join(Question, Question.question_id == QuestionLessonMap.question_id)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .where(QuestionBank.course_id == course_id)
        )
        if lock:
            query = query.with_for_update()
        rows = self.session.execute(query).all()
        return {(lesson_id, question_type) for lesson_id, question_type in rows}

    def question_import_job(self, course_id: str, idempotency_key: str, *, lock: bool = False) -> QuestionImportJob | None:
        query = select(QuestionImportJob).where(
            QuestionImportJob.course_id == course_id,
            QuestionImportJob.idempotency_key == idempotency_key,
        )
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)

    def get_question_import_job(self, import_job_id: str) -> QuestionImportJob | None:
        return self.session.get(QuestionImportJob, import_job_id)

    def question_import_rows(self, import_job_id: str, status: str | None = None) -> list[QuestionImportRow]:
        query = select(QuestionImportRow).where(QuestionImportRow.import_job_id == import_job_id)
        if status:
            query = query.where(QuestionImportRow.status == status)
        return list(self.session.scalars(query.order_by(QuestionImportRow.row_number)))

    def review_queue(self, course_id: str, *, offset: int, limit: int):
        base = (
            select(Question, QuestionLessonMap.lesson_id, QuestionExplanation.explanation, LessonResource.lesson_code, LessonResource.title)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .join(QuestionLessonMap, QuestionLessonMap.question_id == Question.question_id)
            .join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id)
            .join(
                LessonResource,
                and_(LessonResource.course_id == QuestionBank.course_id, LessonResource.lesson_id == QuestionLessonMap.lesson_id),
            )
            .where(QuestionBank.course_id == course_id, Question.status == "PENDING_REVIEW")
        )
        total = self.session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
        rows = self.session.execute(base.order_by(Question.created_at, Question.source_row_number, Question.question_id).offset(offset).limit(limit)).all()
        return rows, total

    def question_coverage(self, course_id: str) -> dict[str, set[str]]:
        return {lesson_id: {item["question_type"] for item in items} for lesson_id, items in self.question_evidence(course_id).items()}

    def question_counts(self, course_id: str) -> dict[str, int]:
        return {lesson_id: len(items) for lesson_id, items in self.question_evidence(course_id).items()}

    def question_evidence(self, course_id: str) -> dict[str, list[dict]]:
        rows = self.session.execute(
            select(QuestionLessonMap.lesson_id, Question, QuestionExplanation.explanation)
            .join(Question, Question.question_id == QuestionLessonMap.question_id)
            .join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .where(and_(QuestionBank.course_id == course_id, Question.status == "PUBLISHED"))
        ).all()
        result: dict[str, list[dict]] = {}
        for lesson_id, question, explanation in rows:
            if not question.answer_json or not explanation or not question.reviewed_by or question.reviewed_by == question.created_by or not question.reviewed_at:
                continue
            result.setdefault(lesson_id, []).append({"question_id": question.question_id, "question_type": question.question_type, "reviewed_by": question.reviewed_by})
        return result

    def asset_counts(self, course_id: str) -> dict[str, set[str]]:
        return {lesson_id: set(types) for lesson_id, types in self.asset_evidence(course_id).items()}

    def asset_evidence(self, course_id: str) -> dict[str, dict[str, list[dict]]]:
        result: dict[str, dict[str, list[dict]]] = {}

        def collect(rows, resource_type: str, extra_key: str | None = None) -> None:
            for row in rows:
                lesson_id, resource_id, version_id, file_id, review_id, reviewer_id, extra = row
                evidence = {"resource_id": resource_id, "resource_version_id": version_id, "file_id": file_id, "resource_review_id": review_id, "reviewed_by": reviewer_id}
                if extra_key:
                    evidence[extra_key] = extra
                result.setdefault(lesson_id, {}).setdefault(resource_type, []).append(evidence)

        base_filters = (Resource.course_id == course_id, Resource.status.in_(["PUBLISHED", "FROZEN"]), ResourceVersion.status.in_(["PUBLISHED", "FROZEN"]), ResourceReview.decision == "APPROVED", ResourceReview.reviewer_id != ResourceVersion.created_by)
        ppt_rows = self.session.execute(
            select(Resource.lesson_id, Resource.resource_id, ResourceVersion.resource_version_id, FileObject.file_id, ResourceReview.resource_review_id, ResourceReview.reviewer_id, PptAsset.ppt_asset_id)
            .join(ResourceVersion, ResourceVersion.resource_id == Resource.resource_id).join(FileObject, FileObject.file_id == ResourceVersion.file_id)
            .join(PptAsset, PptAsset.resource_version_id == ResourceVersion.resource_version_id).join(ResourceReview, ResourceReview.resource_version_id == ResourceVersion.resource_version_id)
            .where(*base_filters, Resource.resource_type == "PPT", PptAsset.knowledge_complete.is_(True), PptAsset.layout_overflow_passed.is_(True), PptAsset.animation_occlusion_passed.is_(True), PptAsset.copyright_noted.is_(True), PptAsset.checked_at.is_not(None)).distinct()
        ).all()
        collect(ppt_rows, "PPT", "ppt_asset_id")
        video_rows = self.session.execute(
            select(Resource.lesson_id, Resource.resource_id, ResourceVersion.resource_version_id, FileObject.file_id, ResourceReview.resource_review_id, ResourceReview.reviewer_id, VideoAsset.duration_seconds)
            .join(ResourceVersion, ResourceVersion.resource_id == Resource.resource_id).join(FileObject, FileObject.file_id == ResourceVersion.file_id)
            .join(VideoAsset, VideoAsset.resource_version_id == ResourceVersion.resource_version_id).join(ResourceReview, ResourceReview.resource_version_id == ResourceVersion.resource_version_id)
            .where(*base_filters, Resource.resource_type == "VIDEO", VideoAsset.duration_seconds > 0).distinct()
        ).all()
        collect(video_rows, "VIDEO", "duration_seconds")
        lab_rows = self.session.execute(
            select(Resource.lesson_id, Resource.resource_id, ResourceVersion.resource_version_id, FileObject.file_id, ResourceReview.resource_review_id, ResourceReview.reviewer_id, LabFilePack.file_count)
            .join(ResourceVersion, ResourceVersion.resource_id == Resource.resource_id).join(FileObject, FileObject.file_id == ResourceVersion.file_id)
            .join(LabFilePack, LabFilePack.resource_version_id == ResourceVersion.resource_version_id).join(ResourceReview, ResourceReview.resource_version_id == ResourceVersion.resource_version_id)
            .where(*base_filters, Resource.resource_type == "LAB_FILE", LabFilePack.file_count > 0).distinct()
        ).all()
        collect(lab_rows, "LAB_FILE", "file_count")
        return result

    def video_durations(self, course_id: str) -> dict[str, int]:
        rows = self.session.execute(select(Resource.lesson_id, VideoAsset.duration_seconds).join(ResourceVersion, ResourceVersion.resource_version_id == VideoAsset.resource_version_id).join(Resource, Resource.resource_id == ResourceVersion.resource_id).where(Resource.course_id == course_id, Resource.status.in_(["PUBLISHED", "FROZEN"]))).all()
        return {lesson_id: duration for lesson_id, duration in rows if lesson_id}

    def latest_audit(self, course_id: str) -> ResourceQualityCheck | None:
        return self.session.scalar(select(ResourceQualityCheck).where(ResourceQualityCheck.course_id == course_id, ResourceQualityCheck.check_type == "COURSE_AUDIT").order_by(ResourceQualityCheck.checked_at.desc()).limit(1))

    def latest_manifest(self, course_id: str) -> ResourceDeliveryManifest | None:
        return self.session.scalar(select(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == course_id).order_by(ResourceDeliveryManifest.version_no.desc()).limit(1))
