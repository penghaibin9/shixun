from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.models import FileObject

from .models import (AnalyticsCourseSummary, AnalyticsLabSummary, AnalyticsSectionSummary, AnalyticsStudentLabSummary,
                     AuditEvent, CourseArchive, CourseArchiveArtifact, GradeEvent, Gradebook, GradebookItem, GradingPolicy,
                     GradingPolicyItem, StudentCourseScore, StudentRiskFlag)


class GradingRepository:
    def __init__(self, session: Session): self.session = session
    def add(self, entity): self.session.add(entity); return entity
    def policy(self, course_id: str) -> GradingPolicy | None:
        return self.session.scalar(select(GradingPolicy).where(GradingPolicy.course_id == course_id).order_by(GradingPolicy.version_no.desc()).limit(1))
    def policy_version(self, course_id: str, version_no: int) -> GradingPolicy | None:
        return self.session.scalar(select(GradingPolicy).where(GradingPolicy.course_id == course_id, GradingPolicy.version_no == version_no))
    def policy_items(self, policy_id: str) -> list[GradingPolicyItem]:
        return list(self.session.scalars(select(GradingPolicyItem).where(GradingPolicyItem.grading_policy_id == policy_id)))
    def grade_events(self, course_id: str, class_id: str, student_id: str | None = None) -> list[GradeEvent]:
        query = select(GradeEvent).where(GradeEvent.course_id == course_id, GradeEvent.class_id == class_id, GradeEvent.status == "CONSUMED")
        if student_id: query = query.where(GradeEvent.student_id == student_id)
        return list(self.session.scalars(query.order_by(GradeEvent.occurred_at)))
    def gradebook(self, course_id: str, class_id: str, *, lock: bool = False) -> Gradebook | None:
        query = select(Gradebook).where(Gradebook.course_id == course_id, Gradebook.class_id == class_id)
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query.order_by(Gradebook.policy_version.desc()).limit(1))
    def scores(self, gradebook_id: str) -> list[StudentCourseScore]:
        return list(self.session.scalars(select(StudentCourseScore).where(StudentCourseScore.gradebook_id == gradebook_id).order_by(StudentCourseScore.total_score.desc())))
    def items(self, gradebook_id: str, student_id: str | None = None) -> list[GradebookItem]:
        query = select(GradebookItem).where(GradebookItem.gradebook_id == gradebook_id)
        if student_id: query = query.where(GradebookItem.student_id == student_id)
        return list(self.session.scalars(query.order_by(GradebookItem.student_id, GradebookItem.component)))
    def audit_events(self, *, course_id=None, action=None, result=None) -> list[AuditEvent]:
        query = select(AuditEvent)
        if course_id: query = query.where(AuditEvent.course_id == course_id)
        if action: query = query.where(AuditEvent.action == action)
        if result: query = query.where(AuditEvent.result == result)
        return list(self.session.scalars(query.order_by(AuditEvent.occurred_at.desc()).limit(1000)))
    def archive(self, course_id: str, class_id: str, *, lock: bool = False) -> CourseArchive | None:
        query = select(CourseArchive).where(CourseArchive.course_id == course_id, CourseArchive.class_id == class_id)
        if lock:
            query = query.with_for_update()
        return self.session.scalar(query)
    def archive_artifact(self, archive_id: str, artifact_type: str) -> CourseArchiveArtifact | None:
        return self.session.scalar(select(CourseArchiveArtifact).where(CourseArchiveArtifact.course_archive_id == archive_id, CourseArchiveArtifact.artifact_type == artifact_type))
    def file_object(self, file_id: str) -> FileObject | None:
        return self.session.get(FileObject, file_id)
    def course_summary(self, gradebook_id: str): return self.session.scalar(select(AnalyticsCourseSummary).where(AnalyticsCourseSummary.gradebook_id == gradebook_id))
    def section_summary(self, gradebook_id: str, lesson_id: str): return self.session.scalar(select(AnalyticsSectionSummary).where(AnalyticsSectionSummary.gradebook_id == gradebook_id, AnalyticsSectionSummary.lesson_id == lesson_id))
    def section_summaries(self, gradebook_id: str): return list(self.session.scalars(select(AnalyticsSectionSummary).where(AnalyticsSectionSummary.gradebook_id == gradebook_id).order_by(AnalyticsSectionSummary.lesson_id)))
    def student_lab_summaries(self, gradebook_id: str): return list(self.session.scalars(select(AnalyticsStudentLabSummary).where(AnalyticsStudentLabSummary.gradebook_id == gradebook_id)))
    def lab_summaries(self, gradebook_id: str): return list(self.session.scalars(select(AnalyticsLabSummary).where(AnalyticsLabSummary.gradebook_id == gradebook_id)))
    def risks(self, course_id: str, class_id: str, student_id: str | None = None):
        query = select(StudentRiskFlag).where(StudentRiskFlag.course_id == course_id, StudentRiskFlag.class_id == class_id, StudentRiskFlag.status == "OPEN")
        if student_id: query = query.where(StudentRiskFlag.student_id == student_id)
        return list(self.session.scalars(query.order_by(StudentRiskFlag.created_at.desc())))
