import hashlib
import json
import secrets
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event

from . import models as m
from .repository import TeachingRepository
from .schemas import AssignmentCreate, AttendanceCreate, ClassCreate, CourseCreate, CoursePatch, MemberCreate, PollCreate, QuizCreate, QuizSubmitIn, SubmissionIn
from .xlsx import parse_members


def now() -> datetime:
    return datetime.utcnow()


def entity_dict(entity) -> dict:
    return {column.name: getattr(entity, column.name) for column in entity.__table__.columns}


class TeachingService:
    def __init__(self, session: Session, user: UserContext):
        self.session, self.user, self.repo = session, user, TeachingRepository(session)

    def require(self, permission: str):
        if permission not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "没有执行此操作的权限", 403)

    def require_course(self, course_id: str):
        if course_id not in self.user.course_ids:
            raise ApiError("AUTH.SCOPE_DENIED", "不能访问该课程", 403)

    def require_class(self, class_id: str):
        if class_id not in self.user.class_ids:
            raise ApiError("AUTH.SCOPE_DENIED", "不能访问该班级", 403)

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

    def create_course(self, body: CourseCreate):
        self.require("teaching.course.write")
        if not self.user.teacher_id:
            raise ApiError("AUTH.TEACHER_REQUIRED", "当前身份没有关联教师", 403)
        item = self.repo.add(m.Course(course_id=str(uuid4()), owner_teacher_id=self.user.teacher_id, created_at=now(), status="DRAFT", **body.model_dump()))
        self.audit("course.created", "course", item.course_id, {"course_id": item.course_id})
        self.session.commit()
        return entity_dict(item)

    def list_courses(self):
        self.require("teaching.course.read")
        items = self.repo.list_courses(self.user.course_ids)
        return {"items": [entity_dict(x) for x in items], "page": 1, "page_size": len(items), "total": len(items)}

    def get_course(self, course_id: str):
        self.require("teaching.course.read"); self.require_course(course_id)
        item = self.repo.get(m.Course, course_id)
        if not item:
            raise ApiError("COURSE.NOT_FOUND", "课程不存在", 404)
        return entity_dict(item)

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

    def add_member(self, class_id: str, body: MemberCreate):
        self.require("teaching.members.write"); self.require_class(class_id)
        self.require_mutable_roster(class_id)
        existing = self.repo.membership_by_number(class_id, body.student_number)
        if existing:
            if existing.student_id != body.student_id: raise ApiError("MEMBER.NUMBER_CONFLICT", "学号已被班级内其他学生使用", 409)
            existing.status = "ACTIVE"; existing.student_name = body.student_name; existing.phone = body.phone; existing.email = body.email
            item = existing
        else:
            item = self.repo.add(m.ClassMembership(class_membership_id=str(uuid4()), class_id=class_id, status="ACTIVE", joined_at=now(), **body.model_dump()))
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
            if existing and existing.status == "ACTIVE":
                duplicate_count += 1
                errors.append({**item, "reason": "该学号已在班级中"})
                continue
            student_id = str(uuid5(NAMESPACE_URL, f"yueke:{class_id}:{item['student_number']}"))
            if existing:
                existing.status = "ACTIVE"; existing.student_name = item["student_name"]; existing.phone = item["phone"] or None; existing.email = item["email"] or None
            else:
                self.repo.add(m.ClassMembership(class_membership_id=str(uuid4()), class_id=class_id, student_id=student_id, student_number=item["student_number"], student_name=item["student_name"], phone=item["phone"] or None, email=item["email"] or None, status="ACTIVE", joined_at=now()))
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

    def create_assignment(self, body: AssignmentCreate):
        self.require("teaching.assignment.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        item = self.repo.add(m.Assignment(assignment_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lesson_id=body.lesson_id, title=body.title, due_at=body.due_at, random_order=body.random_order, status="DRAFT", created_by=self.user.user_id))
        for q in body.questions: self.repo.add(m.AssignmentQuestionRef(ref_id=str(uuid4()), assignment_id=item.assignment_id, **q.model_dump()))
        self.audit("assignment.created", "assignment", item.assignment_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def publish_assignment(self, assignment_id: str):
        self.require("teaching.assignment.write"); item = self.repo.get(m.Assignment, assignment_id)
        if not item: raise ApiError("ASSIGNMENT.NOT_FOUND", "作业不存在", 404)
        self.require_class(item.class_id); item.status = "PUBLISHED"; self.audit("assignment.published", "assignment", assignment_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def submit_assignment(self, assignment_id: str, body: SubmissionIn):
        self.require("teaching.assignment.submit"); student_id = self.require_student(); item = self.repo.get(m.Assignment, assignment_id)
        if not item or item.status != "PUBLISHED": raise ApiError("ASSIGNMENT.NOT_OPEN", "作业未发布", 409)
        self.require_active_membership(item.class_id, student_id)
        if now() > item.due_at: raise ApiError("ASSIGNMENT.EXPIRED", "作业已截止", 409)
        previous = self.repo.submission(assignment_id, student_id)
        if previous: return entity_dict(previous)
        sub = self.repo.add(m.AssignmentSubmission(submission_id=str(uuid4()), assignment_id=assignment_id, student_id=student_id, answers_json=body.answers, raw_score=body.raw_score, max_score=body.max_score, status="SUBMITTED", submitted_at=now()))
        enqueue_event(self.session, event_type="assignment.submitted", aggregate_type="assignment", aggregate_id=assignment_id, actor_user_id=self.user.user_id, idempotency_key=f"{assignment_id}:{student_id}", payload={"course_id": item.course_id, "class_id": item.class_id, "lesson_id": item.lesson_id, "student_id": student_id, "source_id": sub.submission_id, "raw_score": body.raw_score, "max_score": body.max_score})
        self.audit("assignment.submitted", "assignment_submission", sub.submission_id, {"course_id": item.course_id, "class_id": item.class_id, "student_id": student_id}); self.session.commit(); return entity_dict(sub)

    def create_quiz(self, body: QuizCreate):
        self.require("teaching.quiz.write"); self.require_course(body.course_id); self.require_class(body.class_id)
        item = self.repo.add(m.Quiz(quiz_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lesson_id=body.lesson_id, title=body.title, time_limit_minutes=body.time_limit_minutes, random_order=body.random_order, status="DRAFT", created_by=self.user.user_id))
        for q in body.questions: self.repo.add(m.QuizQuestionRef(ref_id=str(uuid4()), quiz_id=item.quiz_id, **q.model_dump()))
        self.audit("quiz.created", "quiz", item.quiz_id, {"course_id": item.course_id, "class_id": item.class_id}); self.session.commit(); return entity_dict(item)

    def publish_quiz(self, quiz_id: str):
        self.require("teaching.quiz.write"); quiz = self.repo.get(m.Quiz, quiz_id)
        if not quiz: raise ApiError("QUIZ.NOT_FOUND", "测验不存在", 404)
        self.require_class(quiz.class_id); quiz.status = "PUBLISHED"; self.audit("quiz.published", "quiz", quiz_id, {"course_id": quiz.course_id, "class_id": quiz.class_id}); self.session.commit(); return entity_dict(quiz)

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
        if attempt.status == "SUBMITTED": return entity_dict(attempt)
        if (now() - attempt.started_at).total_seconds() > quiz.time_limit_minutes * 60: raise ApiError("QUIZ.EXPIRED", "测验已超时", 409)
        attempt.status = "SUBMITTED"; attempt.submitted_at = now(); attempt.raw_score = body.raw_score; attempt.max_score = body.max_score
        refs = {x.ref_id: x for x in self.session.query(m.QuizQuestionRef).filter_by(quiz_id=quiz_id)}
        for ref_id, answer in body.answers.items():
            if ref_id in refs: self.repo.add(m.QuizAnswer(answer_id=str(uuid4()), attempt_id=attempt_id, question_ref_id=ref_id, answer_json={"value": answer}, score=0))
        enqueue_event(self.session, event_type="quiz.completed", aggregate_type="quiz", aggregate_id=quiz_id, actor_user_id=self.user.user_id, idempotency_key=f"{quiz_id}:{student_id}", payload={"course_id": quiz.course_id, "class_id": quiz.class_id, "lesson_id": quiz.lesson_id, "student_id": student_id, "source_id": attempt_id, "raw_score": body.raw_score, "max_score": body.max_score})
        self.audit("quiz.completed", "quiz_attempt", attempt_id, {"course_id": quiz.course_id, "class_id": quiz.class_id, "student_id": student_id}); self.session.commit(); return entity_dict(attempt)
