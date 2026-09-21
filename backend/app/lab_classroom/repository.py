from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m


class ClassroomRepository:
    def __init__(self, session: Session): self.session = session
    def add(self, entity): self.session.add(entity); self.session.flush(); return entity
    def get(self, model, object_id): return self.session.get(model, object_id)
    def projection(self, release_id: str, student_id: str):
        return self.session.scalar(select(m.RuntimeProjection).where(m.RuntimeProjection.lab_release_id == release_id, m.RuntimeProjection.student_id == student_id))
    def latest_runtime_event(self, release_id: str, student_id: str):
        return self.session.scalar(select(m.ClassroomRuntimeEvent).where(m.ClassroomRuntimeEvent.lab_release_id == release_id, m.ClassroomRuntimeEvent.student_id == student_id).order_by(m.ClassroomRuntimeEvent.occurred_at.desc(), m.ClassroomRuntimeEvent.event_sequence.desc()).limit(1))
    def projections(self, release_id: str):
        return list(self.session.scalars(select(m.RuntimeProjection).where(m.RuntimeProjection.lab_release_id == release_id)))
    def consumed(self, event_id: str): return self.session.get(m.ConsumedRuntimeEvent, event_id)
    def distribution_by_key(self, class_id: str, key: str):
        return self.session.scalar(select(m.TeachingLogDistributionTask).where(m.TeachingLogDistributionTask.class_id == class_id, m.TeachingLogDistributionTask.idempotency_key == key))
    def distributions(self, class_ids: frozenset[str]):
        return list(self.session.scalars(select(m.TeachingLogDistributionTask).where(m.TeachingLogDistributionTask.class_id.in_(class_ids)).order_by(m.TeachingLogDistributionTask.created_at.desc())))
    def distribution_items(self, distribution_id: str):
        return list(self.session.scalars(select(m.TeachingLogDistributionItem).where(m.TeachingLogDistributionItem.distribution_id == distribution_id)))
    def student_assignments(self, student_id: str):
        return list(self.session.scalars(select(m.StudentLogAssignment).where(m.StudentLogAssignment.student_id == student_id).order_by(m.StudentLogAssignment.assigned_at.desc())))
    def assignment(self, assignment_id: str): return self.session.get(m.StudentLogAssignment, assignment_id)
    def student_experiment_counts(self, student_id: str):
        rows = list(self.session.scalars(select(m.RuntimeProjection).where(m.RuntimeProjection.student_id == student_id)))
        return {"total": len(rows), "started": sum(x.status not in {"NOT_STARTED", "AVAILABLE"} for x in rows), "completed": sum(x.status == "SUBMITTED" for x in rows), "running": sum(x.status == "RUNNING" for x in rows), "failed": sum(x.status == "FAILED" for x in rows)}
