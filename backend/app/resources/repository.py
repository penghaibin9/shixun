from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from .models import LessonResource, PptAsset, Question, QuestionBank, QuestionExplanation, QuestionLessonMap, Resource, ResourceDeliveryManifest, ResourceQualityCheck, ResourceVersion, VideoAsset


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

    def question_coverage(self, course_id: str) -> dict[str, set[str]]:
        rows = self.session.execute(
            select(QuestionLessonMap.lesson_id, Question.question_type)
            .join(Question, Question.question_id == QuestionLessonMap.question_id)
            .join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id)
            .join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id)
            .where(and_(QuestionBank.course_id == course_id,
                        Question.status == "PUBLISHED"))
        ).all()
        coverage: dict[str, set[str]] = {}
        for lesson_id, question_type in rows:
            coverage.setdefault(lesson_id, set()).add(question_type)
        return coverage

    def question_counts(self, course_id: str) -> dict[str, int]:
        rows = self.session.execute(select(QuestionLessonMap.lesson_id, func.count(Question.question_id)).join(Question, Question.question_id == QuestionLessonMap.question_id).join(QuestionBank, QuestionBank.question_bank_id == Question.question_bank_id).join(QuestionExplanation, QuestionExplanation.question_id == Question.question_id).where(QuestionBank.course_id == course_id, Question.status == "PUBLISHED").group_by(QuestionLessonMap.lesson_id)).all()
        return dict(rows)

    def asset_counts(self, course_id: str) -> dict[str, set[str]]:
        rows = self.session.execute(
            select(Resource.lesson_id, Resource.resource_type)
            .join(ResourceVersion, ResourceVersion.resource_id == Resource.resource_id)
            .where(Resource.course_id == course_id, Resource.status.in_(["PUBLISHED", "FROZEN"]), ResourceVersion.status.in_(["PUBLISHED", "FROZEN"]))
        ).all()
        result: dict[str, set[str]] = {}
        for lesson_id, resource_type in rows:
            if lesson_id:
                if resource_type != "PPT":
                    result.setdefault(lesson_id, set()).add(resource_type)
        ppt_rows = self.session.execute(select(Resource.lesson_id).join(ResourceVersion, ResourceVersion.resource_id == Resource.resource_id).join(PptAsset, PptAsset.resource_version_id == ResourceVersion.resource_version_id).where(Resource.course_id == course_id, Resource.status.in_(["PUBLISHED", "FROZEN"]), PptAsset.knowledge_complete.is_(True), PptAsset.layout_overflow_passed.is_(True), PptAsset.animation_occlusion_passed.is_(True), PptAsset.copyright_noted.is_(True))).all()
        for (lesson_id,) in ppt_rows:
            if lesson_id: result.setdefault(lesson_id, set()).add("PPT")
        return result

    def video_durations(self, course_id: str) -> dict[str, int]:
        rows = self.session.execute(select(Resource.lesson_id, VideoAsset.duration_seconds).join(ResourceVersion, ResourceVersion.resource_version_id == VideoAsset.resource_version_id).join(Resource, Resource.resource_id == ResourceVersion.resource_id).where(Resource.course_id == course_id, Resource.status.in_(["PUBLISHED", "FROZEN"]))).all()
        return {lesson_id: duration for lesson_id, duration in rows if lesson_id}

    def latest_audit(self, course_id: str) -> ResourceQualityCheck | None:
        return self.session.scalar(select(ResourceQualityCheck).where(ResourceQualityCheck.course_id == course_id, ResourceQualityCheck.check_type == "COURSE_AUDIT").order_by(ResourceQualityCheck.checked_at.desc()).limit(1))

    def latest_manifest(self, course_id: str) -> ResourceDeliveryManifest | None:
        return self.session.scalar(select(ResourceDeliveryManifest).where(ResourceDeliveryManifest.course_id == course_id).order_by(ResourceDeliveryManifest.version_no.desc()).limit(1))
