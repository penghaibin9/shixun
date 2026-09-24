from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m


class ChallengeRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, entity):
        self.session.add(entity)
        self.session.flush()
        return entity

    def challenge(self, challenge_id: str):
        return self.session.get(m.ChallengeDefinition, challenge_id)

    def flag(self, challenge_id: str):
        return self.session.scalar(select(m.ChallengeFlag).where(m.ChallengeFlag.challenge_id == challenge_id))

    def challenges(self, course_ids: frozenset[str], course_id: str | None = None, *, published_only: bool = False):
        stmt = select(m.ChallengeDefinition).where(m.ChallengeDefinition.course_id.in_(course_ids))
        if course_id:
            stmt = stmt.where(m.ChallengeDefinition.course_id == course_id)
        if published_only:
            stmt = stmt.where(m.ChallengeDefinition.status == "PUBLISHED")
        return list(self.session.scalars(stmt.order_by(m.ChallengeDefinition.lesson_id, m.ChallengeDefinition.challenge_id)))

    def hints(self, challenge_id: str):
        return list(self.session.scalars(select(m.ChallengeHint).where(m.ChallengeHint.challenge_id == challenge_id).order_by(m.ChallengeHint.sequence)))

    def attempts(self, challenge_id: str, student_id: str) -> int:
        return int(self.session.scalar(select(func.count()).select_from(m.ChallengeAttempt).where(
            m.ChallengeAttempt.challenge_id == challenge_id,
            m.ChallengeAttempt.student_id == student_id,
        )) or 0)

    def accepted(self, challenge_id: str, student_id: str):
        return self.session.scalar(select(m.ChallengeAttempt).where(
            m.ChallengeAttempt.challenge_id == challenge_id,
            m.ChallengeAttempt.student_id == student_id,
            m.ChallengeAttempt.accepted.is_(True),
        ).order_by(m.ChallengeAttempt.created_at.desc()).limit(1))
