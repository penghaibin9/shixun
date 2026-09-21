from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event

from . import models as m
from .gateway import GatewayBundle
from .repository import ClassroomRepository
from .schemas import DistributionCreate, RuntimeActionIn, RuntimeEventIn


def now() -> datetime: return datetime.utcnow()
def entity_dict(entity) -> dict: return {c.name: getattr(entity, c.name) for c in entity.__table__.columns}
def as_datetime(value):
    if not value or isinstance(value, datetime): return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


class ClassroomService:
    def __init__(self, session: Session, user: UserContext, gateways: GatewayBundle): self.session, self.user, self.gateways, self.repo = session, user, gateways, ClassroomRepository(session)
    def require(self, permission: str):
        if permission not in self.user.permissions: raise ApiError("AUTH.FORBIDDEN", "没有执行此操作的权限", 403)
    def require_class(self, class_id: str):
        if class_id not in self.user.class_ids: raise ApiError("AUTH.SCOPE_DENIED", "无权访问该班级", 403)
    def require_student(self) -> str:
        if not self.user.student_id: raise ApiError("AUTH.STUDENT_REQUIRED", "当前身份没有关联学生", 403)
        return self.user.student_id
    def audit(self, action: str, aggregate_id: str, payload: dict):
        enqueue_event(self.session, event_type="classroom.audit.requested", aggregate_type="classroom_action", aggregate_id=aggregate_id, actor_user_id=self.user.user_id, idempotency_key=f"{action}:{aggregate_id}:{uuid4()}", payload={"action": action, **payload})

    def release_summary(self, release_id: str):
        self.require("classroom.release.read")
        data = self.gateways.runtime.request("GET", f"/api/v1/runtime/lab-releases/{release_id}/summary", self.user)
        self.require_class(data["class_id"]); return data
    def release_students(self, release_id: str):
        summary = self.release_summary(release_id)
        data = self.gateways.runtime.request("GET", f"/api/v1/runtime/lab-releases/{release_id}/students", self.user)
        return data | {"dependency": "D", "class_id": summary["class_id"]}
    def release_student(self, release_id: str, student_id: str):
        summary = self.release_summary(release_id)
        data = self.gateways.runtime.request("GET", f"/api/v1/runtime/lab-releases/{release_id}/students/{student_id}", self.user)
        return data | {"class_id": summary["class_id"]}
    def runtime_action(self, runtime_id: str, action: str, body: RuntimeActionIn):
        self.require(f"classroom.runtime.{action}")
        instance = self.gateways.runtime.request("GET", f"/api/v1/runtime/instances/{runtime_id}", self.user)
        self.require_class(instance["class_id"])
        result = self.gateways.runtime.request("POST", f"/api/v1/runtime/instances/{runtime_id}/{action}", self.user, json=body.model_dump(exclude_none=True))
        self.audit(f"runtime.{action}", runtime_id, {"class_id": instance["class_id"], "student_id": instance.get("student_id"), "reason": body.reason})
        self.session.commit(); return result
    def release_action(self, release_id: str, action: str, body: RuntimeActionIn):
        self.require(f"classroom.release.{action}"); summary = self.release_summary(release_id)
        result = self.gateways.runtime.request("POST", f"/api/v1/runtime/lab-releases/{release_id}/{action}", self.user, json=body.model_dump(exclude_none=True))
        self.audit(f"release.{action}", release_id, {"class_id": summary["class_id"]}); self.session.commit(); return result

    def student_start(self, release_id: str):
        self.require("classroom.lab.start"); student_id = self.require_student()
        release = self.gateways.runtime.request("GET", f"/api/v1/runtime/lab-releases/{release_id}", self.user); self.require_class(release["class_id"])
        return self.gateways.runtime.request("POST", f"/api/v1/runtime/lab-releases/{release_id}/start", self.user, json={"student_id": student_id})
    def student_release(self, release_id: str):
        self.require("classroom.lab.read"); student_id = self.require_student()
        data = self.gateways.runtime.request("GET", f"/api/v1/runtime/lab-releases/{release_id}/students/{student_id}", self.user)
        self.require_class(data["class_id"]); return data
    def student_submit(self, release_id: str):
        self.require("classroom.lab.submit"); student_id = self.require_student()
        data = self.student_release(release_id)
        return self.gateways.runtime.request("POST", f"/api/v1/runtime/lab-releases/{release_id}/submit", self.user, json={"student_id": student_id, "runtime_instance_id": data.get("runtime_instance_id")})
    def terminal_token(self, runtime_id: str, assist: bool):
        self.require("classroom.terminal.assist" if assist else "classroom.terminal.use")
        instance = self.gateways.runtime.request("GET", f"/api/v1/runtime/instances/{runtime_id}", self.user); self.require_class(instance["class_id"])
        if not assist and instance.get("student_id") != self.require_student(): raise ApiError("AUTH.SCOPE_DENIED", "不能访问他人的终端", 403)
        result = self.gateways.runtime.request("POST", f"/api/v1/runtime/instances/{runtime_id}/terminal-token", self.user, json={"mode": "ASSIST" if assist else "STUDENT"})
        if assist:
            self.audit("terminal.assist.opened", runtime_id, {"class_id": instance["class_id"], "student_id": instance.get("student_id")}); self.session.commit()
        return result

    def audit_logs(self, params: dict):
        self.require("classroom.logs.read")
        runtime_items, f_items, pending = [], [], []
        try: runtime_items = self.gateways.runtime.request("GET", "/api/v1/runtime/logs/audit", self.user, params=params).get("items", [])
        except ApiError as exc:
            if exc.status_code != 503: raise
            pending.append("D")
        try: f_items = self.gateways.grading.request("GET", "/api/v1/audit", self.user, params=params).get("items", [])
        except ApiError as exc:
            if exc.status_code != 503: raise
            pending.append("F")
        if len(pending) == 2: raise ApiError("DEPENDENCY.PENDING", "审计日志依赖尚未接入", 503, {"dependencies": pending, "status": "PENDING"})
        items = runtime_items + f_items
        return {"items": items, "page": 1, "page_size": len(items), "total": len(items), "dependencies": {name: ("PENDING" if name in pending else "READY") for name in ("D", "F")}}
    def traffic_logs(self, params: dict):
        self.require("classroom.logs.read"); return self.gateways.runtime.request("GET", "/api/v1/runtime/logs/traffic", self.user, params=params)
    def artifact_download(self, artifact_id: str):
        self.require("classroom.logs.download")
        artifact = self.gateways.runtime.request("GET", f"/api/v1/runtime/log-artifacts/{artifact_id}", self.user); self.require_class(artifact["class_id"])
        return self.gateways.runtime.request("POST", f"/api/v1/runtime/log-artifacts/{artifact_id}/download-url", self.user)

    def create_distribution(self, body: DistributionCreate, key: str):
        self.require("classroom.logs.distribute"); self.require_class(body.class_id)
        if not key: raise ApiError("REQUEST.IDEMPOTENCY_REQUIRED", "日志分发必须提供 Idempotency-Key", 400)
        previous = self.repo.distribution_by_key(body.class_id, key)
        if previous: return self.distribution(previous.distribution_id)
        member_ids, page = set(), 1
        while True:
            members = self.gateways.teaching.request("GET", f"/api/v1/classes/{body.class_id}/members", self.user, params={"page": page, "page_size": 100})
            member_ids.update(item["student_id"] for item in members.get("items", []))
            if len(member_ids) >= members.get("total", len(member_ids)) or not members.get("items"): break
            page += 1
        if not set(body.target_student_ids) <= member_ids: raise ApiError("LOG_DISTRIBUTION.TARGET_FORBIDDEN", "目标学生不属于本人任课班级", 403)
        endpoint = "/api/v1/runtime/logs/traffic" if body.distribution_type == "TRAFFIC" else "/api/v1/runtime/logs/audit"
        available = self.gateways.runtime.request("GET", endpoint, self.user, params={**body.source_filter, "class_id": body.class_id, "lab_release_id": body.lab_release_id, "page_size": body.requested_count})
        artifacts = [item for item in available.get("items", []) if item.get("artifact_id")]
        if len(artifacts) < body.requested_count: raise ApiError("LOG_DISTRIBUTION.INSUFFICIENT_ARTIFACTS", "可用日志数量不足", 422, {"available": len(artifacts), "requested": body.requested_count})
        task = self.repo.add(m.TeachingLogDistributionTask(distribution_id=str(uuid4()), course_id=body.course_id, class_id=body.class_id, lab_release_id=body.lab_release_id, distribution_type=body.distribution_type, source_filter_json=body.source_filter, requested_count=body.requested_count, title=body.title, instruction=body.instruction, due_at=body.due_at, status="ASSIGNED", idempotency_key=key, created_by=self.user.user_id, created_at=now()))
        for artifact in artifacts[:body.requested_count]: self.repo.add(m.TeachingLogDistributionItem(item_id=str(uuid4()), distribution_id=task.distribution_id, artifact_id=artifact["artifact_id"], source_system="D", source_student_id=artifact.get("student_id"), artifact_type=body.distribution_type, artifact_meta_json={k: artifact.get(k) for k in ("name", "size_bytes", "occurred_at")}))
        for student_id in body.target_student_ids: self.repo.add(m.StudentLogAssignment(assignment_id=str(uuid4()), distribution_id=task.distribution_id, class_id=body.class_id, student_id=student_id, status="ASSIGNED", assigned_at=now(), downloaded_at=None))
        enqueue_event(self.session, event_type="teaching.log.distributed", aggregate_type="teaching_log_distribution", aggregate_id=task.distribution_id, actor_user_id=self.user.user_id, idempotency_key=key, payload={"course_id": body.course_id, "class_id": body.class_id, "lab_release_id": body.lab_release_id, "target_student_ids": body.target_student_ids, "artifact_ids": [x["artifact_id"] for x in artifacts[:body.requested_count]]})
        self.audit("logs.distributed", task.distribution_id, {"class_id": body.class_id, "target_count": len(body.target_student_ids), "artifact_count": body.requested_count})
        self.session.commit(); return self.distribution(task.distribution_id)
    def distributions(self):
        self.require("classroom.logs.read"); items = self.repo.distributions(self.user.class_ids)
        return {"items": [entity_dict(x) for x in items], "page": 1, "page_size": len(items), "total": len(items)}
    def distribution(self, distribution_id: str):
        task = self.repo.get(m.TeachingLogDistributionTask, distribution_id)
        if not task: raise ApiError("LOG_DISTRIBUTION.NOT_FOUND", "日志分发任务不存在", 404)
        self.require_class(task.class_id)
        return entity_dict(task) | {"items": [entity_dict(x) for x in self.repo.distribution_items(distribution_id)]}
    def my_assignments(self):
        self.require("classroom.logs.assignment.read"); student_id = self.require_student(); rows = self.repo.student_assignments(student_id)
        return {"items": [entity_dict(x) | {"distribution": entity_dict(self.repo.get(m.TeachingLogDistributionTask, x.distribution_id))} for x in rows], "page": 1, "page_size": len(rows), "total": len(rows)}
    def assignment_download(self, assignment_id: str):
        self.require("classroom.logs.assignment.download"); student_id = self.require_student(); assignment = self.repo.assignment(assignment_id)
        if not assignment or assignment.student_id != student_id: raise ApiError("AUTH.SCOPE_DENIED", "不能下载他人的日志任务", 403)
        items = self.repo.distribution_items(assignment.distribution_id)
        result = self.gateways.runtime.request("POST", "/api/v1/runtime/log-artifacts/bundle-url", self.user, json={"artifact_ids": [x.artifact_id for x in items], "student_id": student_id})
        assignment.status = "DOWNLOADED"; assignment.downloaded_at = now(); self.session.commit(); return result

    def consume_event(self, event: RuntimeEventIn):
        self.require("classroom.events.consume")
        if self.repo.consumed(event.event_id): return {"event_id": event.event_id, "status": "ALREADY_CONSUMED"}
        payload = dict(event.payload); required = {"lab_release_id", "course_id", "class_id", "student_id", "runtime_instance_id", "status"}
        missing = sorted(key for key in required if key not in payload or (key != "runtime_instance_id" and payload[key] is None))
        if "current_step" not in payload and "step" not in payload: missing.append("step")
        if "raw_score" not in payload and "score" not in payload: missing.append("score")
        if missing: raise ApiError("EVENT.INVALID_PAYLOAD", "运行事件缺少课堂投影字段", 422, {"required": sorted(required | {"step", "score"}), "missing": missing})
        payload.setdefault("current_step", payload.get("step", 0)); payload.setdefault("raw_score", payload.get("score", 0))
        implied_status = {"lab.instance.started":"RUNNING", "lab.instance.failed":"FAILED", "lab.instance.destroyed":"DESTROYED", "lab.submitted":"SUBMITTED"}.get(event.event_type)
        if implied_status: payload["status"] = implied_status
        projection = self.repo.projection(payload["lab_release_id"], payload["student_id"])
        if not projection:
            projection = self.repo.add(m.RuntimeProjection(projection_id=str(uuid4()), lab_release_id=payload["lab_release_id"], course_id=payload["course_id"], class_id=payload["class_id"], student_id=payload["student_id"], runtime_instance_id=payload.get("runtime_instance_id"), status=payload.get("status", "NOT_STARTED"), current_step=payload.get("current_step", 0), total_steps=payload.get("total_steps", 0), raw_score=payload.get("raw_score", 0), max_score=payload.get("max_score", 100), started_at=as_datetime(payload.get("started_at")), last_activity_at=as_datetime(payload.get("last_activity_at")), updated_at=now()))
        else:
            for field in ("runtime_instance_id", "status", "current_step", "total_steps", "raw_score", "max_score", "started_at", "last_activity_at"):
                if field in payload: setattr(projection, field, as_datetime(payload[field]) if field in {"started_at", "last_activity_at"} else payload[field])
            projection.updated_at = now()
        self.repo.add(m.ConsumedRuntimeEvent(event_id=event.event_id, event_type=event.event_type, aggregate_id=event.aggregate_id, idempotency_key=event.idempotency_key, payload_json=payload, occurred_at=event.occurred_at, consumed_at=now()))
        self.repo.add(m.ClassroomRuntimeEvent(event_id=event.event_id, lab_release_id=payload["lab_release_id"], student_id=payload["student_id"], event_type=event.event_type, payload_json=payload, occurred_at=event.occurred_at))
        self.session.commit(); return {"event_id": event.event_id, "status": "CONSUMED"}

    def learning_summary(self, student_id: str, class_id: str):
        self.require("classroom.readmodel.read"); self.require_class(class_id)
        counts = self.repo.student_experiment_counts(student_id)
        experiment = {"status": "READY", **counts} if counts["total"] else {"status": "PENDING", "label": "实验数据待汇总"}
        grade = risk = {"status": "PENDING", "label": "评分与风险数据待汇总"}
        try:
            upstream = self.gateways.grading.request("GET", f"/api/v1/grading/students/{student_id}/summary", self.user, params={"class_id": class_id})
            grade, risk = upstream.get("grade", grade), upstream.get("risk", risk)
        except ApiError as exc:
            if exc.status_code != 503: raise
        return {"student_id": student_id, "class_id": class_id, "experiment": experiment, "grade": grade, "risk": risk, "source": {"experiment": "D_EVENT_PROJECTION", "grade_risk": "F_CONTRACT"}}
