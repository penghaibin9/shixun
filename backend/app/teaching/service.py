import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import models as auth_models
from app.auth.repository import AuthRepository
from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import DomainEventOutbox
from app.common.outbox import enqueue_event

from . import models as m
from .catalog import catalog_metadata, curriculum_rows
from .repository import TeachingRepository
from .schemas import AssignmentCreate, AttendanceCreate, ClassCreate, CourseCreate, CoursePatch, MemberCreate, PollCreate, QuizCreate, QuizSubmitIn, SubmissionIn
from .xlsx import parse_members


def now() -> datetime:
    return datetime.utcnow()


def entity_dict(entity) -> dict:
    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}


AUTO_SCORE_PER_QUESTION = Decimal("10")
FROZEN_QUESTION_CONTRACT = "teaching-frozen-question/v1"
SCORE_PROOF_CONTRACT = "grading-score-proof/v1"
SCORE_PROOF_ISSUER = "teaching-core"
SCORE_PROOF_ORIGIN = "SERVER_GRADED"
SCORE_PROOF_EVENT_TYPE = "grading.score.proof.frozen"
SUPPORTED_QUESTION_TYPES = frozenset({"FILL", "SINGLE", "MULTIPLE", "TRUE_FALSE"})


def canonical_json(value: Any, *, error_code: str = "TEACHING.SCORE_EVIDENCE_INVALID") -> str:
    """Encode evidence deterministically so later consumers can recompute it."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ApiError(error_code, "答题或判分证据不是可冻结的 JSON 数据", 422) from exc


def sha256_json(value: Any, *, error_code: str = "TEACHING.SCORE_EVIDENCE_INVALID") -> str:
    return hashlib.sha256(canonical_json(value, error_code=error_code).encode("utf-8")).hexdigest()


def canonical_score(value: Decimal) -> str:
    """Keep numeric proof binding byte-for-byte compatible with F's verifier."""

    normalized = value.normalize()
    return format(normalized, "f") if normalized != 0 else "0"


def score_payload_sha256(*, event_id: str, event_type: str, aggregate_id: str, payload: dict, proof: dict, raw: Decimal, maximum: Decimal) -> str:
    """The frozen `grading-score-proof/v1` binding consumed by F.

    This intentionally mirrors F's independently implemented verifier.  The
    data comes only from rows frozen in this service and its outbox events.
    """

    binding = {
        "aggregate_id": aggregate_id,
        "answer_evidence_sha256": proof["answer_evidence_sha256"],
        "contract": proof["contract"],
        "course_id": payload["course_id"],
        "event_id": event_id,
        "event_type": event_type,
        "evidence_type": proof["evidence_type"],
        "frozen_question_count": proof["frozen_question_count"],
        "frozen_question_sha256": proof["frozen_question_sha256"],
        "issuer": proof["issuer"],
        "max_score": canonical_score(maximum),
        "origin": proof["origin"],
        "raw_score": canonical_score(raw),
        "scoring_evidence_sha256": proof["scoring_evidence_sha256"],
        "source_event_id": proof["source_event_id"],
        "source_fact_id": proof["source_fact_id"],
        "student_id": payload["student_id"],
        "class_id": payload["class_id"],
        "lesson_id": payload.get("lesson_id"),
    }
    return hashlib.sha256(canonical_json(binding).encode("utf-8")).hexdigest()


def answer_evidence_from_saved_answers(frozen_evidence: object, saved_answers: object) -> list[dict] | None:
    """Rebuild the answer summary from persisted source facts, not a request."""

    if not isinstance(frozen_evidence, list) or not isinstance(saved_answers, dict):
        return None
    expected: list[dict] = []
    ref_ids: set[str] = set()
    for frozen in frozen_evidence:
        if not isinstance(frozen, dict):
            return None
        ref_id, question_id = frozen.get("question_ref_id"), frozen.get("question_id")
        if not isinstance(ref_id, str) or not ref_id or not isinstance(question_id, str) or not question_id or ref_id in ref_ids:
            return None
        ref_ids.add(ref_id)
        expected.append(
            {
                "question_ref_id": ref_id,
                "question_id": question_id,
                "answer_present": ref_id in saved_answers,
                "answer": saved_answers.get(ref_id) if ref_id in saved_answers else None,
            }
        )
    if set(saved_answers) - ref_ids:
        return None
    return expected


def verify_teaching_score_proof(session: Session, proof_id: str) -> None:
    """Fail closed if A's persisted proof and paired outbox rows diverge.

    This is deliberately callable by tests and future reconciliation jobs.  F
    independently revalidates the envelope it consumes; this check makes a
    direct database mutation of A's own proof evidence detectable before that
    hand-off as well.
    """

    row = session.get(m.TeachingScoreProof, proof_id)
    if not row:
        raise ApiError("TEACHING.SCORE_PROOF_NOT_FOUND", "服务端评分证明不存在", 404)
    proof_event = session.get(DomainEventOutbox, row.score_proof_event_id)
    score_event = session.get(DomainEventOutbox, row.score_event_id)
    mismatches: list[str] = []
    if not proof_event or proof_event.event_type != SCORE_PROOF_EVENT_TYPE:
        mismatches.append("score_proof_event")
    if not score_event:
        mismatches.append("score_event")
    if mismatches:
        raise ApiError("TEACHING.SCORE_PROOF_TAMPERED", "服务端评分证明关联事件缺失或类型不符", 409, {"invalid": mismatches})
    expected_score_event_type = "assignment.submitted" if row.source_type == "assignment_submission" else "quiz.completed" if row.source_type == "quiz_attempt" else None
    expected_aggregate_type = "assignment" if row.source_type == "assignment_submission" else "quiz" if row.source_type == "quiz_attempt" else None
    if not expected_score_event_type or proof_event.aggregate_type != row.source_type or proof_event.aggregate_id != row.source_fact_id:
        mismatches.append("source_scope")
    if proof_event.actor_user_id != "service_teaching_score_prover":
        mismatches.append("proof_actor")
    if score_event.event_type != expected_score_event_type or score_event.aggregate_type != expected_aggregate_type or score_event.aggregate_id != row.score_aggregate_id:
        mismatches.append("score_scope")
    if not proof_event.occurred_at < score_event.occurred_at:
        mismatches.append("event_order")
    score_payload = {
        "course_id": row.course_id,
        "class_id": row.class_id,
        "lesson_id": row.lesson_id,
        "student_id": row.student_id,
        "source_id": row.source_fact_id,
        "raw_score": float(row.raw_score),
        "max_score": float(row.max_score),
    }
    proof_payload = proof_event.payload_json or {}
    proof = proof_payload.get("source_proof")
    if not isinstance(proof, dict):
        mismatches.append("source_proof")
        proof = {}
    expected_proof_payload = {
        "score_event_id": row.score_event_id,
        "score_event_type": expected_score_event_type,
        "score_aggregate_id": row.score_aggregate_id,
        "source_fact_id": row.source_fact_id,
        "course_id": row.course_id,
        "class_id": row.class_id,
        "lesson_id": row.lesson_id,
        "student_id": row.student_id,
        "raw_score": float(row.raw_score),
        "max_score": float(row.max_score),
    }
    if set(proof_payload) != {*expected_proof_payload, "source_proof"}:
        mismatches.append("proof_payload_fields")
    for field, expected in expected_proof_payload.items():
        if proof_payload.get(field) != expected:
            mismatches.append(f"proof_{field}")
    expected_hashes = {
        "frozen_question_sha256": sha256_json(row.frozen_question_evidence_json),
        "answer_evidence_sha256": sha256_json(row.answer_evidence_json),
        "scoring_evidence_sha256": sha256_json(row.scoring_evidence_json),
    }
    for field, expected in expected_hashes.items():
        if getattr(row, field) != expected or proof.get(field) != expected:
            mismatches.append(field)
    expected_proof_values = {
        "contract": row.contract,
        "issuer": row.issuer,
        "origin": row.origin,
        "evidence_type": row.evidence_type,
        "source_event_id": row.score_event_id,
        "source_fact_id": row.source_fact_id,
        "frozen_question_count": row.frozen_question_count,
    }
    for field, expected in expected_proof_values.items():
        if proof.get(field) != expected:
            mismatches.append(field)
    if (score_event.payload_json or {}).get("score_proof_event_id") != row.score_proof_event_id:
        mismatches.append("score_proof_event_id")
    if (score_event.payload_json or {}) != {**score_payload, "score_proof_event_id": row.score_proof_event_id}:
        mismatches.append("score_payload")
    if proof:
        expected_digest = score_payload_sha256(
            event_id=row.score_event_id,
            event_type=expected_score_event_type or "",
            aggregate_id=row.score_aggregate_id,
            payload=score_payload,
            proof=proof,
            raw=Decimal(str(row.raw_score)),
            maximum=Decimal(str(row.max_score)),
        )
        if row.score_payload_sha256 != expected_digest or proof.get("score_payload_sha256") != expected_digest:
            mismatches.append("score_payload_sha256")
    source = session.get(m.AssignmentSubmission, row.source_fact_id) if row.source_type == "assignment_submission" else session.get(m.QuizAttempt, row.source_fact_id) if row.source_type == "quiz_attempt" else None
    if not source or source.student_id != row.student_id or Decimal(str(source.raw_score)) != Decimal(str(row.raw_score)) or Decimal(str(source.max_score)) != Decimal(str(row.max_score)):
        mismatches.append("source_fact")
    else:
        if row.source_type == "assignment_submission":
            expected_answers = answer_evidence_from_saved_answers(row.frozen_question_evidence_json, source.answers_json)
        else:
            quiz_rows = list(session.scalars(select(m.QuizAnswer).where(m.QuizAnswer.attempt_id == row.source_fact_id)))
            saved_answers: dict[str, Any] = {}
            saved_scores: dict[str, Decimal] = {}
            malformed_quiz_answer = False
            for answer_row in quiz_rows:
                answer_json = answer_row.answer_json
                if (
                    answer_row.question_ref_id in saved_answers
                    or not isinstance(answer_json, dict)
                    or set(answer_json) != {"value"}
                ):
                    malformed_quiz_answer = True
                    break
                saved_answers[answer_row.question_ref_id] = answer_json["value"]
                saved_scores[answer_row.question_ref_id] = Decimal(str(answer_row.score))
            expected_answers = None if malformed_quiz_answer else answer_evidence_from_saved_answers(row.frozen_question_evidence_json, saved_answers)
            if expected_answers is not None:
                scoring_by_ref = {
                    item.get("question_ref_id"): item.get("awarded_score")
                    for item in row.scoring_evidence_json
                    if isinstance(item, dict) and isinstance(item.get("question_ref_id"), str)
                } if isinstance(row.scoring_evidence_json, list) else {}
                if set(scoring_by_ref) != {item["question_ref_id"] for item in expected_answers}:
                    mismatches.append("source_scoring")
                for ref_id, score in saved_scores.items():
                    try:
                        expected_score = Decimal(str(scoring_by_ref[ref_id]))
                    except (KeyError, InvalidOperation, ValueError):
                        mismatches.append("source_scoring")
                        break
                    if score != expected_score:
                        mismatches.append("source_scoring")
                        break
        if expected_answers != row.answer_evidence_json:
            mismatches.append("source_answers")
    if mismatches:
        raise ApiError("TEACHING.SCORE_PROOF_TAMPERED", "服务端评分证明、提交事实或事件箱不一致", 409, {"invalid": sorted(set(mismatches))})


class TeachingService:
    def __init__(self, session: Session, user: UserContext):
        self.session, self.user, self.repo = session, user, TeachingRepository(session)
        self.auth_repo = AuthRepository(session)

    def require(self, permission: str):
        if permission not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "没有执行此操作的权限", 403)

    def require_course(self, course_id: str):
        if course_id not in self.user.course_ids:
            raise ApiError("AUTH.SCOPE_DENIED", "不能访问该课程", 403)

    def require_class(self, class_id: str):
        if class_id not in self.user.class_ids:
            raise ApiError("AUTH.SCOPE_DENIED", "不能访问该班级", 403)

    def require_lesson(self, course_id: str, lesson_id: str | None):
        if lesson_id and not self.repo.course_lesson(course_id, lesson_id):
            raise ApiError("COURSE.LESSON_SCOPE_MISMATCH", "课时不存在或不属于当前课程", 422)

    def require_student(self) -> str:
        if not self.user.student_id:
            raise ApiError("AUTH.STUDENT_REQUIRED", "当前身份没有关联学生", 403)
        return self.user.student_id

    def require_active_membership(self, class_id: str, student_id: str) -> m.ClassMembership:
        membership = self.repo.membership(class_id, student_id)
        if not membership or membership.status != "ACTIVE":
            raise ApiError("AUTH.SCOPE_DENIED", "不是该班级的有效成员", 403)
        return membership

    def require_mutable_roster(self, class_id: str) -> m.TeachingClass:
        item = self.repo.class_for_update(class_id)
        if not item:
            raise ApiError("CLASS.NOT_FOUND", "班级不存在", 404)
        if item.roster_frozen_at:
            raise ApiError("CLASS.ROSTER_FROZEN", "班级名单已冻结，不能再增删或导入学生", 409, {"class_id": class_id, "frozen_at": item.roster_frozen_at.isoformat()})
        return item

    def audit(self, action: str, aggregate_type: str, aggregate_id: str, payload: dict):
        enqueue_event(self.session, event_type="teaching.audit", aggregate_type=aggregate_type, aggregate_id=aggregate_id, actor_user_id=self.user.user_id, idempotency_key=f"{action}:{aggregate_id}:{uuid4()}", payload={"action": action, "actor_role": self.user.role, **payload})

    def course_catalogs(self):
        self.require("teaching.course.read")
        return {"items": catalog_metadata()}

    def create_course(self, body: CourseCreate):
        self.require("teaching.course.write")
        if not self.user.teacher_id:
            raise ApiError("AUTH.TEACHER_REQUIRED", "当前身份没有关联教师", 403)
        course_fields = body.model_dump()
        course_id = str(uuid4())
        try:
            catalog = curriculum_rows(course_id, body.catalog_key)
        except ValueError as error:
            raise ApiError(
                "TEACHING.CATALOG_NOT_FOUND",
                "课程模板不存在或内容包无效",
                422,
                {"catalog_key": body.catalog_key},
            ) from error
        item = self.repo.add(m.Course(course_id=course_id, owner_teacher_id=self.user.teacher_id, created_at=now(), status="DRAFT", **course_fields))
        for row in catalog["chapters"]:
            self.repo.add(m.CourseChapter(**row))
        for row in catalog["lessons"]:
            self.repo.add(m.CourseLesson(**row))
        self.audit("course.created", "course", item.course_id, {"course_id": item.course_id, "catalog_key": item.catalog_key})
        self.session.commit()
        return entity_dict(item) | {
            "theory_lesson_count": sum(row["lesson_type"] == "THEORY" for row in catalog["lessons"]),
            "lab_lesson_count": sum(row["lesson_type"] == "LAB" for row in catalog["lessons"]),
        }

    def list_courses(self):
        self.require("teaching.course.read")
        items = self.repo.list_courses(self.user.course_ids)
        rows = []
        for item in items:
            lessons = [lesson for lesson, _ in self.repo.course_lessons(item.course_id)]
            rows.append(
                entity_dict(item)
                | {
                    "theory_lesson_count": sum(lesson.lesson_type == "THEORY" for lesson in lessons),
                    "lab_lesson_count": sum(lesson.lesson_type == "LAB" for lesson in lessons),
                }
            )
        return {"items": rows, "page": 1, "page_size": len(rows), "total": len(rows)}

    def get_course(self, course_id: str):
        self.require("teaching.course.read"); self.require_course(course_id)
        item = self.repo.get(m.Course, course_id)
        if not item:
            raise ApiError("COURSE.NOT_FOUND", "课程不存在", 404)
        return entity_dict(item)

    def course_lessons(self, course_id: str):
        self.require("teaching.course.read"); self.require_course(course_id)
        if not self.repo.get(m.Course, course_id):
            raise ApiError("COURSE.NOT_FOUND", "课程不存在", 404)
        rows = [
            {
                **entity_dict(lesson),
                "chapter_title": chapter.title,
                "chapter_sequence": chapter.sequence,
            }
            for lesson, chapter in self.repo.course_lessons(course_id)
        ]
        return {
            "items": rows,
            "total": len(rows),
            "theory_count": sum(row["lesson_type"] == "THEORY" for row in rows),
            "lab_count": sum(row["lesson_type"] == "LAB" for row in rows),
        }

    def patch_course(self, course_id: str, body: CoursePatch):
        self.require("teaching.course.write"); self.require_course(course_id)
        item = self.repo.get(m.Course, course_id)
        if not item:
            raise ApiError("COURSE.NOT_FOUND", "课程不存在", 404)
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        self.audit("course.updated", "course", course_id, {"course_id": course_id})
        self.session.commit()
        return entity_dict(item)

    def create_class(self, body: ClassCreate):
        self.require("teaching.class.write"); self.require_course(body.course_id)
        if not self.user.teacher_id:
            raise ApiError("AUTH.TEACHER_REQUIRED", "当前身份没有关联教师", 403)
        item = self.repo.add(m.TeachingClass(class_id=str(uuid4()), name=body.name, term=body.term, owner_teacher_id=self.user.teacher_id, created_at=now()))
        self.repo.add(m.ClassCourse(class_course_id=str(uuid4()), class_id=item.class_id, course_id=body.course_id))
        self.repo.add(m.TeachingTeacherAssignment(assignment_id=str(uuid4()), teacher_id=self.user.teacher_id, class_id=item.class_id, course_id=body.course_id))
        self.audit("class.created", "class", item.class_id, {"class_id": item.class_id, "course_id": body.course_id})
        self.session.commit()
        return entity_dict(item) | {"course_id": body.course_id}

    def list_classes(self):
        self.require("teaching.class.read")
        items = self.repo.list_classes(self.user.class_ids)
        return {"items": [entity_dict(x) for x in items], "page": 1, "page_size": len(items), "total": len(items)}

    def get_class(self, class_id: str):
        self.require("teaching.class.read"); self.require_class(class_id)
        item = self.repo.get(m.TeachingClass, class_id)
        if not item: raise ApiError("CLASS.NOT_FOUND", "班级不存在", 404)
        return entity_dict(item)

    def members(self, class_id: str, *, search: str = "", status: str = "ACTIVE", sort: str = "student_number", direction: str = "asc", page: int = 1, page_size: int = 20):
        self.require("teaching.members.read"); self.require_class(class_id)
        items, total = self.repo.members(class_id, search=search, status=status, sort=sort, direction=direction, offset=(page-1)*page_size, limit=page_size)
        return {"items": [entity_dict(x) for x in items], "page": page, "page_size": page_size, "total": total}

    def member_detail(self, class_id: str, membership_id: str):
        self.require("teaching.members.read"); self.require_class(class_id)
        item = self.repo.membership_by_id(class_id, membership_id) or self.repo.membership(class_id, membership_id)
        if not item: raise ApiError("MEMBER.NOT_FOUND", "班级成员不存在", 404)
        return entity_dict(item)

    def _record_identity_case(self, *, class_id: str, student_number: str, student_name: str, phone: str | None, email: str | None, reason_code: str, details: dict, legacy_student_id: str | None = None, canonical_student_id: str | None = None) -> None:
        # 有既有成员标识时，一个班级只保留一个待核对事项，重试不能把
        # 同一身份冲突变成数据库唯一约束错误；没有历史标识的导入行仍逐行留证。
        if legacy_student_id and self.auth_repo.reconciliation_case(legacy_student_id, class_id):
            return
        self.session.add(
            auth_models.IdentityReconciliationCase(
                reconciliation_case_id=str(uuid4()),
                legacy_student_id=legacy_student_id,
                canonical_student_id=canonical_student_id,
                class_id=class_id,
                student_number=student_number,
                observed_name=student_name,
                observed_phone=phone,
                observed_email=email,
                reason_code=reason_code,
                status="PENDING",
                details_json=details,
                created_by=self.user.user_id,
                created_at=now(),
                resolved_by=None,
                resolved_at=None,
            )
        )

    def _resolve_roster_student(self, *, class_id: str, student_number: str, student_name: str, phone: str | None = None, email: str | None = None, legacy_student_id: str | None = None):
        profile = self.auth_repo.student_profile_by_number(student_number)
        if not profile:
            self._record_identity_case(
                class_id=class_id,
                student_number=student_number,
                student_name=student_name,
                phone=phone,
                email=email,
                reason_code="STUDENT_PROFILE_NOT_FOUND",
                details={"message": "学号不存在，不能创建班级成员"},
                legacy_student_id=legacy_student_id,
            )
            return None, "学号不存在或账号不可用", "STUDENT.PROFILE_NOT_FOUND"
        account = self.auth_repo.user(profile.user_id)
        if profile.status != "ACTIVE" or not account or account.status != "ACTIVE":
            self._record_identity_case(
                class_id=class_id,
                student_number=student_number,
                student_name=student_name,
                phone=phone,
                email=email,
                reason_code="STUDENT_PROFILE_DISABLED",
                details={"message": "学生档案或账号已停用", "student_id": profile.student_id},
                legacy_student_id=legacy_student_id,
                canonical_student_id=profile.student_id,
            )
            return None, "学号不存在或账号不可用", "STUDENT.PROFILE_DISABLED"
        if profile.full_name.strip() != student_name.strip():
            self._record_identity_case(
                class_id=class_id,
                student_number=student_number,
                student_name=student_name,
                phone=phone,
                email=email,
                reason_code="STUDENT_NAME_CONFLICT",
                details={"message": "导入姓名与学生档案不一致", "profile_name": profile.full_name, "student_id": profile.student_id},
                legacy_student_id=legacy_student_id,
                canonical_student_id=profile.student_id,
            )
            return None, "姓名与已有学生档案不一致", "STUDENT.NAME_CONFLICT"
        return profile, None, None

    def add_member(self, class_id: str, body: MemberCreate):
        self.require("teaching.members.write"); self.require_class(class_id)
        self.require_mutable_roster(class_id)
        existing = self.repo.membership_by_number(class_id, body.student_number)
        profile, reason, code = self._resolve_roster_student(
            class_id=class_id,
            student_number=body.student_number,
            student_name=body.student_name,
            legacy_student_id=existing.student_id if existing else None,
        )
        if not profile:
            self.session.commit()
            raise ApiError(code or "STUDENT.PROFILE_NOT_FOUND", reason or "学生账号不可用", 422)
        if existing:
            if existing.student_id != profile.student_id:
                self._record_identity_case(
                    class_id=class_id,
                    student_number=body.student_number,
                    student_name=body.student_name,
                    phone=None,
                    email=None,
                    reason_code="MEMBERSHIP_IDENTITY_CONFLICT",
                    details={"message": "班级已有成员与学生档案身份不一致", "membership_student_id": existing.student_id, "profile_student_id": profile.student_id},
                    legacy_student_id=existing.student_id,
                    canonical_student_id=profile.student_id,
                )
                self.session.commit()
                raise ApiError("MEMBER.IDENTITY_CONFLICT", "班级已有成员与学生档案身份不一致，需人工核对", 409)
            existing.status = "ACTIVE"; existing.student_name = profile.full_name; existing.phone = profile.phone; existing.email = profile.email
            item = existing
        else:
            item = self.repo.add(m.ClassMembership(class_membership_id=str(uuid4()), class_id=class_id, student_id=profile.student_id, student_number=profile.student_number, student_name=profile.full_name, phone=profile.phone, email=profile.email, status="ACTIVE", joined_at=now()))
        course = self.repo.class_course(class_id)
        self.audit("membership.added", "class_membership", item.class_membership_id, {"course_id": course.course_id if course else None, "class_id": class_id, "student_id": item.student_id})
        self.session.commit(); return entity_dict(item)

    def remove_member(self, class_id: str, membership_id: str):
        self.require("teaching.members.write"); self.require_class(class_id)
        self.require_mutable_roster(class_id)
        item = self.repo.membership_by_id(class_id, membership_id) or self.repo.membership(class_id, membership_id)
        if not item: raise ApiError("MEMBER.NOT_FOUND", "班级成员不存在", 404)
        item.status = "REMOVED"
        course = self.repo.class_course(class_id)
        self.audit("membership.removed", "class_membership", membership_id, {"course_id": course.course_id if course else None, "class_id": class_id, "student_id": item.student_id})
        self.session.commit(); return {"class_membership_id": membership_id, "status": "REMOVED"}

    def freeze_roster(self, class_id: str):
        self.require("teaching.roster.freeze"); self.require_class(class_id)
        teaching_class = self.repo.class_for_update(class_id)
        if not teaching_class:
            raise ApiError("CLASS.NOT_FOUND", "班级不存在", 404)
        course = self.repo.class_course(class_id)
        if not course:
            raise ApiError("CLASS.COURSE_NOT_BOUND", "班级尚未绑定课程，不能冻结名单", 409)
        members, _ = self.repo.members(class_id, status="ACTIVE", sort="student_number", direction="asc", offset=0, limit=100000)
        snapshot = [{"student_id": row.student_id, "student_number": row.student_number, "student_name": row.student_name} for row in members]
        digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if not teaching_class.roster_frozen_at:
            teaching_class.roster_frozen_at = now()
            teaching_class.roster_frozen_by = self.user.user_id
            teaching_class.roster_snapshot_hash = digest
            enqueue_event(
                self.session,
                event_type="course.roster.frozen",
                aggregate_type="class_roster",
                aggregate_id=class_id,
                actor_user_id=self.user.user_id,
                idempotency_key=f"course.roster.frozen:{class_id}",
                payload={"course_id": course.course_id, "class_id": class_id, "member_count": len(snapshot), "snapshot_hash": digest, "frozen_at": teaching_class.roster_frozen_at.isoformat()},
            )
            self.session.commit()
        return {"class_id": class_id, "course_id": course.course_id, "status": "FROZEN", "member_count": len(snapshot), "snapshot_hash": teaching_class.roster_snapshot_hash, "frozen_at": teaching_class.roster_frozen_at, "frozen_by": teaching_class.roster_frozen_by}

    def learning_summary(self, class_id: str, membership_id: str):
        self.require("teaching.members.read"); self.require_class(class_id)
        item = self.repo.membership_by_id(class_id, membership_id) or self.repo.membership(class_id, membership_id)
        if not item: raise ApiError("MEMBER.NOT_FOUND", "班级成员不存在", 404)
        tasks = self.repo.attendance_tasks(frozenset({class_id}))
        attendance_signed = sum(bool(self.repo.attendance_record(x.task_id, item.student_id)) for x in tasks)
        assignment_submitted = self.session.query(m.AssignmentSubmission).filter_by(student_id=item.student_id).count()
        quiz_completed = self.session.query(m.QuizAttempt).filter_by(student_id=item.student_id, status="SUBMITTED").count()
        pending = {"status": "PENDING_AGGREGATION", "label": "数据待汇总"}
        return {"student_id": item.student_id, "attendance": {"signed": attendance_signed, "total": len(tasks)}, "assignment_submitted": assignment_submitted, "quiz_completed": quiz_completed, "experiment": pending, "grade": pending, "risk": pending}

    def import_members(self, class_id: str, data: bytes, key: str):
        self.require("teaching.members.import"); self.require_class(class_id)
        if not key:
            raise ApiError("REQUEST.IDEMPOTENCY_REQUIRED", "导入必须提供 Idempotency-Key", 400)
        if len(key) > 128:
            raise ApiError("REQUEST.IDEMPOTENCY_INVALID", "导入幂等标识不能超过 128 个字符", 422)
        teaching_class = self.repo.class_for_update(class_id)
        if not teaching_class:
            raise ApiError("CLASS.NOT_FOUND", "班级不存在", 404)
        if teaching_class.roster_frozen_at:
            raise ApiError("CLASS.ROSTER_FROZEN", "班级名单已冻结，不能继续修改", 409)
        request_sha256 = hashlib.sha256(data).hexdigest()
        previous = self.repo.import_job(class_id, key)
        if previous:
            if not previous.request_sha256:
                raise ApiError(
                    "REQUEST.IDEMPOTENCY_DIGEST_MISSING",
                    "历史导入任务缺少文件摘要，不能安全复用该幂等标识，请使用新的 Idempotency-Key",
                    409,
                    {"job_id": previous.job_id},
                )
            if previous.request_sha256 != request_sha256:
                raise ApiError("REQUEST.IDEMPOTENCY_CONFLICT", "同一导入幂等标识对应了不同文件", 409)
            return entity_dict(previous)
        try:
            valid, errors = parse_members(data, teaching_class.name)
        except ValueError as exc:
            raise ApiError("IMPORT.INVALID_XLSX", str(exc), 422) from exc
        duplicate_count = sum("重复" in item["reason"] for item in errors)
        success_count = 0
        for item in valid:
            existing = self.repo.membership_by_number(class_id, item["student_number"])
            profile, reason, _ = self._resolve_roster_student(
                class_id=class_id,
                student_number=item["student_number"],
                student_name=item["student_name"],
                phone=item["phone"] or None,
                email=item["email"] or None,
                legacy_student_id=existing.student_id if existing else None,
            )
            if not profile:
                errors.append({**item, "reason": reason or "学号不存在或账号不可用"})
                continue
            if existing and existing.status == "ACTIVE":
                duplicate_count += 1
                errors.append({**item, "reason": "该学号已在班级中"})
                continue
            if existing:
                if existing.student_id != profile.student_id:
                    self._record_identity_case(
                        class_id=class_id,
                        student_number=item["student_number"],
                        student_name=item["student_name"],
                        phone=item["phone"] or None,
                        email=item["email"] or None,
                        reason_code="MEMBERSHIP_IDENTITY_CONFLICT",
                        details={"message": "班级已有成员与学生档案身份不一致", "membership_student_id": existing.student_id, "profile_student_id": profile.student_id},
                        legacy_student_id=existing.student_id,
                        canonical_student_id=profile.student_id,
                    )
                    errors.append({**item, "reason": "班级已有成员与学生档案身份不一致，需人工核对"})
                    continue
                existing.status = "ACTIVE"; existing.student_name = profile.full_name; existing.phone = profile.phone; existing.email = profile.email
            else:
                self.repo.add(m.ClassMembership(class_membership_id=str(uuid4()), class_id=class_id, student_id=profile.student_id, student_number=profile.student_number, student_name=profile.full_name, phone=profile.phone, email=profile.email, status="ACTIVE", joined_at=now()))
            success_count += 1
        job = self.repo.add(m.ImportJob(job_id=str(uuid4()), class_id=class_id, idempotency_key=key, request_sha256=request_sha256, status="COMPLETED", success_count=success_count, failure_count=len(errors), duplicate_count=duplicate_count, error_rows_json=errors, created_by=self.user.user_id, created_at=now()))
        course = self.repo.class_course(class_id)
        self.audit("membership.imported", "class", class_id, {"course_id": course.course_id if course else None, "class_id": class_id, "job_id": job.job_id, "success_count": job.success_count, "failure_count": job.failure_count})
        self.session.commit()
        return entity_dict(job)

    def get_import_job(self, job_id: str):
        self.require("teaching.members.read")
        job = self.repo.get(m.ImportJob, job_id)
        if not job: raise ApiError("IMPORT.NOT_FOUND", "导入任务不存在", 404)
        self.require_class(job.class_id)
        return entity_dict(job)

    def create_attendance(self, body: AttendanceCreate):
        self.require("teaching.attendance.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        self.require_lesson(body.course_id, body.lesson_id)
        if body.expires_at <= body.starts_at:
            raise ApiError("ATTENDANCE.INVALID_WINDOW", "结束时间必须晚于开始时间", 422)
        task = self.repo.add(m.AttendanceTask(task_id=str(uuid4()), status="DRAFT", created_by=self.user.user_id, **body.model_dump()))
        self.audit("attendance.created", "attendance_task", task.task_id, {"course_id": task.course_id, "class_id": task.class_id})
        self.session.commit(); return entity_dict(task)

    def list_attendance(self):
        self.require("teaching.attendance.read")
        items = self.repo.attendance_tasks(self.user.class_ids)
        return {"items": [entity_dict(x) for x in items], "page": 1, "page_size": len(items), "total": len(items)}

    def attendance(self, task_id: str):
        self.require("teaching.attendance.read")
        task = self.repo.get(m.AttendanceTask, task_id)
        if not task: raise ApiError("ATTENDANCE.NOT_FOUND", "签到任务不存在", 404)
        self.require_class(task.class_id); return entity_dict(task)

    def publish_attendance(self, task_id: str):
        self.require("teaching.attendance.write")
        task = self.repo.get(m.AttendanceTask, task_id)
        if not task: raise ApiError("ATTENDANCE.NOT_FOUND", "签到任务不存在", 404)
        self.require_class(task.class_id)
        if task.status != "DRAFT": raise ApiError("ATTENDANCE.INVALID_STATE", "只有草稿可发布", 409)
        token = secrets.token_urlsafe(32)
        task.sign_token_hash = hashlib.sha256(token.encode()).hexdigest(); task.status = "PUBLISHED"
        self.audit("attendance.published", "attendance_task", task_id, {"course_id": task.course_id, "class_id": task.class_id})
        self.session.commit(); return {**entity_dict(task), "sign_token": token, "sign_url": f"/student-attendance/{token}"}

    def close_attendance(self, task_id: str):
        self.require("teaching.attendance.write")
        task = self.repo.get(m.AttendanceTask, task_id)
        if not task: raise ApiError("ATTENDANCE.NOT_FOUND", "签到任务不存在", 404)
        self.require_class(task.class_id); task.status = "CLOSED"
        self.audit("attendance.closed", "attendance_task", task_id, {"course_id": task.course_id, "class_id": task.class_id})
        self.session.commit(); return entity_dict(task)

    def sign(self, task_id: str, token: str):
        task, student_id = self._attendance_link_context(token, lock=True)
        if task.task_id != task_id:
            raise ApiError("ATTENDANCE.INVALID_LINK", "签到链接无效", 404)
        return self._sign_attendance(task, student_id)

    def attendance_link(self, token: str):
        task, _ = self._attendance_link_context(token)
        return {
            "task_id": task.task_id,
            "title": task.title,
            "task_type": task.task_type,
            "starts_at": task.starts_at,
            "expires_at": task.expires_at,
            "status": task.status,
        }

    def sign_by_token(self, token: str):
        task, student_id = self._attendance_link_context(token, lock=True)
        return self._sign_attendance(task, student_id)

    def _attendance_link_context(self, token: str, *, lock: bool = False) -> tuple[m.AttendanceTask, str]:
        self.require("teaching.attendance.sign")
        student_id = self.require_student()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        task = self.repo.attendance_task_by_token_hash(token_hash, lock=lock)
        if not task or not task.sign_token_hash or not secrets.compare_digest(task.sign_token_hash, token_hash):
            raise ApiError("ATTENDANCE.INVALID_LINK", "签到链接无效", 404)
        self.require_active_membership(task.class_id, student_id)
        return task, student_id

    def _sign_attendance(self, task: m.AttendanceTask, student_id: str):
        current = now()
        if task.status != "PUBLISHED": raise ApiError("ATTENDANCE.CLOSED", "签到已关闭", 409)
        if current < task.starts_at: raise ApiError("ATTENDANCE.NOT_STARTED", "签到尚未开始", 409)
        if current > task.expires_at: raise ApiError("ATTENDANCE.EXPIRED", "签到已过期", 409)
        existing = self.repo.attendance_record(task.task_id, student_id)
        if existing: return entity_dict(existing)
        midpoint = task.starts_at + (task.expires_at - task.starts_at) / 2
        result = "LATE" if current > midpoint else "ON_TIME"
        record = self.repo.add(m.AttendanceRecord(record_id=str(uuid4()), task_id=task.task_id, student_id=student_id, signed_at=current, result=result, source="WEB"))
        enqueue_event(self.session, event_type="attendance.completed", aggregate_type="attendance_task", aggregate_id=task.task_id, actor_user_id=self.user.user_id, idempotency_key=f"{task.task_id}:{student_id}", payload={"course_id": task.course_id, "class_id": task.class_id, "lesson_id": task.lesson_id, "student_id": student_id, "source_id": record.record_id, "raw_score": 1, "max_score": 1})
        self.audit("attendance.signed", "attendance_record", record.record_id, {"course_id": task.course_id, "class_id": task.class_id, "task_id": task.task_id, "student_id": student_id})
        self.session.commit(); return entity_dict(record)

    def attendance_records(self, task_id: str):
        task = self.repo.get(m.AttendanceTask, task_id)
        if not task: raise ApiError("ATTENDANCE.NOT_FOUND", "签到任务不存在", 404)
        self.require("teaching.attendance.read"); self.require_class(task.class_id)
        items = self.repo.attendance_records(task_id)
        return {"items": [entity_dict(x) for x in items], "page": 1, "page_size": len(items), "total": len(items)}

    def section_summary(self):
        self.require("teaching.attendance.read")
        results = []
        for task in self.repo.attendance_tasks(self.user.class_ids):
            members, _ = self.repo.members(task.class_id, limit=10000); records = self.repo.attendance_records(task.task_id)
            on_time = sum(x.result == "ON_TIME" for x in records); late = sum(x.result == "LATE" for x in records)
            lesson = self.repo.get(m.CourseLesson, task.lesson_id) if task.lesson_id else None
            results.append({"task_id": task.task_id, "lesson": lesson.title if lesson else None, "task_type": task.task_type, "expected": len(members), "present": len(records), "late": late, "absent": max(0, len(members) - on_time - late), "status": task.status})
        return {"items": results, "page": 1, "page_size": len(results), "total": len(results)}

    def create_poll(self, body: PollCreate):
        self.require("teaching.poll.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        self.require_lesson(body.course_id, body.lesson_id)
        poll = self.repo.add(m.Poll(poll_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lesson_id=body.lesson_id, poll_type=body.poll_type, title=body.title, status="DRAFT", created_by=self.user.user_id))
        options = [self.repo.add(m.PollOption(option_id=str(uuid4()), poll_id=poll.poll_id, label=label, sequence=index)) for index, label in enumerate(body.options, 1)]
        self.audit("poll.created", "poll", poll.poll_id, {"course_id": poll.course_id, "class_id": poll.class_id})
        self.session.commit(); return entity_dict(poll) | {"options": [entity_dict(x) for x in options]}

    def publish_poll(self, poll_id: str):
        self.require("teaching.poll.write"); poll = self.repo.get(m.Poll, poll_id)
        if not poll: raise ApiError("POLL.NOT_FOUND", "投票不存在", 404)
        self.require_class(poll.class_id)
        if poll.status != "DRAFT": raise ApiError("POLL.INVALID_STATE", "只有草稿可发布", 409)
        poll.status = "PUBLISHED"; self.audit("poll.published", "poll", poll_id, {"course_id": poll.course_id, "class_id": poll.class_id}); self.session.commit(); return entity_dict(poll)

    def answer_poll(self, poll_id: str, option_id: str):
        self.require("teaching.poll.answer"); student_id = self.require_student(); poll = self.repo.get(m.Poll, poll_id)
        if not poll or poll.status != "PUBLISHED": raise ApiError("POLL.NOT_OPEN", "投票未开放", 409)
        self.require_active_membership(poll.class_id, student_id)
        option = self.repo.get(m.PollOption, option_id)
        if not option or option.poll_id != poll_id: raise ApiError("POLL.INVALID_OPTION", "选项无效", 422)
        if self.repo.poll_answer(poll_id, student_id): raise ApiError("POLL.DUPLICATE_ANSWER", "不能重复投票", 409)
        answer = self.repo.add(m.PollAnswer(answer_id=str(uuid4()), poll_id=poll_id, option_id=option_id, student_id=student_id, answered_at=now()))
        enqueue_event(self.session, event_type="poll.completed", aggregate_type="poll", aggregate_id=poll_id, actor_user_id=self.user.user_id, idempotency_key=f"{poll_id}:{student_id}", payload={"course_id": poll.course_id, "class_id": poll.class_id, "lesson_id": poll.lesson_id, "student_id": student_id, "source_id": answer.answer_id, "raw_score": 1, "max_score": 1})
        self.audit("poll.answered", "poll_answer", answer.answer_id, {"course_id": poll.course_id, "class_id": poll.class_id, "poll_id": poll_id, "student_id": student_id}); self.session.commit(); return entity_dict(answer)

    def poll_results(self, poll_id: str):
        self.require("teaching.poll.read"); poll = self.repo.get(m.Poll, poll_id)
        if not poll: raise ApiError("POLL.NOT_FOUND", "投票不存在", 404)
        self.require_class(poll.class_id); return {"poll_type": poll.poll_type, "items": self.repo.poll_results(poll_id)}

    def _freeze_published_questions(self, *, course_id: str, lesson_id: str | None, selections) -> list[dict]:
        """Resolve teacher selections against B's published facts and freeze them.

        A intentionally accepts only question IDs.  The version hash, answer key,
        visible snapshot and fixed per-question points all originate here from
        B's approved question row, never from a browser request.
        """

        question_ids = [selection.question_id for selection in selections]
        if len(question_ids) != len(set(question_ids)):
            raise ApiError("QUESTION.FROZEN_DUPLICATE", "同一作业或测验不能重复引用题目", 422)
        rows = self.repo.published_questions_for_freeze(course_id, question_ids)
        by_question_id: dict[str, tuple[Any, str]] = {}
        for question, source_lesson_id in rows:
            if question.question_id in by_question_id:
                raise ApiError("QUESTION.FROZEN_SOURCE_AMBIGUOUS", "题目存在多个课时映射，不能冻结", 422, {"question_id": question.question_id})
            by_question_id[question.question_id] = (question, source_lesson_id)
        missing = sorted(set(question_ids) - set(by_question_id))
        if missing:
            raise ApiError(
                "QUESTION.FROZEN_SOURCE_UNAVAILABLE",
                "题目不存在、未发布或不属于当前课程，不能创建作业或测验",
                422,
                {"question_ids": missing},
            )

        frozen: list[dict] = []
        for question_id in question_ids:
            question, source_lesson_id = by_question_id[question_id]
            if lesson_id and source_lesson_id != lesson_id:
                raise ApiError(
                    "QUESTION.FROZEN_LESSON_SCOPE_MISMATCH",
                    "题目不属于当前教学任务选择的课时",
                    422,
                    {"question_id": question_id, "lesson_id": lesson_id},
                )
            if question.question_type not in SUPPORTED_QUESTION_TYPES:
                raise ApiError("QUESTION.FROZEN_TYPE_UNSUPPORTED", "题目类型不支持自动判分，不能冻结", 422, {"question_id": question_id})
            if not question.reviewed_by or question.reviewed_by == question.created_by or not question.reviewed_at:
                raise ApiError(
                    "QUESTION.FROZEN_SOURCE_UNAVAILABLE",
                    "题目缺少独立审核的已发布事实，不能冻结",
                    422,
                    {"question_id": question_id},
                )
            if not isinstance(question.answer_json, list) or not question.answer_json:
                raise ApiError("QUESTION.FROZEN_ANSWER_INVALID", "已发布题目的标准答案不完整，不能冻结", 422, {"question_id": question_id})
            # Ensure the source answer is actually scoreable before a task can
            # be created.  `canonical_json` alone would allow objects which
            # cannot later be compared as a student answer.
            canonical_json(question.answer_json, error_code="QUESTION.FROZEN_ANSWER_INVALID")
            try:
                normalized_answer = [self._normalize_answer_atom(value) for value in question.answer_json]
            except ApiError as exc:
                raise ApiError(
                    "QUESTION.FROZEN_ANSWER_INVALID",
                    "已发布题目的标准答案格式不支持自动判分，不能冻结",
                    422,
                    {"question_id": question_id},
                ) from exc
            if not normalized_answer or any(not value for value in normalized_answer):
                raise ApiError("QUESTION.FROZEN_ANSWER_INVALID", "已发布题目的标准答案不完整，不能冻结", 422, {"question_id": question_id})
            options = [
                {"key": option.option_key, "text": option.option_text}
                for option in self.repo.question_options_for_freeze(question.question_id)
            ]
            authoritative = {
                "question_id": question.question_id,
                "lesson_id": source_lesson_id,
                "question_type": question.question_type,
                "stem": question.stem,
                "answer": question.answer_json,
                "options": options,
                "reviewed_by": question.reviewed_by,
                "reviewed_at": question.reviewed_at.isoformat() if question.reviewed_at else None,
            }
            version = sha256_json(authoritative, error_code="QUESTION.FROZEN_SOURCE_INVALID")
            snapshot = {
                "contract": FROZEN_QUESTION_CONTRACT,
                **authoritative,
                "question_version": version,
                "max_score": int(AUTO_SCORE_PER_QUESTION),
            }
            frozen.append(
                {
                    "question_id": question.question_id,
                    "question_version": version,
                    "question_snapshot": snapshot,
                    "max_score": int(AUTO_SCORE_PER_QUESTION),
                }
            )
        return frozen

    @staticmethod
    def _frozen_refs(source_kind: str, source_id: str, session: Session):
        model = m.AssignmentQuestionRef if source_kind == "assignment" else m.QuizQuestionRef
        column = model.assignment_id if source_kind == "assignment" else model.quiz_id
        return list(session.scalars(select(model).where(column == source_id).order_by(model.ref_id)))

    @staticmethod
    def _normalize_answer_atom(value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.strip().casefold().split())
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            try:
                return canonical_json(value, error_code="TEACHING.ANSWER_VALUE_INVALID")
            except ApiError:
                raise
        raise ApiError("TEACHING.ANSWER_VALUE_INVALID", "作答值必须是字符串、数字、布尔值或选择项列表", 422)

    @classmethod
    def _answer_matches(cls, snapshot: dict, answer: Any) -> bool:
        if answer is None:
            return False
        expected = snapshot.get("answer")
        question_type = snapshot.get("question_type")
        if not isinstance(expected, list) or not expected or question_type not in SUPPORTED_QUESTION_TYPES:
            raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目缺少可复核的标准答案", 409)
        if question_type == "MULTIPLE":
            actual_values = answer if isinstance(answer, list) else [answer]
            try:
                actual = {cls._normalize_answer_atom(value) for value in actual_values}
                target = {cls._normalize_answer_atom(value) for value in expected}
            except ApiError:
                raise
            return bool(actual) and actual == target
        if isinstance(answer, list):
            if len(answer) != 1:
                return False
            answer = answer[0]
        actual = cls._normalize_answer_atom(answer)
        expected_values = [cls._normalize_answer_atom(value) for value in expected]
        if question_type == "FILL":
            return actual in expected_values
        return actual == expected_values[0]

    @staticmethod
    def _resolve_answers(refs: list, submitted_answers: dict[str, Any]) -> dict[str, Any]:
        aliases: dict[str, Any] = {}
        for ref in refs:
            for alias in (ref.ref_id, ref.question_id):
                existing = aliases.get(alias)
                if existing is not None and existing.ref_id != ref.ref_id:
                    raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目标识不唯一，不能判分", 409)
                aliases[alias] = ref
        resolved: dict[str, Any] = {}
        invalid = []
        duplicate = []
        for supplied_id, answer in submitted_answers.items():
            ref = aliases.get(supplied_id)
            if not ref:
                invalid.append(supplied_id)
                continue
            if ref.ref_id in resolved:
                duplicate.append(supplied_id)
                continue
            # Validate JSON determinism before a score fact is persisted.
            canonical_json(answer, error_code="TEACHING.ANSWER_VALUE_INVALID")
            resolved[ref.ref_id] = answer
        if invalid:
            raise ApiError("TEACHING.ANSWER_REFERENCE_INVALID", "作答包含不属于当前任务的题目标识", 422, {"question_ids": sorted(invalid)})
        if duplicate:
            raise ApiError("TEACHING.ANSWER_REFERENCE_DUPLICATE", "同一道冻结题目只能提交一次作答", 422, {"question_ids": sorted(duplicate)})
        return resolved

    def _score_frozen_answers(self, refs: list, submitted_answers: dict[str, Any]) -> tuple[Decimal, Decimal, dict[str, Any], list[dict], list[dict], list[dict]]:
        answers = self._resolve_answers(refs, submitted_answers)
        frozen_evidence: list[dict] = []
        answer_evidence: list[dict] = []
        scoring_evidence: list[dict] = []
        raw = Decimal("0")
        maximum = Decimal("0")
        required_snapshot_fields = {
            "contract", "question_id", "lesson_id", "question_type", "stem",
            "answer", "options", "reviewed_by", "reviewed_at", "question_version", "max_score",
        }
        for ref in refs:
            snapshot = ref.question_snapshot
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != required_snapshot_fields
                or snapshot.get("contract") != FROZEN_QUESTION_CONTRACT
                or snapshot.get("question_id") != ref.question_id
            ):
                raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目快照无效，不能判分", 409, {"question_ref_id": ref.ref_id})
            ref_max = Decimal(str(ref.max_score))
            if ref_max <= 0 or snapshot.get("max_score") != int(ref_max):
                raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目分值无效，不能判分", 409, {"question_ref_id": ref.ref_id})
            authoritative = {
                "question_id": snapshot["question_id"],
                "lesson_id": snapshot["lesson_id"],
                "question_type": snapshot["question_type"],
                "stem": snapshot["stem"],
                "answer": snapshot["answer"],
                "options": snapshot["options"],
                "reviewed_by": snapshot["reviewed_by"],
                "reviewed_at": snapshot["reviewed_at"],
            }
            expected_version = sha256_json(authoritative, error_code="TEACHING.FROZEN_QUESTION_INVALID")
            if snapshot.get("question_version") != expected_version or ref.question_version != expected_version:
                raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目版本摘要不匹配，不能判分", 409, {"question_ref_id": ref.ref_id})
            answer_present = ref.ref_id in answers
            answer = answers.get(ref.ref_id)
            awarded = ref_max if answer_present and self._answer_matches(snapshot, answer) else Decimal("0")
            raw += awarded
            maximum += ref_max
            frozen_evidence.append(
                {
                    "question_ref_id": ref.ref_id,
                    "question_id": ref.question_id,
                    "question_version": ref.question_version,
                    "question_snapshot": snapshot,
                    "max_score": canonical_score(ref_max),
                }
            )
            answer_evidence.append(
                {
                    "question_ref_id": ref.ref_id,
                    "question_id": ref.question_id,
                    "answer_present": answer_present,
                    "answer": answer if answer_present else None,
                }
            )
            scoring_evidence.append(
                {
                    "question_ref_id": ref.ref_id,
                    "question_id": ref.question_id,
                    "question_version": ref.question_version,
                    "awarded_score": canonical_score(awarded),
                    "max_score": canonical_score(ref_max),
                    "matched": bool(awarded),
                }
            )
        if not refs or maximum <= 0:
            raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "教学任务没有可判分的冻结题目", 409)
        return raw, maximum, answers, frozen_evidence, answer_evidence, scoring_evidence

    def _require_existing_score_proof(self, source_type: str, source_fact_id: str) -> None:
        """Do not return a legacy client-scored fact as a safe replay result."""

        proof = self.session.scalar(
            select(m.TeachingScoreProof).where(
                m.TeachingScoreProof.source_type == source_type,
                m.TeachingScoreProof.source_fact_id == source_fact_id,
            )
        )
        if not proof:
            raise ApiError(
                "TEACHING.LEGACY_SCORE_UNVERIFIED",
                "历史提交缺少服务端评分证明，不能作为可复核成绩继续使用",
                409,
                {"source_type": source_type, "source_fact_id": source_fact_id},
            )
        verify_teaching_score_proof(self.session, proof.proof_id)

    def _emit_server_score_proof(
        self,
        *,
        score_event_type: str,
        score_aggregate_id: str,
        source_type: str,
        source_fact_id: str,
        course_id: str,
        class_id: str,
        lesson_id: str | None,
        student_id: str,
        raw_score: Decimal,
        max_score: Decimal,
        frozen_evidence: list[dict],
        answer_evidence: list[dict],
        scoring_evidence: list[dict],
    ) -> tuple[str, str]:
        """Create paired, server-only proof and score events in one transaction.

        The proof event is timestamped one second ahead of the score event so
        the deterministic dispatcher order is proof -> score even after MySQL
        drops sub-second precision.  Both are still committed atomically with
        the source submission/attempt and A's own proof row.
        """

        evidence_type = "ASSIGNMENT_FROZEN_QUESTION_SET" if score_event_type == "assignment.submitted" else "QUIZ_FROZEN_QUESTION_SET"
        score_aggregate_type = "assignment" if score_event_type == "assignment.submitted" else "quiz"
        score_payload = {
            "course_id": course_id,
            "class_id": class_id,
            "lesson_id": lesson_id,
            "student_id": student_id,
            "source_id": source_fact_id,
            "raw_score": float(raw_score),
            "max_score": float(max_score),
        }
        score_event = enqueue_event(
            self.session,
            event_type=score_event_type,
            aggregate_type=score_aggregate_type,
            aggregate_id=score_aggregate_id,
            actor_user_id=self.user.user_id,
            idempotency_key=f"{score_aggregate_id}:{student_id}",
            payload={},
        )
        proof = {
            "contract": SCORE_PROOF_CONTRACT,
            "issuer": SCORE_PROOF_ISSUER,
            "origin": SCORE_PROOF_ORIGIN,
            "evidence_type": evidence_type,
            "source_event_id": score_event.event_id,
            "source_fact_id": source_fact_id,
            "frozen_question_count": len(frozen_evidence),
            "frozen_question_sha256": sha256_json(frozen_evidence),
            "answer_evidence_sha256": sha256_json(answer_evidence),
            "scoring_evidence_sha256": sha256_json(scoring_evidence),
        }
        proof["score_payload_sha256"] = score_payload_sha256(
            event_id=score_event.event_id,
            event_type=score_event_type,
            aggregate_id=score_aggregate_id,
            payload=score_payload,
            proof=proof,
            raw=raw_score,
            maximum=max_score,
        )
        proof_event = enqueue_event(
            self.session,
            event_type=SCORE_PROOF_EVENT_TYPE,
            aggregate_type=source_type,
            aggregate_id=source_fact_id,
            actor_user_id="service_teaching_score_prover",
            idempotency_key=f"score-proof:{source_type}:{source_fact_id}",
            payload={
                "score_event_id": score_event.event_id,
                "score_event_type": score_event_type,
                "score_aggregate_id": score_aggregate_id,
                "source_fact_id": source_fact_id,
                "course_id": course_id,
                "class_id": class_id,
                "lesson_id": lesson_id,
                "student_id": student_id,
                "raw_score": float(raw_score),
                "max_score": float(max_score),
                "source_proof": proof,
            },
        )
        # MySQL deployments without fractional DATETIME precision must still
        # observe a stable proof-before-score ordering.
        proof_occurred_at = datetime.now(timezone.utc).replace(microsecond=0)
        proof_event.occurred_at = proof_occurred_at
        score_event.occurred_at = proof_occurred_at + timedelta(seconds=1)
        score_event.payload_json = {**score_payload, "score_proof_event_id": proof_event.event_id}
        proof_row = m.TeachingScoreProof(
            proof_id=str(uuid4()),
            source_type=source_type,
            source_fact_id=source_fact_id,
            score_event_id=score_event.event_id,
            score_proof_event_id=proof_event.event_id,
            score_aggregate_id=score_aggregate_id,
            course_id=course_id,
            class_id=class_id,
            lesson_id=lesson_id,
            student_id=student_id,
            raw_score=raw_score,
            max_score=max_score,
            contract=proof["contract"],
            issuer=proof["issuer"],
            origin=proof["origin"],
            evidence_type=proof["evidence_type"],
            frozen_question_count=proof["frozen_question_count"],
            frozen_question_sha256=proof["frozen_question_sha256"],
            answer_evidence_sha256=proof["answer_evidence_sha256"],
            scoring_evidence_sha256=proof["scoring_evidence_sha256"],
            score_payload_sha256=proof["score_payload_sha256"],
            frozen_question_evidence_json=frozen_evidence,
            answer_evidence_json=answer_evidence,
            scoring_evidence_json=scoring_evidence,
            created_at=proof_occurred_at.replace(tzinfo=None),
        )
        self.repo.add(proof_row)
        # Catch a programming error or an in-transaction mutation before any
        # of the paired facts can be committed or dispatched to F.
        verify_teaching_score_proof(self.session, proof_row.proof_id)
        return proof_event.event_id, score_event.event_id

    def create_assignment(self, body: AssignmentCreate):
        self.require("teaching.assignment.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        self.require_lesson(body.course_id, body.lesson_id)
        item = self.repo.add(m.Assignment(assignment_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lesson_id=body.lesson_id, title=body.title, due_at=body.due_at, random_order=body.random_order, status="DRAFT", created_by=self.user.user_id))
        for question in self._freeze_published_questions(course_id=body.course_id, lesson_id=body.lesson_id, selections=body.questions):
            self.repo.add(m.AssignmentQuestionRef(ref_id=str(uuid4()), assignment_id=item.assignment_id, **question))
        self.audit("assignment.created", "assignment", item.assignment_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def publish_assignment(self, assignment_id: str):
        self.require("teaching.assignment.write"); item = self.repo.get(m.Assignment, assignment_id)
        if not item: raise ApiError("ASSIGNMENT.NOT_FOUND", "作业不存在", 404)
        self.require_class(item.class_id); item.status = "PUBLISHED"; self.audit("assignment.published", "assignment", assignment_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def _student_task_questions(self, source_kind: str, source_id: str) -> list[dict]:
        """Return a safe render projection of already frozen question facts.

        A question reference stores the full immutable evidence, including the
        answer key required for server scoring.  The browser must never receive
        that evidence or be able to send it back.  We still validate the full
        reference before projecting it so a corrupted snapshot fails closed
        instead of becoming a misleading student task.
        """

        refs = self._frozen_refs(source_kind, source_id, self.session)
        self._score_frozen_answers(refs, {})
        questions: list[dict] = []
        for ref in refs:
            snapshot = ref.question_snapshot
            options = snapshot.get("options")
            if not isinstance(options, list) or any(
                not isinstance(option, dict)
                or set(option) != {"key", "text"}
                or not isinstance(option["key"], str)
                or not isinstance(option["text"], str)
                for option in options
            ):
                raise ApiError("TEACHING.FROZEN_QUESTION_INVALID", "冻结题目选项无效，不能展示", 409, {"question_ref_id": ref.ref_id})
            questions.append(
                {
                    "question_ref_id": ref.ref_id,
                    "question_id": ref.question_id,
                    "question_type": snapshot["question_type"],
                    "stem": snapshot["stem"],
                    "options": [{"key": option["key"], "text": option["text"]} for option in options],
                }
            )
        return questions

    def student_assignments(self):
        self.require("teaching.assignment.submit"); student_id = self.require_student()
        items = []
        for assignment in self.repo.published_assignments(self.user.class_ids):
            self.require_course(assignment.course_id)
            membership = self.require_active_membership(assignment.class_id, student_id)
            if not membership:
                continue
            submission = self.repo.submission(assignment.assignment_id, student_id)
            items.append(
                {
                    "assignment_id": assignment.assignment_id,
                    "course_id": assignment.course_id,
                    "class_id": assignment.class_id,
                    "lesson_id": assignment.lesson_id,
                    "title": assignment.title,
                    "due_at": assignment.due_at,
                    "status": assignment.status,
                    "submission_status": submission.status if submission else None,
                }
            )
        return {"items": items}

    def student_assignment_task(self, assignment_id: str):
        self.require("teaching.assignment.submit"); student_id = self.require_student(); assignment = self.repo.get(m.Assignment, assignment_id)
        if not assignment or assignment.status != "PUBLISHED": raise ApiError("ASSIGNMENT.NOT_OPEN", "作业未发布", 409)
        self.require_course(assignment.course_id); self.require_class(assignment.class_id); self.require_active_membership(assignment.class_id, student_id)
        submission = self.repo.submission(assignment.assignment_id, student_id)
        return {
            "assignment_id": assignment.assignment_id,
            "course_id": assignment.course_id,
            "class_id": assignment.class_id,
            "lesson_id": assignment.lesson_id,
            "title": assignment.title,
            "due_at": assignment.due_at,
            "status": assignment.status,
            "submission_status": submission.status if submission else None,
            "questions": self._student_task_questions("assignment", assignment.assignment_id),
        }

    def submit_assignment(self, assignment_id: str, body: SubmissionIn):
        self.require("teaching.assignment.submit"); student_id = self.require_student(); item = self.repo.get(m.Assignment, assignment_id)
        if not item or item.status != "PUBLISHED": raise ApiError("ASSIGNMENT.NOT_OPEN", "作业未发布", 409)
        self.require_active_membership(item.class_id, student_id)
        if now() > item.due_at: raise ApiError("ASSIGNMENT.EXPIRED", "作业已截止", 409)
        previous = self.repo.submission(assignment_id, student_id)
        if previous:
            self._require_existing_score_proof("assignment_submission", previous.submission_id)
            return entity_dict(previous)
        refs = self._frozen_refs("assignment", assignment_id, self.session)
        raw_score, max_score, answers, frozen_evidence, answer_evidence, scoring_evidence = self._score_frozen_answers(refs, body.answers)
        sub = self.repo.add(m.AssignmentSubmission(submission_id=str(uuid4()), assignment_id=assignment_id, student_id=student_id, answers_json=answers, raw_score=raw_score, max_score=max_score, status="SUBMITTED", submitted_at=now()))
        self._emit_server_score_proof(score_event_type="assignment.submitted", score_aggregate_id=assignment_id, source_type="assignment_submission", source_fact_id=sub.submission_id, course_id=item.course_id, class_id=item.class_id, lesson_id=item.lesson_id, student_id=student_id, raw_score=raw_score, max_score=max_score, frozen_evidence=frozen_evidence, answer_evidence=answer_evidence, scoring_evidence=scoring_evidence)
        self.audit("assignment.submitted", "assignment_submission", sub.submission_id, {"course_id": item.course_id, "class_id": item.class_id, "student_id": student_id}); self.session.commit(); return entity_dict(sub)

    def create_quiz(self, body: QuizCreate):
        self.require("teaching.quiz.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        self.require_lesson(body.course_id, body.lesson_id)
        item = self.repo.add(m.Quiz(quiz_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lesson_id=body.lesson_id, title=body.title, time_limit_minutes=body.time_limit_minutes, random_order=body.random_order, status="DRAFT", created_by=self.user.user_id))
        for question in self._freeze_published_questions(course_id=body.course_id, lesson_id=body.lesson_id, selections=body.questions):
            self.repo.add(m.QuizQuestionRef(ref_id=str(uuid4()), quiz_id=item.quiz_id, **question))
        self.audit("quiz.created", "quiz", item.quiz_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def publish_quiz(self, quiz_id: str):
        self.require("teaching.quiz.write"); quiz = self.repo.get(m.Quiz, quiz_id)
        if not quiz: raise ApiError("QUIZ.NOT_FOUND", "测验不存在", 404)
        self.require_class(quiz.class_id); quiz.status = "PUBLISHED"; self.audit("quiz.published", "quiz", quiz_id, {"course_id": quiz.course_id, "class_id": quiz.class_id}); self.session.commit(); return entity_dict(quiz)

    def student_quizzes(self):
        self.require("teaching.quiz.submit"); student_id = self.require_student()
        items = []
        for quiz in self.repo.published_quizzes(self.user.class_ids):
            self.require_course(quiz.course_id)
            membership = self.require_active_membership(quiz.class_id, student_id)
            if not membership:
                continue
            attempt = self.repo.attempt(quiz.quiz_id, student_id)
            items.append(
                {
                    "quiz_id": quiz.quiz_id,
                    "course_id": quiz.course_id,
                    "class_id": quiz.class_id,
                    "lesson_id": quiz.lesson_id,
                    "title": quiz.title,
                    "time_limit_minutes": quiz.time_limit_minutes,
                    "status": quiz.status,
                    "attempt_status": attempt.status if attempt else None,
                }
            )
        return {"items": items}

    def student_quiz_task(self, quiz_id: str):
        self.require("teaching.quiz.submit"); student_id = self.require_student(); quiz = self.repo.get(m.Quiz, quiz_id)
        if not quiz or quiz.status != "PUBLISHED": raise ApiError("QUIZ.NOT_OPEN", "测验未发布", 409)
        self.require_course(quiz.course_id); self.require_class(quiz.class_id); self.require_active_membership(quiz.class_id, student_id)
        attempt = self.repo.attempt(quiz.quiz_id, student_id)
        return {
            "quiz_id": quiz.quiz_id,
            "course_id": quiz.course_id,
            "class_id": quiz.class_id,
            "lesson_id": quiz.lesson_id,
            "title": quiz.title,
            "time_limit_minutes": quiz.time_limit_minutes,
            "status": quiz.status,
            "attempt_status": attempt.status if attempt else None,
            "questions": self._student_task_questions("quiz", quiz.quiz_id),
        }

    def start_quiz(self, quiz_id: str):
        self.require("teaching.quiz.submit"); student_id = self.require_student(); quiz = self.repo.get(m.Quiz, quiz_id)
        if not quiz or quiz.status != "PUBLISHED": raise ApiError("QUIZ.NOT_OPEN", "测验未发布", 409)
        self.require_active_membership(quiz.class_id, student_id)
        previous = self.repo.attempt(quiz_id, student_id)
        if previous: return entity_dict(previous)
        attempt = self.repo.add(m.QuizAttempt(attempt_id=str(uuid4()), quiz_id=quiz_id, student_id=student_id, status="DRAFT", started_at=now(), submitted_at=None, raw_score=None, max_score=None)); self.session.commit(); return entity_dict(attempt)

    def submit_quiz(self, quiz_id: str, attempt_id: str, body: QuizSubmitIn):
        self.require("teaching.quiz.submit"); student_id = self.require_student(); quiz = self.repo.get(m.Quiz, quiz_id); attempt = self.repo.get(m.QuizAttempt, attempt_id)
        if not quiz or not attempt or attempt.quiz_id != quiz_id: raise ApiError("QUIZ.ATTEMPT_NOT_FOUND", "作答不存在", 404)
        if attempt.student_id != student_id: raise ApiError("AUTH.SCOPE_DENIED", "不能提交他人的测验", 403)
        self.require_active_membership(quiz.class_id, student_id)
        if attempt.status == "SUBMITTED":
            self._require_existing_score_proof("quiz_attempt", attempt.attempt_id)
            return entity_dict(attempt)
        if (now() - attempt.started_at).total_seconds() > quiz.time_limit_minutes * 60: raise ApiError("QUIZ.EXPIRED", "测验已超时", 409)
        refs = self._frozen_refs("quiz", quiz_id, self.session)
        raw_score, max_score, answers, frozen_evidence, answer_evidence, scoring_evidence = self._score_frozen_answers(refs, body.answers)
        attempt.status = "SUBMITTED"; attempt.submitted_at = now(); attempt.raw_score = raw_score; attempt.max_score = max_score
        scoring_by_ref = {item["question_ref_id"]: Decimal(item["awarded_score"]) for item in scoring_evidence}
        for ref_id, answer in answers.items():
            self.repo.add(m.QuizAnswer(answer_id=str(uuid4()), attempt_id=attempt_id, question_ref_id=ref_id, answer_json={"value": answer}, score=scoring_by_ref[ref_id]))
        self._emit_server_score_proof(score_event_type="quiz.completed", score_aggregate_id=quiz_id, source_type="quiz_attempt", source_fact_id=attempt_id, course_id=quiz.course_id, class_id=quiz.class_id, lesson_id=quiz.lesson_id, student_id=student_id, raw_score=raw_score, max_score=max_score, frozen_evidence=frozen_evidence, answer_evidence=answer_evidence, scoring_evidence=scoring_evidence)
        self.audit("quiz.completed", "quiz_attempt", attempt_id, {"course_id": quiz.course_id, "class_id": quiz.class_id, "student_id": student_id}); self.session.commit(); return entity_dict(attempt)
