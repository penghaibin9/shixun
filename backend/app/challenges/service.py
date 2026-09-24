from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event
from app.labs.models import LabDefinition, LabVersion
from app.teaching.models import CourseLesson

from . import models as m
from .repository import ChallengeRepository
from .schemas import ChallengeBind, ChallengeCreate, FlagConfigure, FlagSubmit, HintCreate


def now() -> datetime:
    return datetime.utcnow()


class ChallengeService:
    def __init__(self, session: Session, user: UserContext):
        self.session = session
        self.user = user
        self.repo = ChallengeRepository(session)

    def require(self, *permissions: str) -> None:
        if not any(permission in self.user.permissions for permission in permissions):
            raise ApiError("AUTH.PERMISSION_DENIED", "缺少挑战操作权限", 403)

    def require_course(self, course_id: str) -> None:
        if course_id not in self.user.course_ids and "grading:all-courses" not in self.user.permissions:
            raise ApiError("AUTH.COURSE_SCOPE_DENIED", "无权访问该课程挑战", 403)

    def require_class(self, class_id: str) -> None:
        if class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权访问该班级挑战", 403)

    def list_challenges(self, course_id: str | None = None):
        self.require("labs.read", "classroom.lab.read", "classroom.lab.start")
        if course_id:
            self.require_course(course_id)
        rows = self.repo.challenges(self.user.course_ids, course_id)
        return {"items": [self._challenge(row) for row in rows], "page": 1, "page_size": len(rows), "total": len(rows)}

    def get_challenge(self, challenge_id: str):
        self.require("labs.read", "classroom.lab.read", "classroom.lab.start")
        row = self._get(challenge_id)
        return self._challenge(row)

    def create_challenge(self, body: ChallengeCreate):
        self.require("labs.write")
        self.require_course(body.course_id)
        lesson = self.session.scalar(select(CourseLesson).where(
            CourseLesson.course_id == body.course_id,
            CourseLesson.lesson_id == body.lesson_id,
        ))
        if not lesson or lesson.lesson_type != "LAB":
            raise ApiError("CHALLENGE.LAB_LESSON_REQUIRED", "挑战必须绑定本课程实验课时", 422)
        row = self.repo.add(m.ChallengeDefinition(
            challenge_id=str(uuid4()),
            course_id=body.course_id,
            lesson_id=body.lesson_id,
            lab_definition_id=None,
            checkpoint_key=None,
            title=body.title,
            description=body.description,
            difficulty=body.difficulty,
            max_attempts=body.max_attempts,
            status="DRAFT",
            created_by=self.user.user_id,
            created_at=now(),
            published_at=None,
        ))
        self._event("challenge.created", row, {"lesson_id": row.lesson_id})
        self.session.commit()
        return self._challenge(row)

    def bind(self, challenge_id: str, body: ChallengeBind):
        self.require("labs.write")
        row = self._get(challenge_id)
        definition = self.session.get(LabDefinition, body.lab_definition_id)
        if not definition or definition.course_id != row.course_id:
            raise ApiError("CHALLENGE.LAB_SCOPE_MISMATCH", "实验定义不属于挑战课程", 422)
        version = self.session.scalar(select(LabVersion).where(
            LabVersion.lab_definition_id == definition.lab_definition_id,
            LabVersion.status == "PUBLISHED",
        ).order_by(LabVersion.version.desc()).limit(1))
        if not version:
            raise ApiError("CHALLENGE.LAB_NOT_PUBLISHED", "实验定义尚无已发布版本", 409)
        keys = {item.get("checkpoint_id") for item in (version.spec_json or {}).get("checkpoints", [])}
        if body.checkpoint_key not in keys:
            raise ApiError("CHALLENGE.CHECKPOINT_NOT_FOUND", "挑战引用的 Checkpoint 不存在", 422)
        row.lab_definition_id = definition.lab_definition_id
        row.checkpoint_key = body.checkpoint_key
        self._event("challenge.bound", row, {"lab_definition_id": row.lab_definition_id, "checkpoint_key": row.checkpoint_key})
        self.session.commit()
        return self._challenge(row)

    def add_hint(self, challenge_id: str, body: HintCreate):
        self.require("labs.write")
        row = self._get(challenge_id)
        hints = self.repo.hints(challenge_id)
        hint = self.repo.add(m.ChallengeHint(
            hint_id=str(uuid4()),
            challenge_id=challenge_id,
            sequence=len(hints) + 1,
            title=body.title,
            content=body.content,
            unlock_after_attempts=body.unlock_after_attempts,
            created_by=self.user.user_id,
            created_at=now(),
        ))
        self._event("challenge.hint.created", row, {"hint_id": hint.hint_id, "sequence": hint.sequence})
        self.session.commit()
        return self._hint(hint)

    def hints(self, challenge_id: str):
        self.require("labs.read", "classroom.lab.read", "classroom.lab.start")
        row = self._get(challenge_id)
        if self.user.role == "student":
            student_id = self._student_id()
            attempts = self.repo.attempts(challenge_id, student_id)
            items = [hint for hint in self.repo.hints(challenge_id) if hint.unlock_after_attempts <= attempts]
        else:
            attempts = 0
            items = self.repo.hints(challenge_id)
        return {"items": [self._hint(item) for item in items], "attempts": attempts, "total": len(items)}

    def configure_flag(self, challenge_id: str, body: FlagConfigure):
        self.require("labs.write")
        row = self._get(challenge_id)
        salt = secrets.token_hex(16)
        normalized = self._normalize(body.flag, body.case_sensitive)
        digest = self._flag_hash(salt, normalized)
        flag = self.repo.flag(challenge_id)
        if not flag:
            flag = self.repo.add(m.ChallengeFlag(
                flag_id=str(uuid4()),
                challenge_id=challenge_id,
                salt=salt,
                flag_hash=digest,
                case_sensitive=body.case_sensitive,
                configured_by=self.user.user_id,
                configured_at=now(),
            ))
        else:
            flag.salt = salt
            flag.flag_hash = digest
            flag.case_sensitive = body.case_sensitive
            flag.configured_by = self.user.user_id
            flag.configured_at = now()
        self._event("challenge.flag.configured", row, {"case_sensitive": body.case_sensitive})
        self.session.commit()
        return {"challenge_id": challenge_id, "configured": True, "case_sensitive": body.case_sensitive}

    def publish(self, challenge_id: str):
        self.require("labs.write")
        row = self._get(challenge_id)
        if not row.lab_definition_id or not row.checkpoint_key:
            raise ApiError("CHALLENGE.BIND_REQUIRED", "发布前必须绑定已发布实验版本的 Checkpoint", 409)
        if not self.repo.flag(challenge_id):
            raise ApiError("CHALLENGE.FLAG_REQUIRED", "发布前必须配置 Flag", 409)
        row.status = "PUBLISHED"
        row.published_at = now()
        self._event("challenge.published", row, {"lesson_id": row.lesson_id})
        self.session.commit()
        return self._challenge(row)

    def submit(self, challenge_id: str, body: FlagSubmit):
        self.require("classroom.lab.read", "classroom.lab.start")
        row = self._get(challenge_id)
        if row.status != "PUBLISHED":
            raise ApiError("CHALLENGE.NOT_PUBLISHED", "挑战尚未发布", 409)
        self.require_class(body.class_id)
        student_id = self._student_id()
        accepted_before = self.repo.accepted(challenge_id, student_id)
        if accepted_before:
            remaining = max(0, row.max_attempts - accepted_before.attempt_no)
            return self._attempt(accepted_before, remaining)
        count = self.repo.attempts(challenge_id, student_id)
        if count >= row.max_attempts:
            raise ApiError("CHALLENGE.ATTEMPTS_EXHAUSTED", "挑战提交次数已用完", 409)
        flag = self.repo.flag(challenge_id)
        if not flag:
            raise ApiError("CHALLENGE.FLAG_NOT_CONFIGURED", "挑战验证器未配置", 409)
        normalized = self._normalize(body.submission, flag.case_sensitive)
        accepted = hmac.compare_digest(self._flag_hash(flag.salt, normalized), flag.flag_hash)
        attempt = self.repo.add(m.ChallengeAttempt(
            attempt_id=str(uuid4()),
            challenge_id=challenge_id,
            student_id=student_id,
            class_id=body.class_id,
            lab_release_id=body.lab_release_id,
            attempt_no=count + 1,
            accepted=accepted,
            created_at=now(),
        ))
        self._event(
            "lab.challenge.flag.accepted" if accepted else "lab.challenge.flag.rejected",
            row,
            {
                "student_id": student_id,
                "class_id": body.class_id,
                "lab_release_id": body.lab_release_id,
                "attempt_no": attempt.attempt_no,
                "checkpoint_key": row.checkpoint_key,
            },
        )
        self.session.commit()
        return self._attempt(attempt, max(0, row.max_attempts - attempt.attempt_no))

    def _get(self, challenge_id: str):
        row = self.repo.challenge(challenge_id)
        if not row:
            raise ApiError("CHALLENGE.NOT_FOUND", "挑战不存在", 404)
        self.require_course(row.course_id)
        return row

    def _student_id(self) -> str:
        if not self.user.student_id:
            raise ApiError("AUTH.STUDENT_REQUIRED", "当前身份没有关联学生", 403)
        return self.user.student_id

    @staticmethod
    def _normalize(value: str, case_sensitive: bool) -> str:
        value = value.strip()
        return value if case_sensitive else value.lower()

    @staticmethod
    def _flag_hash(salt: str, value: str) -> str:
        return hashlib.sha256(f"{salt}\0{value}".encode("utf-8")).hexdigest()

    def _event(self, event_type: str, row: m.ChallengeDefinition, payload: dict):
        enqueue_event(
            self.session,
            event_type=event_type,
            aggregate_type="challenge",
            aggregate_id=row.challenge_id,
            actor_user_id=self.user.user_id,
            idempotency_key=f"{event_type}:{row.challenge_id}:{uuid4()}",
            payload={"course_id": row.course_id, "lesson_id": row.lesson_id, "challenge_id": row.challenge_id, **payload},
        )

    def _challenge(self, row: m.ChallengeDefinition):
        return {
            "challenge_id": row.challenge_id,
            "course_id": row.course_id,
            "lesson_id": row.lesson_id,
            "lab_definition_id": row.lab_definition_id,
            "checkpoint_key": row.checkpoint_key,
            "title": row.title,
            "description": row.description,
            "difficulty": row.difficulty,
            "max_attempts": row.max_attempts,
            "status": row.status,
            "flag_configured": bool(self.repo.flag(row.challenge_id)),
            "created_by": row.created_by,
            "created_at": row.created_at,
            "published_at": row.published_at,
        }

    @staticmethod
    def _hint(row: m.ChallengeHint):
        return {
            "hint_id": row.hint_id,
            "challenge_id": row.challenge_id,
            "sequence": row.sequence,
            "title": row.title,
            "content": row.content,
            "unlock_after_attempts": row.unlock_after_attempts,
        }

    @staticmethod
    def _attempt(row: m.ChallengeAttempt, remaining: int):
        return {
            "attempt_id": row.attempt_id,
            "challenge_id": row.challenge_id,
            "attempt_no": row.attempt_no,
            "accepted": row.accepted,
            "remaining_attempts": remaining,
            "created_at": row.created_at,
        }
