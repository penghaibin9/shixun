from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import FileObject
from app.common.outbox import enqueue_event

from .models import (AnalyticsCourseSummary, AnalyticsLabSummary, AnalyticsSectionSummary, AnalyticsStudentLabSummary,
                     AuditEvent, CourseArchive, CourseArchiveArtifact, GradeEvent, Gradebook, GradebookItem,
                     GradingPolicy, GradingPolicyItem, StudentCourseScore, StudentRiskFlag)
from .repository import GradingRepository

COMPONENTS = ["ATTENDANCE", "ASSIGNMENT", "QUIZ", "LAB", "INTERACTION"]
DEFAULT_WEIGHTS = {"ATTENDANCE": Decimal("10"), "ASSIGNMENT": Decimal("20"), "QUIZ": Decimal("20"), "LAB": Decimal("40"), "INTERACTION": Decimal("10")}
EVENT_TYPES = {
    "attendance.completed": "ATTENDANCE", "assignment.submitted": "ASSIGNMENT", "quiz.completed": "QUIZ",
    "lab.checkpoint.passed": "LAB_CHECKPOINT", "lab.checkpoint.failed": "LAB_CHECKPOINT",
    "lab.submitted": "LAB_SUBMISSION", "poll.completed": "INTERACTION", "grade.manual.adjusted": "MANUAL_ADJUSTMENT",
}


def utcnow(): return datetime.utcnow()
def number(value): return float(value) if value is not None else None


class GradingService:
    def __init__(self, session: Session, user: UserContext, request_id: str = "system", ip: str = "local"):
        self.session, self.user, self.repo = session, user, GradingRepository(session)
        self.request_id, self.ip = request_id, ip

    def authorize(self, course_id: str, permission: str, class_id: str | None = None, student_id: str | None = None):
        if course_id not in self.user.course_ids and "grading:all-courses" not in self.user.permissions:
            raise ApiError("GRADING.COURSE_SCOPE_DENIED", "无权访问该课程成绩", 403)
        if class_id and class_id not in self.user.class_ids and "grading:all-classes" not in self.user.permissions:
            raise ApiError("GRADING.CLASS_SCOPE_DENIED", "无权访问该班级成绩", 403)
        if student_id and self.user.role == "student" and student_id != self.user.student_id:
            raise ApiError("GRADING.STUDENT_SCOPE_DENIED", "学生只能查看本人数据", 403)
        if permission not in self.user.permissions and "grading:manage" not in self.user.permissions:
            raise ApiError("AUTH.PERMISSION_DENIED", "缺少成绩操作权限", 403)

    def audit(self, action: str, resource_type: str, resource_id: str, *, result="SUCCESS", reason=None, course_id=None, class_id=None, student_id=None, details=None):
        event = AuditEvent(audit_event_id=str(uuid4()), source_event_id=None, actor_user_id=self.user.user_id, actor_role=self.user.role, action=action, resource_type=resource_type, resource_id=resource_id, course_id=course_id, class_id=class_id, student_id=student_id, request_id=self.request_id, ip=self.ip, result=result, reason=reason, occurred_at=utcnow(), details_json=details or {})
        self.repo.add(event); return event

    def ingest_audit(self, data) -> dict:
        if "audit:ingest" not in self.user.permissions and "grading:manage" not in self.user.permissions: raise ApiError("AUTH.PERMISSION_DENIED", "缺少跨域审计写入权限", 403)
        existing=self.session.scalar(select(AuditEvent).where(AuditEvent.source_event_id==data.source_event_id))
        if existing:return {"status":"DUPLICATE","audit_event_id":existing.audit_event_id}
        row=AuditEvent(audit_event_id=str(uuid4()),source_event_id=data.source_event_id,actor_user_id=data.actor_user_id,actor_role=data.actor_role,action=data.action,resource_type=data.resource_type,resource_id=data.resource_id,course_id=data.course_id,class_id=data.class_id,student_id=data.student_id,request_id=self.request_id,ip=self.ip,result=data.result,reason=data.reason,occurred_at=data.occurred_at.replace(tzinfo=None),details_json=data.details)
        self.repo.add(row);self.session.commit();return {"status":"RECORDED","audit_event_id":row.audit_event_id}

    def get_policy(self, course_id: str) -> dict:
        self.authorize(course_id, "grading:read")
        policy = self.repo.policy(course_id)
        if not policy: return {"course_id": course_id, "status": "PENDING", "version_no": None, "items": []}
        return self.policy_dict(policy)

    def put_policy(self, course_id: str, values: dict, effective_at=None) -> dict:
        self.authorize(course_id, "grading:policy")
        weights = {key.upper(): Decimal(str(value)) for key, value in values.items()}
        if set(weights) != set(COMPONENTS) or sum(weights.values()) != Decimal("100"):
            raise ApiError("GRADING.POLICY_WEIGHT_INVALID", "成绩权重合计必须为 100%", 422, {"total": float(sum(weights.values()))})
        latest = self.repo.policy(course_id); version = latest.version_no + 1 if latest else 1
        policy = GradingPolicy(grading_policy_id=str(uuid4()), course_id=course_id, version_no=version, status="PUBLISHED", effective_at=effective_at or utcnow(), created_by=self.user.user_id, created_at=utcnow())
        self.repo.add(policy)
        for component, weight in weights.items(): self.repo.add(GradingPolicyItem(grading_policy_item_id=str(uuid4()), grading_policy_id=policy.grading_policy_id, component=component, weight_percent=weight))
        self.audit("GRADING_POLICY_PUBLISHED", "grading_policy", policy.grading_policy_id, course_id=course_id, details={"version_no": version, "weights": {k: float(v) for k,v in weights.items()}})
        self.session.commit(); return self.policy_dict(policy)

    def ensure_policy(self, course_id: str) -> GradingPolicy:
        policy = self.repo.policy(course_id)
        if policy: return policy
        policy = GradingPolicy(grading_policy_id=str(uuid4()), course_id=course_id, version_no=1, status="PUBLISHED", effective_at=utcnow(), created_by=self.user.user_id, created_at=utcnow())
        self.repo.add(policy)
        for component, weight in DEFAULT_WEIGHTS.items(): self.repo.add(GradingPolicyItem(grading_policy_item_id=str(uuid4()), grading_policy_id=policy.grading_policy_id, component=component, weight_percent=weight))
        self.session.flush(); return policy

    def consume(self, envelope) -> dict:
        if "grading:consume" not in self.user.permissions and "grading:manage" not in self.user.permissions:
            raise ApiError("AUTH.PERMISSION_DENIED", "缺少事实消费权限", 403)
        existing = self.session.scalar(select(GradeEvent).where(GradeEvent.event_id == envelope.event_id))
        if existing: return {"status": "DUPLICATE", "grade_event_id": existing.grade_event_id, "event_id": envelope.event_id}
        rejected=self.session.scalar(select(AuditEvent).where(AuditEvent.source_event_id==envelope.event_id,AuditEvent.action=="GRADE_EVENT_REJECTED"))
        if rejected: raise ApiError(rejected.details_json["code"],rejected.reason or "成绩事件已拒绝",422,rejected.details_json.get("details",{}))
        payload = envelope.payload
        if envelope.event_type not in EVENT_TYPES:
            if envelope.event_type in {"resource.delivery.frozen", "course.roster.frozen"}:
                action = "UPSTREAM.RESOURCE_DELIVERY_FROZEN" if envelope.event_type.startswith("resource") else "UPSTREAM.COURSE_ROSTER_FROZEN"
                existing_audit=self.session.scalar(select(AuditEvent).where(AuditEvent.source_event_id==envelope.event_id))
                if existing_audit:return {"status":"DUPLICATE","event_id":envelope.event_id}
                self.repo.add(AuditEvent(audit_event_id=str(uuid4()),source_event_id=envelope.event_id,actor_user_id=envelope.actor_user_id,actor_role="service",action=action,resource_type=envelope.aggregate_type,resource_id=envelope.aggregate_id,course_id=payload.get("course_id"),class_id=payload.get("class_id"),student_id=None,request_id=self.request_id,ip=self.ip,result="SUCCESS",reason=None,occurred_at=envelope.occurred_at.replace(tzinfo=None),details_json={"payload":payload}))
                self.session.commit(); return {"status": "RECORDED", "event_id": envelope.event_id}
            self.reject_envelope(envelope,"GRADING.EVENT_TYPE_UNSUPPORTED","该事件不属于成绩事实来源",{})
        required = ["course_id", "class_id", "student_id", "source_id", "raw_score", "max_score"]
        missing = [key for key in required if payload.get(key) is None]
        if missing:self.reject_envelope(envelope,"GRADING.EVENT_PAYLOAD_INVALID","上游事件缺少成绩字段",{"missing":missing})
        raw, maximum = Decimal(str(payload["raw_score"])), Decimal(str(payload["max_score"]))
        if maximum <= 0 or raw < 0 or raw > maximum:self.reject_envelope(envelope,"GRADING.SCORE_INVALID","原始分数必须在有效范围内",{})
        grade = GradeEvent(grade_event_id=str(uuid4()), course_id=payload["course_id"], class_id=payload["class_id"], lesson_id=payload.get("lesson_id"), student_id=payload["student_id"], source_type=EVENT_TYPES[envelope.event_type], source_id=payload["source_id"], raw_score=raw, max_score=maximum, normalized_score=(raw/maximum*100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), occurred_at=envelope.occurred_at.replace(tzinfo=None), event_id=envelope.event_id, status="CONSUMED", payload_json={**payload,"source_event_type":envelope.event_type})
        self.repo.add(grade)
        if grade.source_type == "MANUAL_ADJUSTMENT": self.audit("GRADE_MANUAL_ADJUSTMENT", "grade_event", grade.grade_event_id, course_id=grade.course_id, class_id=grade.class_id, student_id=grade.student_id, details={"source_id": grade.source_id, "normalized_score": number(grade.normalized_score)})
        enqueue_event(self.session, event_type="grade.event.created", aggregate_type="grade_event", aggregate_id=grade.grade_event_id, actor_user_id=self.user.user_id, idempotency_key=f"grade-event:{envelope.event_id}", payload={"course_id":grade.course_id,"class_id":grade.class_id,"student_id":grade.student_id,"source_type":grade.source_type})
        self.session.commit(); return {"status": "CONSUMED", "grade_event_id": grade.grade_event_id, "event_id": envelope.event_id}

    def reject_envelope(self,envelope,code,message,details):
        payload=envelope.payload
        self.repo.add(AuditEvent(audit_event_id=str(uuid4()),source_event_id=envelope.event_id,actor_user_id=envelope.actor_user_id,actor_role="service",action="GRADE_EVENT_REJECTED",resource_type=envelope.aggregate_type,resource_id=envelope.aggregate_id,course_id=payload.get("course_id"),class_id=payload.get("class_id"),student_id=payload.get("student_id"),request_id=self.request_id,ip=self.ip,result="ERROR",reason=message,occurred_at=utcnow(),details_json={"code":code,"details":details,"event_type":envelope.event_type}))
        self.session.commit();raise ApiError(code,message,422,details)

    def recalculate(self, course_id: str, class_id: str) -> dict:
        self.authorize(course_id, "grading:recalculate", class_id)
        archived = self.repo.archive(course_id, class_id)
        if archived and archived.status == "ARCHIVED": raise ApiError("ARCHIVE.GRADEBOOK_LOCKED", "课程已归档，不能静默重算成绩", 409)
        policy = self.ensure_policy(course_id); weights = {x.component: Decimal(x.weight_percent) for x in self.repo.policy_items(policy.grading_policy_id)}
        events = self.repo.grade_events(course_id, class_id)
        if not events: raise ApiError("GRADING.SOURCE_FACTS_PENDING", "尚未收到 A/D/E 上游成绩事实", 409)
        book = self.repo.gradebook(course_id, class_id)
        if book and book.policy_version == policy.version_no and book.status in {"POSTED","LOCKED"}: raise ApiError("GRADING.GRADEBOOK_LOCKED", "成绩已入账或归档；请发布新规则版本后重算", 409)
        if book and book.policy_version == policy.version_no:
            for model in [StudentRiskFlag, AnalyticsLabSummary, AnalyticsStudentLabSummary, AnalyticsSectionSummary, AnalyticsCourseSummary, StudentCourseScore, GradebookItem]: self.session.execute(delete(model).where(model.gradebook_id == book.gradebook_id))
            book.status, book.calculated_at = "CALCULATING", utcnow()
        else:
            book = Gradebook(gradebook_id=str(uuid4()), course_id=course_id, class_id=class_id, policy_version=policy.version_no, status="CALCULATING", calculated_at=utcnow(), posted_at=None, locked_at=None); self.repo.add(book); self.session.flush()
        by_student = defaultdict(list)
        for event in events: by_student[event.student_id].append(event)
        rankings=[]
        for student_id, student_events in by_student.items():
            grouped=defaultdict(list)
            for event in student_events: grouped[self.component(event.source_type)].append(Decimal(event.normalized_score))
            total=Decimal("0"); present=[]
            for component in COMPONENTS:
                scores=grouped.get(component,[]); score=(sum(scores)/len(scores)).quantize(Decimal("0.01")) if scores else Decimal("0")
                if scores: present.append(component)
                weighted=(score*weights[component]/100).quantize(Decimal("0.01")); total+=weighted
                self.repo.add(GradebookItem(gradebook_item_id=str(uuid4()),gradebook_id=book.gradebook_id,student_id=student_id,component=component,component_score=score,weight_percent=weights[component],weighted_score=weighted))
            adjustments=sum((Decimal(e.normalized_score) for e in student_events if e.source_type=="MANUAL_ADJUSTMENT"),Decimal("0"))
            total=max(Decimal("0"),min(Decimal("100"),total+adjustments)).quantize(Decimal("0.01")); completeness="READY" if set(present)==set(COMPONENTS) else "PARTIAL"
            self.repo.add(StudentCourseScore(student_course_score_id=str(uuid4()),gradebook_id=book.gradebook_id,course_id=course_id,class_id=class_id,student_id=student_id,total_score=total,completeness=completeness));rankings.append({"student_id":student_id,"total_score":float(total),"completeness":completeness})
            self.build_risks(book, student_id, grouped, total, present, student_events, events)
        rankings.sort(key=lambda x:x["total_score"],reverse=True)
        component_avg={c: self.average([next((i.component_score for i in self.repo.items(book.gradebook_id,s) if i.component==c),Decimal("0")) for s in by_student]) for c in COMPONENTS}
        summary={"status":"READY" if all(x["completeness"]=="READY" for x in rankings) else "PARTIAL","student_count":len(rankings),"avg_assignment":component_avg["ASSIGNMENT"],"avg_quiz":component_avg["QUIZ"],"attendance_rate":component_avg["ATTENDANCE"],"course_average":self.average([Decimal(str(x["total_score"])) for x in rankings]),"ranking":rankings}
        self.repo.add(AnalyticsCourseSummary(analytics_course_summary_id=str(uuid4()),gradebook_id=book.gradebook_id,course_id=course_id,class_id=class_id,summary_json=summary,calculated_at=utcnow()))
        self.build_section_analytics(book,events); self.build_lab_analytics(book,events,len(by_student)); book.status="READY"; book.calculated_at=utcnow()
        self.audit("GRADEBOOK_RECALCULATED","gradebook",book.gradebook_id,course_id=course_id,class_id=class_id,details={"policy_version":policy.version_no,"source_event_count":len(events),"status":summary["status"]})
        self.session.commit(); return self.gradebook_dict(book)

    def post(self, course_id: str) -> dict:
        self.authorize(course_id,"grading:post")
        book=self.repo.gradebook(course_id)
        if book and book.status=="POSTED": return self.gradebook_dict(book)
        if not book or book.status!="READY": raise ApiError("GRADING.GRADEBOOK_NOT_READY","只有已重算成绩册可以入账",409)
        self.authorize(course_id,"grading:post",book.class_id)
        book.status="POSTED";book.posted_at=utcnow();self.audit("GRADEBOOK_POSTED","gradebook",book.gradebook_id,course_id=course_id,class_id=book.class_id)
        enqueue_event(self.session,event_type="gradebook.posted",aggregate_type="gradebook",aggregate_id=book.gradebook_id,actor_user_id=self.user.user_id,idempotency_key=f"gradebook-posted:{book.gradebook_id}",payload={"course_id":course_id,"class_id":book.class_id,"policy_version":book.policy_version})
        self.session.commit();return self.gradebook_dict(book)

    def gradebook(self, course_id: str, student_id: str | None = None) -> dict:
        if self.user.role == "student":
            if student_id and student_id != self.user.student_id: raise ApiError("GRADING.STUDENT_SCOPE_DENIED", "学生只能查看本人数据", 403)
            student_id = self.user.student_id
        self.authorize(course_id,"grading:read",student_id=student_id)
        book=self.repo.gradebook(course_id)
        if not book:return {"course_id":course_id,"status":"PENDING","items":[]}
        self.authorize(course_id,"grading:read",book.class_id,student_id)
        scores=self.repo.scores(book.gradebook_id)
        if student_id:scores=[x for x in scores if x.student_id==student_id]
        return {**self.gradebook_dict(book),"items":[{"student_id":x.student_id,"total_score":number(x.total_score),"completeness":x.completeness} for x in scores]}

    def trace(self, course_id: str, student_id: str) -> dict:
        self.authorize(course_id,"grading:read",student_id=student_id);book=self.repo.gradebook(course_id)
        if not book:return {"status":"PENDING","student_id":student_id,"sources":[]}
        self.authorize(course_id,"grading:read",book.class_id,student_id)
        score=next((x for x in self.repo.scores(book.gradebook_id) if x.student_id==student_id),None)
        events=self.repo.grade_events(course_id,book.class_id,student_id); items=self.repo.items(book.gradebook_id,student_id)
        return {"status":book.status,"student_id":student_id,"total_score":number(score.total_score) if score else None,"policy_version":book.policy_version,"components":[{"component":x.component,"score":number(x.component_score),"weight_percent":number(x.weight_percent),"weighted_score":number(x.weighted_score),"sources":[self.event_dict(e) for e in events if self.component(e.source_type)==x.component]} for x in items]}

    def overview(self,course_id):
        self.authorize(course_id,"analytics:class");book=self.repo.gradebook(course_id)
        if not book:return {"course_id":course_id,"status":"PENDING","reason":"等待上游成绩事实与重算"}
        self.authorize(course_id,"analytics:class",book.class_id)
        row=self.repo.course_summary(book.gradebook_id);return row.summary_json if row else {"course_id":course_id,"status":"PENDING"}
    def section(self,course_id,lesson_id):
        self.authorize(course_id,"analytics:class");book=self.repo.gradebook(course_id);row=self.repo.section_summary(book.gradebook_id,lesson_id) if book else None
        if book:self.authorize(course_id,"analytics:class",book.class_id)
        return row.summary_json if row else {"course_id":course_id,"lesson_id":lesson_id,"status":"PENDING"}
    def labs_by_student(self,course_id):
        self.authorize(course_id,"analytics:class");book=self.repo.gradebook(course_id)
        if book:self.authorize(course_id,"analytics:class",book.class_id)
        return {"status":"PENDING","items":[]} if not book else {"status":"READY","items":[{"student_id":x.student_id,"sum_lab_score":number(x.sum_lab_score),"submitted_count":x.submitted_count,"unsubmitted_count":x.unsubmitted_count} for x in self.repo.student_lab_summaries(book.gradebook_id)]}
    def labs_by_lab(self,course_id):
        self.authorize(course_id,"analytics:class");book=self.repo.gradebook(course_id)
        if book:self.authorize(course_id,"analytics:class",book.class_id)
        return {"status":"PENDING","items":[]} if not book else {"status":"READY","items":[{"lab_release_id":x.lab_release_id,"max_score":number(x.max_score),"submitted_students":x.submitted_students,"unsubmitted_students":x.unsubmitted_students,"avg_score":number(x.avg_score)} for x in self.repo.lab_summaries(book.gradebook_id)]}
    def risks(self,course_id,student_id=None):
        self.authorize(course_id,"analytics:read",student_id=student_id);rows=self.repo.risks(course_id,student_id)
        return {"status":"READY" if self.repo.gradebook(course_id) else "PENDING","items":[{"student_id":x.student_id,"risk_type":x.risk_type,"evidence":x.evidence_json,"status":x.status} for x in rows]}

    def learning_summary(self,course_id,student_id=None):
        if self.user.role == "student":student_id=self.user.student_id
        self.authorize(course_id,"analytics:read",student_id=student_id);gradebook_row=self.repo.gradebook(course_id)
        summary_row=self.repo.course_summary(gradebook_row.gradebook_id) if gradebook_row else None;overview=dict(summary_row.summary_json) if summary_row else {"status":"PENDING"}
        if student_id and overview.get("ranking"):
            rank=next((i+1 for i,x in enumerate(overview["ranking"]) if x["student_id"]==student_id),None);overview.pop("ranking",None);overview["student_rank"]=rank
        book=self.gradebook(course_id,student_id);risks=self.risks(course_id,student_id)
        states=[overview.get("status","PENDING"),book.get("status","PENDING"),risks.get("status","PENDING")]
        status="PENDING" if all(x=="PENDING" for x in states) else ("READY" if overview.get("status")=="READY" and book.get("status") in {"POSTED","LOCKED"} else "PARTIAL")
        return {"course_id":course_id,"student_id":student_id,"status":status,"grade":book,"risk":risks,"analytics":overview,"missing_upstream":[] if status=="READY" else ["上游班级成员/完整教学事实或成绩入账尚未就绪"]}

    def precheck(self,course_id,class_id):
        self.authorize(course_id,"archives:write",class_id);book=self.repo.gradebook(course_id,class_id);audits=self.repo.audit_events(course_id=course_id)
        actions={x.action for x in audits};events=self.repo.grade_events(course_id,class_id)
        checks={"roster_frozen":"UPSTREAM.COURSE_ROSTER_FROZEN" in actions,"gradebook_posted":bool(book and book.status=="POSTED"),"grade_event_traceable":bool(events) and all(x.event_id and x.source_id for x in events),"lab_evidence_referenced":any(x.source_type in {"LAB_CHECKPOINT","LAB_SUBMISSION"} for x in events),"resources_frozen":"UPSTREAM.RESOURCE_DELIVERY_FROZEN" in actions}
        blockers=[key for key,value in checks.items() if not value];data={"checks":checks,"blocking":len(blockers),"blocking_items":blockers,"status":"READY" if not blockers else "PRECHECK"}
        archive=self.repo.archive(course_id,class_id)
        if archive and archive.status=="ARCHIVED": return {**archive.precheck_json,"status":"ARCHIVED"}
        if archive: archive.precheck_json,archive.status,archive.gradebook_id=data,"READY" if not blockers else "PRECHECK",book.gradebook_id if book else archive.gradebook_id
        else: archive=CourseArchive(course_archive_id=str(uuid4()),course_id=course_id,class_id=class_id,gradebook_id=book.gradebook_id if book else None,status="READY" if not blockers else "PRECHECK",precheck_json=data,manifest_json=None,created_by=self.user.user_id,created_at=utcnow(),archived_at=None);self.repo.add(archive)
        self.audit("COURSE_ARCHIVE_PRECHECK","course_archive",archive.course_archive_id,result="SUCCESS" if not blockers else "BLOCKED",reason=",".join(blockers) or None,course_id=course_id,class_id=class_id,details=data)
        self.session.commit();return data

    def freeze_archive(self,course_id,class_id):
        self.authorize(course_id,"archives:freeze",class_id);existing=self.repo.archive(course_id,class_id)
        if existing and existing.status=="ARCHIVED":return existing.manifest_json
        check=self.precheck(course_id,class_id)
        if check["blocking"]:raise ApiError("ARCHIVE.PRECHECK_BLOCKED","归档门禁尚有阻断项",409,check)
        archive=self.repo.archive(course_id,class_id);book=self.repo.gradebook(course_id,class_id);book.status="LOCKED";book.locked_at=utcnow()
        artifacts=[]
        for kind,content in [("GRADEBOOK_XLSX",self.gradebook_xlsx(course_id)),("ANALYTICS_XLSX",self.analytics_xlsx(course_id))]:
            digest=sha256(content).hexdigest();ref=f"/api/v1/{'gradebook' if kind.startswith('GRADEBOOK') else 'analytics'}/courses/{course_id}/export.xlsx";file_id=str(uuid4())
            self.repo.add(FileObject(file_id=file_id,storage_provider="generated-api",bucket="course-archives",object_key=f"{archive.course_archive_id}/{kind.lower()}.xlsx",original_name=f"{course_id}-{'成绩册' if kind.startswith('GRADEBOOK') else '学情'}.xlsx",mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",size_bytes=len(content),sha256=digest,created_by=self.user.user_id,created_at=utcnow()))
            self.repo.add(CourseArchiveArtifact(course_archive_artifact_id=str(uuid4()),course_archive_id=archive.course_archive_id,artifact_type=kind,file_id=file_id,evidence_ref=ref,sha256=digest));artifacts.append({"type":kind,"file_id":file_id,"evidence_ref":ref,"sha256":digest})
        evidence_ids=[x.source_id for x in self.repo.grade_events(course_id,class_id) if x.source_type in {"LAB_CHECKPOINT","LAB_SUBMISSION"}]
        evidence_digest=sha256("\n".join(evidence_ids).encode()).hexdigest();evidence_ref="contract://lab-evidence/"+class_id
        self.repo.add(CourseArchiveArtifact(course_archive_artifact_id=str(uuid4()),course_archive_id=archive.course_archive_id,artifact_type="LAB_EVIDENCE_REFERENCES",file_id=None,evidence_ref=evidence_ref,sha256=evidence_digest));artifacts.append({"type":"LAB_EVIDENCE_REFERENCES","evidence_ref":evidence_ref,"sha256":evidence_digest})
        archive.status="ARCHIVED";archive.archived_at=utcnow();archive.manifest_json={"course_id":course_id,"class_id":class_id,"gradebook_id":book.gradebook_id,"policy_version":book.policy_version,"source_event_ids":[x.event_id for x in self.repo.grade_events(course_id,class_id)],"artifacts":artifacts,"archived_at":archive.archived_at.isoformat()+"Z"}
        self.audit("COURSE_ARCHIVED","course_archive",archive.course_archive_id,course_id=course_id,class_id=class_id,details=archive.manifest_json)
        enqueue_event(self.session,event_type="course.archived",aggregate_type="course_archive",aggregate_id=archive.course_archive_id,actor_user_id=self.user.user_id,idempotency_key=f"course-archived:{archive.course_archive_id}",payload={"course_id":course_id,"class_id":class_id,"gradebook_id":book.gradebook_id})
        self.session.commit();return archive.manifest_json

    def archive(self,course_id,class_id):
        self.authorize(course_id,"archives:read",class_id);row=self.repo.archive(course_id,class_id)
        return {"status":"PENDING"} if not row else {"status":row.status,"precheck":row.precheck_json,"manifest":row.manifest_json}
    def audit_list(self,course_id=None,action=None,result=None):
        if "audit:read" not in self.user.permissions and "grading:manage" not in self.user.permissions:raise ApiError("AUTH.PERMISSION_DENIED","缺少审计读取权限",403)
        rows=self.repo.audit_events(course_id=course_id,action=action,result=result);return {"items":[self.audit_dict(x) for x in rows],"page":1,"page_size":len(rows),"total":len(rows)}

    def gradebook_xlsx(self,course_id):
        data=self.gradebook(course_id);return self.make_xlsx("成绩册",["学生标识","总评","完整性"],[[x["student_id"],x["total_score"],x["completeness"]] for x in data.get("items",[])],course_id)
    def analytics_xlsx(self,course_id):
        overview=self.overview(course_id);gradebook=self.repo.gradebook(course_id);book=Workbook();sheet=book.active;sheet.title="课程总览";sheet.append(["课程标识",course_id]);sheet.append(["班级标识",gradebook.class_id if gradebook else None]);sheet.append(["生成时间",utcnow().isoformat()+"Z"]);sheet.append(["作业平均",overview.get("avg_assignment")]);sheet.append(["测验平均",overview.get("avg_quiz")]);sheet.append(["平均到课率",overview.get("attendance_rate")]);sheet.append(["课程平均",overview.get("course_average")])
        section_items=[]
        if gradebook:
            for row in self.repo.section_summaries(gradebook.gradebook_id):
                summary=row.summary_json
                for rank in summary.get("ranking",[]):section_items.append([row.lesson_id,summary.get("average"),rank.get("student_id"),rank.get("score")])
        worksheets=[("小节成绩",["课时","平均成绩","学生标识","学生成绩"],section_items),("学生实验完成",["学生标识","实验总分","已提交","未提交"],[[x["student_id"],x["sum_lab_score"],x["submitted_count"],x["unsubmitted_count"]] for x in self.labs_by_student(course_id)["items"]]),("实验完成统计",["实验发布标识","满分","已提交人数","未提交人数","平均分"],[[x["lab_release_id"],x["max_score"],x["submitted_students"],x["unsubmitted_students"],x["avg_score"]] for x in self.labs_by_lab(course_id)["items"]])]
        for title,headers,items in worksheets:
            ws=book.create_sheet(title);ws.append(["课程标识",course_id]);ws.append(["班级标识",gradebook.class_id if gradebook else None]);ws.append(["生成时间",utcnow().isoformat()+"Z"]);ws.append([]);ws.append(headers)
            for x in items:ws.append(x)
        output=BytesIO();book.save(output);return output.getvalue()
    def audit_xlsx(self,course_id=None):
        rows=self.audit_list(course_id)["items"];return self.make_xlsx("审计",["时间","操作者","角色","动作","对象类型","对象标识","结果","原因"],[[x["occurred_at"],x["actor_user_id"],x["actor_role"],x["action"],x["resource_type"],x["resource_id"],x["result"],x["reason"]] for x in rows],course_id or "全部")
    def audit_csv(self,course_id=None):
        import csv
        output=BytesIO();text=__import__('io').StringIO();writer=csv.writer(text);writer.writerow(["时间","操作者","角色","动作","对象类型","对象标识","结果","原因"])
        for x in self.audit_list(course_id)["items"]:writer.writerow([x[k] for k in ["occurred_at","actor_user_id","actor_role","action","resource_type","resource_id","result","reason"]])
        return ('\ufeff'+text.getvalue()).encode('utf-8')

    def build_risks(self,book,student_id,grouped,total,present,student_events,all_events):
        risks=[]
        if grouped.get("ATTENDANCE") and sum(grouped["ATTENDANCE"])/len(grouped["ATTENDANCE"])<80:risks.append(("LOW_ATTENDANCE",{"attendance_rate":float(sum(grouped["ATTENDANCE"])/len(grouped["ATTENDANCE"]))}))
        if total<60:risks.append(("LOW_TOTAL_SCORE",{"total_score":float(total),"threshold":60}))
        missing=[x for x in COMPONENTS if x not in present]
        if missing:risks.append(("MISSING_FACTS",{"missing_components":missing}))
        checkpoint_failures=[x for x in student_events if x.payload_json.get("source_event_type")=="lab.checkpoint.failed"]
        if len(checkpoint_failures)>=2:risks.append(("CONSECUTIVE_CHECKPOINT_FAILURES",{"failure_count":len(checkpoint_failures),"source_ids":[x.source_id for x in checkpoint_failures]}))
        available_labs={x.source_id for x in all_events if x.source_type=="LAB_SUBMISSION"};submitted_labs={x.source_id for x in student_events if x.source_type=="LAB_SUBMISSION"};missing_labs=sorted(available_labs-submitted_labs)
        if len(missing_labs)>=2:risks.append(("MULTIPLE_MISSING_SUBMISSIONS",{"missing_count":len(missing_labs),"lab_release_ids":missing_labs}))
        for kind,evidence in risks:self.repo.add(StudentRiskFlag(student_risk_flag_id=str(uuid4()),gradebook_id=book.gradebook_id,course_id=book.course_id,class_id=book.class_id,student_id=student_id,risk_type=kind,evidence_json=evidence,status="OPEN",created_at=utcnow()))
    def build_section_analytics(self,book,events):
        grouped=defaultdict(list)
        for e in events:
            if e.lesson_id:grouped[e.lesson_id].append(e)
        for lesson_id,rows in grouped.items():
            per=defaultdict(list)
            for e in rows:per[e.student_id].append(Decimal(e.normalized_score))
            scores=[sum(x)/len(x) for x in per.values()];dist={"0-59":0,"60-69":0,"70-79":0,"80-89":0,"90-100":0}
            for score in scores:dist["0-59" if score<60 else "60-69" if score<70 else "70-79" if score<80 else "80-89" if score<90 else "90-100"]+=1
            ranking=sorted([{"student_id":s,"score":float(sum(v)/len(v))} for s,v in per.items()],key=lambda x:x["score"],reverse=True)
            self.repo.add(AnalyticsSectionSummary(analytics_section_summary_id=str(uuid4()),gradebook_id=book.gradebook_id,lesson_id=lesson_id,summary_json={"status":"READY","lesson_id":lesson_id,"average":self.average(scores),"distribution":dist,"ranking":ranking}))
    def build_lab_analytics(self,book,events,student_count):
        submissions=[e for e in events if e.source_type=="LAB_SUBMISSION"];by_student=defaultdict(list);by_lab=defaultdict(list)
        for e in submissions:by_student[e.student_id].append(e);by_lab[e.source_id].append(e)
        labs=set(by_lab)
        for student_id,rows in by_student.items():self.repo.add(AnalyticsStudentLabSummary(analytics_student_lab_summary_id=str(uuid4()),gradebook_id=book.gradebook_id,student_id=student_id,sum_lab_score=sum((Decimal(x.normalized_score) for x in rows),Decimal("0")),submitted_count=len({x.source_id for x in rows}),unsubmitted_count=max(0,len(labs)-len({x.source_id for x in rows}))))
        for lab_id,rows in by_lab.items():self.repo.add(AnalyticsLabSummary(analytics_lab_summary_id=str(uuid4()),gradebook_id=book.gradebook_id,lab_release_id=lab_id,max_score=max(Decimal(x.max_score) for x in rows),submitted_students=len({x.student_id for x in rows}),unsubmitted_students=max(0,student_count-len({x.student_id for x in rows})),avg_score=Decimal(str(self.average([Decimal(x.normalized_score) for x in rows])))))
    @staticmethod
    def component(source):return "LAB" if source.startswith("LAB_") else source
    @staticmethod
    def average(values):return round(float(sum(values)/len(values)),2) if values else None
    def policy_dict(self,p):return {"course_id":p.course_id,"version_no":p.version_no,"status":p.status,"effective_at":p.effective_at.isoformat()+"Z","items":[{"component":x.component,"weight_percent":number(x.weight_percent)} for x in self.repo.policy_items(p.grading_policy_id)]}
    @staticmethod
    def gradebook_dict(b):return {"gradebook_id":b.gradebook_id,"course_id":b.course_id,"class_id":b.class_id,"policy_version":b.policy_version,"status":b.status,"calculated_at":b.calculated_at.isoformat()+"Z","posted_at":b.posted_at.isoformat()+"Z" if b.posted_at else None}
    @staticmethod
    def event_dict(e):return {"grade_event_id":e.grade_event_id,"source_type":e.source_type,"source_id":e.source_id,"lesson_id":e.lesson_id,"raw_score":number(e.raw_score),"max_score":number(e.max_score),"normalized_score":number(e.normalized_score),"occurred_at":e.occurred_at.isoformat()+"Z","event_id":e.event_id}
    @staticmethod
    def audit_dict(x):return {"audit_event_id":x.audit_event_id,"source_event_id":x.source_event_id,"actor_user_id":x.actor_user_id,"actor_role":x.actor_role,"action":x.action,"resource_type":x.resource_type,"resource_id":x.resource_id,"course_id":x.course_id,"class_id":x.class_id,"student_id":x.student_id,"request_id":x.request_id,"ip":x.ip,"result":x.result,"reason":x.reason,"occurred_at":x.occurred_at.isoformat()+"Z","details":x.details_json}
    @staticmethod
    def make_xlsx(title,headers,rows,course_id):
        book=Workbook();sheet=book.active;sheet.title=title;sheet.append(["课程/范围",course_id]);sheet.append(["生成时间",utcnow().isoformat()+"Z"]);sheet.append([]);sheet.append(headers)
        for row in rows:sheet.append(row)
        output=BytesIO();book.save(output);return output.getvalue()
