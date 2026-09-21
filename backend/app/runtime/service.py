from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.outbox import enqueue_event

from . import models
from .catalog import LabCatalogClient
from .provider import NodeAgentClient
from .schemas import ImageRegister, NodeRegister, RuntimeExtend, RuntimeStart


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


ALLOWED_TRANSITIONS = {
    "QUEUED": {"SCHEDULING", "CANCELED", "FAILED"},
    "SCHEDULING": {"STARTING", "QUEUED", "FAILED"},
    "STARTING": {"RUNNING", "FAILED"},
    "RUNNING": {"FAILED", "CANCELED"},
    "FAILED": {"SCHEDULING", "CANCELED"},
    "CANCELED": set(),
    "DESTROYED": set(),
}


class RuntimeService:
    def __init__(self, session: Session, user: UserContext, catalog: LabCatalogClient | None = None, agent_factory=None):
        self.session = session
        self.user = user
        self.catalog = catalog or LabCatalogClient()
        self.agent_factory = agent_factory or (lambda url: NodeAgentClient(url))

    def _permission(self, name: str) -> None:
        if name not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "当前账号没有此操作权限", 403, {"required_permission": name})

    def _scope(self, data: RuntimeStart) -> None:
        if data.course_id and data.course_id not in self.user.course_ids:
            raise ApiError("AUTH.COURSE_SCOPE_DENIED", "无权访问该课程的实验运行环境", 403)
        if data.class_id and data.class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权访问该班级的实验运行环境", 403)
        if data.mode == "STUDENT" and (self.user.role != "student" or data.student_id != self.user.student_id):
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能启动自己的实验环境", 403)
        if data.mode == "TEACHER_PREVIEW" and self.user.role not in {"teacher", "admin"}:
            raise ApiError("AUTH.FORBIDDEN", "仅教师或管理员可发起预演", 403)

    def _instance_scope(self, item: models.RuntimeInstance, permission: str = "runtime.read") -> None:
        self._permission(permission)
        if self.user.role == "student" and item.student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能访问自己的实验实例", 403)
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id) if group else None
        if not request:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        if self.user.role == "teacher":
            if request.course_id and request.course_id not in self.user.course_ids:
                raise ApiError("AUTH.COURSE_SCOPE_DENIED", "无权访问该课程的实验实例", 403)
            if request.class_id and request.class_id not in self.user.class_ids:
                raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权访问该班级的实验实例", 403)

    def _event(self, event_type: str, *, instance_id: str | None = None, group_id: str | None = None, detail: dict | None = None, idempotency_key: str | None = None) -> None:
        stamp = now()
        self.session.add(models.RuntimeEvent(runtime_event_id=new_id("rte"), runtime_instance_id=instance_id, runtime_group_id=group_id, event_type=event_type, actor_user_id=self.user.user_id, detail_json=detail or {}, occurred_at=stamp))
        if event_type.startswith("lab."):
            aggregate_id = instance_id or group_id or self.user.user_id
            enqueue_event(self.session, event_type=event_type, aggregate_type="runtime_instance", aggregate_id=aggregate_id, actor_user_id=self.user.user_id, idempotency_key=idempotency_key or f"{event_type}:{aggregate_id}", payload=detail or {})

    @staticmethod
    def _projection_payload(request: models.RuntimeRequest, instance: models.RuntimeInstance | None, *, status: str, current_step: int = 0, raw_score: int = 0, max_score: int = 100, **extra) -> dict:
        return {"lab_release_id": request.lab_release_id, "course_id": request.course_id, "class_id": request.class_id, "student_id": request.student_id, "runtime_instance_id": instance.runtime_instance_id if instance else None, "status": status, "step": current_step, "score": raw_score, "current_step": current_step, "total_steps": len(request.spec_snapshot_json.get("steps", [])), "raw_score": raw_score, "max_score": max_score, "started_at": instance.started_at.isoformat() if instance and instance.started_at else None, "last_activity_at": request.last_activity_at.isoformat() if request.last_activity_at else request.updated_at.isoformat(), **extra}

    @staticmethod
    def _transition(item, status: str) -> None:
        if status not in ALLOWED_TRANSITIONS.get(item.status, set()):
            raise ApiError("RUNTIME.INVALID_STATE_TRANSITION", "当前状态不能执行该操作", 409, {"from": item.status, "to": status})
        item.status = status

    async def start(self, data: RuntimeStart, idempotency_key: str) -> dict:
        self._permission("runtime.start" if data.mode == "STUDENT" else "runtime.preview")
        self._scope(data)
        existing = self.session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.requested_by == self.user.user_id, models.RuntimeRequest.idempotency_key == idempotency_key))
        if existing:
            return self.request_view(existing)
        spec = await self.catalog.frozen_version(data.lab_version_id, data.course_id)
        self._validate_spec(spec, data.lab_version_id)
        stamp = now()
        if data.course_id and data.class_id:
            context = self.session.get(models.RuntimeReleaseReadModel, data.lab_release_id)
            if not context:
                self.session.add(models.RuntimeReleaseReadModel(lab_release_id=data.lab_release_id, lab_version_id=data.lab_version_id, course_id=data.course_id, class_id=data.class_id, status="OPEN", spec_snapshot_json=spec, published_at=stamp, updated_at=stamp))
        request = models.RuntimeRequest(
            runtime_request_id=new_id("rrq"), lab_release_id=data.lab_release_id, lab_version_id=data.lab_version_id,
            course_id=data.course_id, class_id=data.class_id, student_id=data.student_id, mode=data.mode, status="SCHEDULING",
            requested_by=self.user.user_id, idempotency_key=idempotency_key, spec_snapshot_json=spec,
            error_code=None, error_message=None, submission_status="DRAFT", submitted_at=None, last_activity_at=stamp, created_at=stamp, updated_at=stamp,
        )
        self.session.add(request)
        self._event("runtime.request.created", detail={"runtime_request_id": request.runtime_request_id, "student_id": data.student_id, "mode": data.mode})
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            previous = self.session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.requested_by == self.user.user_id, models.RuntimeRequest.idempotency_key == idempotency_key))
            if previous:
                return self.request_view(previous)
            raise
        return await self._schedule_and_provision(request)

    def _validate_spec(self, spec: dict, version_id: str) -> None:
        required = {"lab_definition_id", "version", "nodes", "networks", "image_bindings", "checkpoints", "runtime_policy"}
        if not required.issubset(spec):
            raise ApiError("RUNTIME.INVALID_LAB_SPEC", "冻结实验版本字段不完整", 422)
        if not spec["nodes"] or not spec["networks"]:
            raise ApiError("RUNTIME.INVALID_LAB_SPEC", "实验拓扑不能为空", 422)
        bindings = {item["node_key"]: item for item in spec["image_bindings"]}
        for node in spec["nodes"]:
            binding = bindings.get(node["node_key"])
            if not binding or binding.get("digest") != node.get("image_digest") or not str(node.get("image_digest", "")).startswith("sha256:"):
                raise ApiError("RUNTIME.IMAGE_DIGEST_MISMATCH", "实验节点必须绑定固定且一致的镜像摘要", 422, {"node_key": node.get("node_key")})
            if node.get("mounts"):
                raise ApiError("RUNTIME.MOUNT_NOT_APPROVED", "首期运行时不接受宿主机挂载", 422, {"node_key": node["node_key"]})
        if any(net.get("internet_access") for net in spec["networks"]):
            raise ApiError("RUNTIME.NETWORK_POLICY_UNSUPPORTED", "首期实验网络默认禁止外网", 422)

    async def _schedule_and_provision(self, request: models.RuntimeRequest) -> dict:
        spec = request.spec_snapshot_json
        cpu = sum(float(node["cpu_limit"]) for node in spec["nodes"])
        memory = sum(int(node["memory_mb"]) for node in spec["nodes"])
        digests = {node["image_digest"] for node in spec["nodes"]}
        enabled = set(self.session.scalars(select(models.InfraImage.digest).where(models.InfraImage.enabled.is_(True), models.InfraImage.scan_status == "PASSED", models.InfraImage.startup_check_status == "PASSED", models.InfraImage.teaching_validation_status == "PASSED")))
        missing = sorted(digests - enabled)
        if missing:
            return self._pending(request, "RUNTIME.IMAGE_NOT_READY", "实验镜像尚未完成三重验证", {"missing_digests": missing})
        candidates = []
        for node in self.session.scalars(select(models.InfraNode).where(models.InfraNode.status == "READY", models.InfraNode.scheduling_paused.is_(False))):
            try:
                capacity = await self.agent_factory(node.agent_url).capacity()
                observed = now()
                node.last_seen_at = observed
                heartbeat = models.InfraNodeHeartbeat(heartbeat_id=new_id("hbt"), node_id=node.node_id, observed_at=observed, cpu_available=float(capacity["cpu_available"]), memory_available_mb=int(capacity["memory_available_mb"]), running_groups=int(capacity["running_groups"]), image_digests_json=capacity.get("image_digests", []), detail_json={"engine": capacity.get("engine")})
                self.session.add(heartbeat)
                self.session.flush()
            except ApiError:
                continue
            if heartbeat and heartbeat.cpu_available >= cpu and heartbeat.memory_available_mb >= memory:
                cached = len(digests.intersection(heartbeat.image_digests_json or []))
                score = node.weight + heartbeat.cpu_available * 10 + heartbeat.memory_available_mb / 1024 + cached * 50 - heartbeat.running_groups * 5
                candidates.append((score, node, heartbeat, cached))
        if not candidates:
            return self._pending(request, "RUNTIME.CAPACITY_UNAVAILABLE", "暂无满足资源和健康要求的计算节点", {"cpu": cpu, "memory_mb": memory})
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, node, _, cached = candidates[0]
        request.status = "STARTING"
        request.error_code = request.error_message = None
        request.updated_at = now()
        group_id = new_id("rtg")
        timeout = int(spec["runtime_policy"]["timeout_minutes"])
        group = models.RuntimeInstanceGroup(runtime_group_id=group_id, runtime_request_id=request.runtime_request_id, node_id=node.node_id, provider_group_id=None, status="STARTING", scheduler_score=score, scheduler_reason=f"健康节点；资源满足；命中 {cached}/{len(digests)} 个镜像缓存", scheduled_at=now(), expires_at=now() + timedelta(minutes=timeout), destroyed_at=None)
        self.session.add(group)
        self.session.commit()
        payload = {
            "runtime_group_id": group_id,
            "expires_at": group.expires_at.isoformat(),
            "networks": spec["networks"],
            "containers": [{"node_key": item["node_key"], "role": item["role"], "image_digest": item["image_digest"], "cpu_limit": item["cpu_limit"], "memory_mb": item["memory_mb"], "pids_limit": 128, "startup_command": item.get("startup_command", "")} for item in spec["nodes"]],
        }
        result = None
        last_error = None
        for attempt, (candidate_score, candidate_node, _, candidate_cached) in enumerate(candidates, start=1):
            node, score, cached = candidate_node, candidate_score, candidate_cached
            group.node_id, group.scheduler_score = node.node_id, score
            group.scheduler_reason = f"健康节点；资源满足；命中 {cached}/{len(digests)} 个镜像缓存；第 {attempt} 次调度"
            group.scheduled_at = now()
            self._event("runtime.group.scheduled", group_id=group_id, detail={"node_id": node.node_id, "score": score, "reason": group.scheduler_reason, "scheduled_at": group.scheduled_at.isoformat(), "attempt": attempt})
            self.session.commit()
            try:
                result = await self.agent_factory(node.agent_url).create_group(payload)
                break
            except ApiError as error:
                last_error = error
                self._event("runtime.group.retry", group_id=group_id, detail={"node_id": node.node_id, "attempt": attempt, "error_code": error.code})
                self.session.commit()
        if result is None:
            error = last_error or ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "计算节点代理不可用", 503)
            request.status, request.error_code, request.error_message, request.updated_at = "FAILED", error.code, error.message, now()
            group.status = "FAILED"
            self._event("lab.instance.failed", group_id=group_id, detail=self._projection_payload(request, None, status="FAILED", error_code=error.code), idempotency_key=f"lab.instance.failed:{request.runtime_request_id}:{len(candidates)}")
            self.session.commit()
            raise ApiError(error.code, error.message, error.status_code, {**error.details, "runtime_request_id": request.runtime_request_id}) from error
        group.provider_group_id = result["provider_group_id"]
        group.status = "RUNNING"
        request.status = "RUNNING"
        request.updated_at = now()
        instances = []
        for container in result.get("containers", []):
            source = next(item for item in spec["nodes"] if item["node_key"] == container["node_key"])
            instance = models.RuntimeInstance(runtime_instance_id=new_id("rti"), runtime_group_id=group_id, student_id=request.student_id, node_key=source["node_key"], role=source["role"], status="RUNNING", started_at=now(), expires_at=group.expires_at, ended_at=None)
            self.session.add(instance)
            self.session.add(models.RuntimeContainer(runtime_container_id=new_id("rtc"), runtime_instance_id=instance.runtime_instance_id, provider_container_id=container["container_id"], image_digest=source["image_digest"], status="RUNNING", metadata_json={"name": container.get("name")}))
            instances.append(instance)
        for network in result.get("networks", []):
            self.session.add(models.RuntimeNetwork(runtime_network_id=new_id("rtn"), runtime_group_id=group_id, network_key=network["network_key"], provider_network_id=network["network_id"], status="ACTIVE", isolation_checks_json=network.get("isolation_checks", {})))
        primary = next((x for x in instances if x.role == "STUDENT_WORKSTATION"), instances[0] if instances else None)
        request.last_activity_at = now()
        self._event("lab.instance.started", instance_id=primary.runtime_instance_id if primary else None, group_id=group_id, detail=self._projection_payload(request, primary, status="RUNNING"), idempotency_key=f"lab.instance.started:{primary.runtime_instance_id if primary else group_id}:1")
        self.session.commit()
        return self.request_view(request)

    def _pending(self, request: models.RuntimeRequest, code: str, message: str, detail: dict) -> dict:
        request.status, request.error_code, request.error_message, request.updated_at = "QUEUED", code, message, now()
        self.session.add(models.RuntimeQueue(queue_id=new_id("rtq"), runtime_request_id=request.runtime_request_id, status="WAITING", priority=100, attempts=0, not_before=None, enqueued_at=now()))
        self._event("runtime.request.queued", detail={"runtime_request_id": request.runtime_request_id, "reason": code})
        self.session.commit()
        return self.request_view(request)

    def request(self, request_id: str) -> dict:
        self._permission("runtime.read")
        item = self.session.get(models.RuntimeRequest, request_id)
        if not item:
            raise ApiError("RUNTIME.REQUEST_NOT_FOUND", "运行请求不存在", 404)
        if self.user.role == "student" and item.student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能查看自己的运行请求", 403)
        return self.request_view(item)

    def cancel_request(self, request_id: str, reason: str) -> dict:
        self._permission("runtime.destroy")
        item = self.session.get(models.RuntimeRequest, request_id)
        if not item:
            raise ApiError("RUNTIME.REQUEST_NOT_FOUND", "运行请求不存在", 404)
        if self.user.role == "student" and item.student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能取消自己的运行请求", 403)
        if item.status == "CANCELED":
            return self.request_view(item)
        if item.status not in {"QUEUED", "SCHEDULING"}:
            raise ApiError("RUNTIME.REQUEST_NOT_CANCELABLE", "当前运行请求不能直接取消", 409)
        item.status, item.updated_at, item.last_activity_at = "CANCELED", now(), now()
        queued = self.session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == request_id))
        if queued:
            queued.status = "CANCELED"
        self._event("runtime.request.canceled", detail={"runtime_request_id": request_id, "reason": reason})
        self.session.commit()
        return self.request_view(item)

    def request_view(self, item: models.RuntimeRequest) -> dict:
        group = self.session.scalar(select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_request_id == item.runtime_request_id))
        instances = list(self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id))) if group else []
        return {"runtime_request_id": item.runtime_request_id, "lab_release_id": item.lab_release_id, "lab_version_id": item.lab_version_id, "course_id": item.course_id, "class_id": item.class_id, "mode": item.mode, "student_id": item.student_id, "status": item.status, "display_status": self._display_status(item.status), "error": {"code": item.error_code, "message": item.error_message} if item.error_code else None, "runtime_group_id": group.runtime_group_id if group else None, "instance_ids": [x.runtime_instance_id for x in instances], "submission_status": item.submission_status, "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None, "started_at": min((x.started_at for x in instances if x.started_at), default=None).isoformat() if any(x.started_at for x in instances) else None, "last_activity_at": item.last_activity_at.isoformat() if item.last_activity_at else item.updated_at.isoformat(), "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}

    def instance(self, instance_id: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item)
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id)
        results = list(self.session.scalars(select(models.CheckpointResult).where(models.CheckpointResult.runtime_instance_id == item.runtime_instance_id).order_by(models.CheckpointResult.judged_at)))
        networks = list(self.session.scalars(select(models.RuntimeNetwork).where(models.RuntimeNetwork.runtime_group_id == group.runtime_group_id)))
        latest_results = {}
        for result in results:
            latest_results[result.checkpoint_id] = result
        raw_score = sum(x.score_awarded for x in latest_results.values())
        return {"runtime_instance_id": item.runtime_instance_id, "runtime_group_id": item.runtime_group_id, "runtime_request_id": request.runtime_request_id, "lab_release_id": request.lab_release_id, "lab_version_id": request.lab_version_id, "course_id": request.course_id, "class_id": request.class_id, "student_id": item.student_id, "node_key": item.node_key, "role": item.role, "status": item.status, "display_status": self._display_status(item.status), "submission_status": request.submission_status, "node_id": group.node_id, "scheduler": {"score": group.scheduler_score, "reason": group.scheduler_reason, "scheduled_at": group.scheduled_at.isoformat()}, "started_at": item.started_at.isoformat() if item.started_at else None, "last_activity_at": request.last_activity_at.isoformat() if request.last_activity_at else request.updated_at.isoformat(), "expires_at": item.expires_at.isoformat(), "network_checks": {x.network_key: x.isolation_checks_json for x in networks}, "current_step": max((int(x.evidence_json.get("order_no", 0)) for x in latest_results.values()), default=len(latest_results)), "total_steps": len(request.spec_snapshot_json.get("steps", [])), "raw_score": raw_score, "max_score": int(request.spec_snapshot_json.get("total_score", 100)), "score": raw_score, "checkpoint_results": [self._checkpoint_view(x) for x in results]}

    async def destroy(self, instance_id: str, reason: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.destroy")
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        if group.status == "DESTROYED":
            return self.instance(instance_id)
        node = self.session.get(models.InfraNode, group.node_id)
        group.status = "DESTROYING"
        for sibling in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)):
            sibling.status = "STOPPING"
        self.session.commit()
        await self.agent_factory(node.agent_url).destroy(group.provider_group_id)
        stamp = now()
        group.status, group.destroyed_at = "DESTROYED", stamp
        for sibling in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)):
            sibling.status, sibling.ended_at = "DESTROYED", stamp
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id)
        request.status, request.updated_at, request.last_activity_at = "CANCELED", stamp, stamp
        self._event("lab.instance.destroyed", instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status="DESTROYED", reason=reason), idempotency_key=f"lab.instance.destroyed:{instance_id}")
        self.session.commit()
        return self.instance(instance_id)

    async def rebuild(self, instance_id: str, reason: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.rebuild")
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id)
        node = self.session.get(models.InfraNode, group.node_id)
        if group.provider_group_id:
            await self.agent_factory(node.agent_url).destroy(group.provider_group_id)
        spec = request.spec_snapshot_json
        result = await self.agent_factory(node.agent_url).create_group({"runtime_group_id": group.runtime_group_id, "expires_at": group.expires_at.isoformat(), "networks": spec["networks"], "containers": [{"node_key": x["node_key"], "role": x["role"], "image_digest": x["image_digest"], "cpu_limit": x["cpu_limit"], "memory_mb": x["memory_mb"], "pids_limit": 128, "startup_command": x.get("startup_command", "")} for x in spec["nodes"]]})
        group.provider_group_id, group.status = result["provider_group_id"], "RUNNING"
        existing = {x.node_key: x for x in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id))}
        for container in result["containers"]:
            instance = existing[container["node_key"]]
            instance.status, instance.started_at, instance.ended_at = "RUNNING", now(), None
            stored = self.session.scalar(select(models.RuntimeContainer).where(models.RuntimeContainer.runtime_instance_id == instance.runtime_instance_id))
            stored.provider_container_id, stored.status = container["container_id"], "RUNNING"
        request.last_activity_at = now()
        self._event("lab.instance.started", instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status="RUNNING", reason=reason, checkpoint_results_preserved=True), idempotency_key=f"lab.instance.started:{instance_id}:{int(item.started_at.timestamp())}")
        self.session.commit()
        return self.instance(instance_id)

    def extend(self, instance_id: str, data: RuntimeExtend) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.extend")
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        group.expires_at += timedelta(minutes=data.minutes)
        for sibling in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)):
            sibling.expires_at = group.expires_at
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id)
        request.last_activity_at = now()
        self._event("runtime.instance.extended", instance_id=instance_id, group_id=group.runtime_group_id, detail={"minutes": data.minutes, "reason": data.reason})
        self.session.commit()
        return self.instance(instance_id)

    async def rejudge(self, instance_id: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.rejudge")
        group = self.session.get(models.RuntimeInstanceGroup, item.runtime_group_id)
        request = self.session.get(models.RuntimeRequest, group.runtime_request_id)
        node = self.session.get(models.InfraNode, group.node_id)
        agent = self.agent_factory(node.agent_url)
        for checkpoint in request.spec_snapshot_json["checkpoints"]:
            result = await agent.exec(group.provider_group_id, {"operation": "judge", "checkpoint": checkpoint, "timeout_seconds": min(int(checkpoint["timeout_seconds"]), 30), "output_limit_bytes": 8192})
            attempt = (self.session.scalar(select(func.max(models.CheckpointResult.attempt)).where(models.CheckpointResult.runtime_instance_id == item.runtime_instance_id, models.CheckpointResult.checkpoint_id == checkpoint["checkpoint_id"])) or 0) + 1
            passed = bool(result.get("passed"))
            evidence = {**result.get("evidence", {}), "order_no": int(checkpoint.get("order_no", 0))}
            stored = models.CheckpointResult(checkpoint_result_id=new_id("cpr"), runtime_instance_id=item.runtime_instance_id, student_id=item.student_id, checkpoint_id=checkpoint["checkpoint_id"], attempt=attempt, status="PASSED" if passed else "FAILED", score_awarded=checkpoint["score"] if passed else 0, max_score=checkpoint["score"], evidence_json=evidence, message=result.get("message", "通过" if passed else checkpoint["failure_message"]), judged_at=now())
            self.session.add(stored)
            event_type = "lab.checkpoint.passed" if passed else "lab.checkpoint.failed"
            self._event(event_type, instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status=item.status, current_step=int(checkpoint.get("order_no", 0)), raw_score=stored.score_awarded, max_score=stored.max_score, source_id=stored.checkpoint_result_id, checkpoint_id=checkpoint["checkpoint_id"], checkpoint_status=stored.status, score_awarded=stored.score_awarded), idempotency_key=f"{event_type}:{instance_id}:{checkpoint['checkpoint_id']}:{attempt}")
        request.last_activity_at = now()
        self.session.commit()
        return self.instance(instance_id)

    def terminal_token(self, instance_id: str, idle_timeout_seconds: int) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.terminal")
        if item.role != "STUDENT_WORKSTATION" or item.status != "RUNNING":
            raise ApiError("RUNTIME.TERMINAL_NOT_ALLOWED", "终端只能连接运行中的学生操作机", 409)
        raw = token_urlsafe(32)
        expiry = now() + timedelta(seconds=min(idle_timeout_seconds, 300))
        self.session.add(models.RuntimeTerminalSession(terminal_session_id=new_id("rts"), runtime_instance_id=instance_id, user_id=self.user.user_id, token_hash=sha256(raw.encode()).hexdigest(), status="ISSUED", created_at=now(), expires_at=expiry, last_seen_at=None))
        self._event("runtime.terminal.token_issued", instance_id=instance_id, group_id=item.runtime_group_id, detail={"expires_at": expiry.isoformat()})
        self.session.commit()
        return {"token": raw, "expires_at": expiry.isoformat(), "runtime_instance_id": instance_id, "websocket_path": f"/api/v1/runtime-instances/{instance_id}/terminal"}

    def logs(self, instance_id: str) -> list[dict]:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item)
        events = self.session.scalars(select(models.RuntimeEvent).where((models.RuntimeEvent.runtime_instance_id == instance_id) | (models.RuntimeEvent.runtime_group_id == item.runtime_group_id)).order_by(models.RuntimeEvent.occurred_at))
        return [{"event_type": x.event_type, "actor_user_id": x.actor_user_id, "detail": x.detail_json, "occurred_at": x.occurred_at.isoformat()} for x in events]

    def artifacts(self, instance_id: str) -> list[dict]:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item)
        return [{"artifact_id": x.runtime_artifact_id, "type": x.artifact_type, "file_id": x.file_id, "sha256": x.sha256, "size_bytes": x.size_bytes} for x in self.session.scalars(select(models.RuntimeArtifact).where(models.RuntimeArtifact.runtime_instance_id == instance_id))]

    def nodes(self) -> list[dict]:
        self._permission("infrastructure.read")
        result = []
        for node in self.session.scalars(select(models.InfraNode).order_by(models.InfraNode.name)):
            hb = self.session.scalar(select(models.InfraNodeHeartbeat).where(models.InfraNodeHeartbeat.node_id == node.node_id).order_by(desc(models.InfraNodeHeartbeat.observed_at)).limit(1))
            result.append({"node_id": node.node_id, "name": node.name, "status": node.status, "scheduling_paused": node.scheduling_paused, "weight": node.weight, "cpu_total": node.cpu_total, "memory_total_mb": node.memory_total_mb, "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None, "capacity": {"cpu_available": hb.cpu_available, "memory_available_mb": hb.memory_available_mb, "running_groups": hb.running_groups, "image_digests": hb.image_digests_json} if hb else None})
        return result

    async def register_node(self, data: NodeRegister) -> dict:
        self._permission("infrastructure.write")
        client = self.agent_factory(data.agent_url)
        health, capacity = await client.health(), await client.capacity()
        if health.get("status") != "ok":
            raise ApiError("RUNTIME.NODE_NOT_READY", "节点代理健康检查未通过", 422)
        stamp = now()
        node = self.session.get(models.InfraNode, data.node_id) or models.InfraNode(node_id=data.node_id, name=data.name, agent_url=data.agent_url, status="READY", scheduling_paused=False, weight=data.weight, labels_json=data.labels, cpu_total=capacity["cpu_total"], memory_total_mb=capacity["memory_total_mb"], last_seen_at=stamp, created_at=stamp)
        node.name, node.agent_url, node.status, node.weight, node.labels_json, node.cpu_total, node.memory_total_mb, node.last_seen_at = data.name, data.agent_url, "READY", data.weight, data.labels, capacity["cpu_total"], capacity["memory_total_mb"], stamp
        self.session.add(node)
        self.session.add(models.InfraNodeHeartbeat(heartbeat_id=new_id("hbt"), node_id=node.node_id, observed_at=stamp, cpu_available=capacity["cpu_available"], memory_available_mb=capacity["memory_available_mb"], running_groups=capacity["running_groups"], image_digests_json=capacity.get("image_digests", []), detail_json={"engine": capacity.get("engine")}))
        self._event("infrastructure.node.registered", detail={"node_id": node.node_id, "name": node.name})
        self.session.commit()
        return next(x for x in self.nodes() if x["node_id"] == node.node_id)

    def images(self) -> list[dict]:
        self._permission("infrastructure.read")
        return [{"image_id": x.image_id, "name": x.name, "tag": x.tag, "digest": x.digest, "size_bytes": x.size_bytes, "scan_status": x.scan_status, "startup_check_status": x.startup_check_status, "teaching_validation_status": x.teaching_validation_status, "enabled": x.enabled} for x in self.session.scalars(select(models.InfraImage).order_by(models.InfraImage.name))]

    def register_image(self, data: ImageRegister) -> dict:
        self._permission("infrastructure.write")
        if data.enabled and {data.scan_status, data.startup_check_status, data.teaching_validation_status} != {"PASSED"}:
            raise ApiError("RUNTIME.IMAGE_VALIDATION_REQUIRED", "镜像通过扫描、启动自检和教学验证后才可启用", 422)
        item = self.session.get(models.InfraImage, data.image_id)
        if item and item.digest != data.digest:
            raise ApiError("RUNTIME.IMAGE_ID_CONFLICT", "镜像标识已绑定其他摘要", 409)
        if not item:
            item = models.InfraImage(image_id=data.image_id, name=data.name, tag=data.tag, digest=data.digest, size_bytes=data.size_bytes, scan_status=data.scan_status, startup_check_status=data.startup_check_status, teaching_validation_status=data.teaching_validation_status, enabled=data.enabled, created_at=now())
            self.session.add(item)
        else:
            item.name, item.tag, item.size_bytes = data.name, data.tag, data.size_bytes
            item.scan_status, item.startup_check_status, item.teaching_validation_status, item.enabled = data.scan_status, data.startup_check_status, data.teaching_validation_status, data.enabled
        for kind, status in (("SCAN", data.scan_status), ("STARTUP", data.startup_check_status), ("TEACHING", data.teaching_validation_status)):
            self.session.add(models.InfraImageValidation(validation_id=new_id("imv"), image_id=data.image_id, validation_type=kind, status=status, detail_json={}, validated_at=now()))
        self._event("infrastructure.image.registered", detail={"image_id": data.image_id, "digest": data.digest, "enabled": data.enabled})
        self.session.commit()
        return next(x for x in self.images() if x["image_id"] == data.image_id)

    def queue(self) -> list[dict]:
        self._permission("infrastructure.read")
        rows = self.session.execute(select(models.RuntimeQueue, models.RuntimeRequest).join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeQueue.runtime_request_id).where(models.RuntimeQueue.status == "WAITING").order_by(desc(models.RuntimeQueue.priority), models.RuntimeQueue.enqueued_at))
        return [{"queue_id": q.queue_id, "runtime_request_id": q.runtime_request_id, "status": q.status, "priority": q.priority, "attempts": q.attempts, "student_id": r.student_id, "reason": r.error_message, "enqueued_at": q.enqueued_at.isoformat()} for q, r in rows]

    def instances(self) -> list[dict]:
        self._permission("infrastructure.read")
        rows = self.session.execute(select(models.RuntimeInstance, models.RuntimeInstanceGroup, models.RuntimeRequest).join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeInstance.runtime_group_id).join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id).order_by(desc(models.RuntimeInstance.started_at)))
        return [{"runtime_instance_id": item.runtime_instance_id, "student_id": item.student_id, "lab_version_id": request.lab_version_id, "node_id": group.node_id, "node_key": item.node_key, "status": item.status, "started_at": item.started_at.isoformat() if item.started_at else None, "expires_at": item.expires_at.isoformat()} for item, group, request in rows]

    def infrastructure_overview(self) -> dict:
        self._permission("infrastructure.read")
        counts = {status: self.session.scalar(select(func.count()).select_from(models.RuntimeInstance).where(models.RuntimeInstance.status == status)) for status in ["RUNNING", "FAILED", "DESTROYED"]}
        return {"nodes_ready": self.session.scalar(select(func.count()).select_from(models.InfraNode).where(models.InfraNode.status == "READY", models.InfraNode.scheduling_paused.is_(False))), "running_instances": counts["RUNNING"], "failed_instances": counts["FAILED"], "destroyed_instances": counts["DESTROYED"], "queued_groups": self.session.scalar(select(func.count()).select_from(models.RuntimeQueue).where(models.RuntimeQueue.status == "WAITING"))}

    def recent_events(self) -> list[dict]:
        self._permission("infrastructure.read")
        return [{"event_type": x.event_type, "runtime_instance_id": x.runtime_instance_id, "detail": x.detail_json, "occurred_at": x.occurred_at.isoformat()} for x in self.session.scalars(select(models.RuntimeEvent).order_by(desc(models.RuntimeEvent.occurred_at)).limit(100))]

    def _release_requests(self, release_id: str) -> list[models.RuntimeRequest]:
        return list(self.session.scalars(select(models.RuntimeRequest).where(models.RuntimeRequest.lab_release_id == release_id).order_by(desc(models.RuntimeRequest.created_at))))

    def release_summary(self, release_id: str) -> dict:
        self._permission("runtime.read")
        requests = self._release_requests(release_id)
        context = self.session.get(models.RuntimeReleaseReadModel, release_id)
        if not requests and not context:
            raise ApiError("RUNTIME.RELEASE_CONTEXT_REQUIRED", "运行底座尚未收到该实验发布的冻结版本上下文", 409, {"lab_release_id": release_id, "required_source": "C lab.release.published 或教师预演"})
        course_id = requests[0].course_id if requests else context.course_id
        class_id = requests[0].class_id if requests else context.class_id
        version_id = requests[0].lab_version_id if requests else context.lab_version_id
        if class_id and self.user.role == "teacher" and class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权查看该班级运行情况", 403)
        latest: dict[str, models.RuntimeRequest] = {}
        for item in requests:
            if item.student_id and item.student_id not in latest:
                latest[item.student_id] = item
        counts = {state: sum(1 for x in latest.values() if x.status == state) for state in ["QUEUED", "SCHEDULING", "STARTING", "RUNNING", "FAILED", "CANCELED"]}
        updated = max((x.updated_at for x in requests), default=context.updated_at if context else now())
        return {"lab_release_id": release_id, "lab_version_id": version_id, "course_id": course_id, "class_id": class_id, "release_status": context.status if context else "OPEN", "student_count": len(latest), "status_counts": counts, "running_count": counts["RUNNING"], "queued_count": counts["QUEUED"], "failed_count": counts["FAILED"], "submitted_count": sum(1 for x in latest.values() if x.submission_status == "SUBMITTED"), "updated_at": updated.isoformat()}

    def release_students(self, release_id: str) -> dict:
        summary = self.release_summary(release_id)
        latest: dict[str, models.RuntimeRequest] = {}
        for item in self._release_requests(release_id):
            if item.student_id and item.student_id not in latest:
                latest[item.student_id] = item
        items = [self._release_student_view(item) for item in latest.values()]
        return {"items": items, "page": 1, "page_size": len(items), "total": len(items), "lab_release_id": release_id, "course_id": summary["course_id"], "class_id": summary["class_id"]}

    def release_student(self, release_id: str, student_id: str) -> dict:
        self._permission("runtime.read")
        if self.user.role == "student" and student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能查看自己的实验运行状态", 403)
        item = self.session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.lab_release_id == release_id, models.RuntimeRequest.student_id == student_id).order_by(desc(models.RuntimeRequest.created_at)).limit(1))
        if not item:
            raise ApiError("RUNTIME.STUDENT_NOT_STARTED", "该学生尚未启动实验", 404)
        if item.class_id and self.user.role == "teacher" and item.class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权查看该班级运行情况", 403)
        return self._release_student_view(item)

    def _release_student_view(self, request: models.RuntimeRequest) -> dict:
        group = self.session.scalar(select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_request_id == request.runtime_request_id))
        instance = self.session.scalar(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id, models.RuntimeInstance.role == "STUDENT_WORKSTATION")) if group else None
        if not instance:
            view = self.request_view(request)
            return {**view, "runtime_instance_id": None, "current_step": 0, "total_steps": len(request.spec_snapshot_json.get("steps", [])), "raw_score": 0, "max_score": int(request.spec_snapshot_json.get("total_score", 100))}
        return self.instance(instance.runtime_instance_id)

    async def start_release(self, release_id: str, student_id: str) -> dict:
        self._permission("runtime.start")
        active = self.session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.lab_release_id == release_id, models.RuntimeRequest.student_id == student_id, models.RuntimeRequest.status.in_(["QUEUED", "SCHEDULING", "STARTING", "RUNNING"])).order_by(desc(models.RuntimeRequest.created_at)).limit(1))
        if active:
            return self.request_view(active)
        context = self.session.get(models.RuntimeReleaseReadModel, release_id)
        source = self.session.scalar(select(models.RuntimeRequest).where(models.RuntimeRequest.lab_release_id == release_id).order_by(desc(models.RuntimeRequest.created_at)).limit(1))
        if not source and not context:
            raise ApiError("RUNTIME.RELEASE_CONTEXT_REQUIRED", "缺少发布版本上下文，不能仅凭学生标识启动", 409, {"lab_release_id": release_id, "required_fields": ["lab_version_id", "course_id", "class_id"]})
        version_id = source.lab_version_id if source else context.lab_version_id
        course_id = (source.course_id if source else context.course_id) or (next(iter(self.user.course_ids)) if len(self.user.course_ids) == 1 else None)
        class_id = (source.class_id if source else context.class_id) or (next(iter(self.user.class_ids)) if len(self.user.class_ids) == 1 else None)
        if not course_id or not class_id:
            raise ApiError("RUNTIME.RELEASE_CONTEXT_REQUIRED", "发布上下文缺少课程或班级标识", 409)
        return await self.start(RuntimeStart(lab_release_id=release_id, lab_version_id=version_id, course_id=course_id, class_id=class_id, student_id=student_id, mode="STUDENT"), f"release-start:{release_id}:{student_id}")

    async def register_release_context(self, *, release_id: str, version_id: str, course_id: str, class_id: str, status: str, spec_snapshot: dict | None = None) -> dict:
        spec = spec_snapshot or await self.catalog.frozen_version(version_id, course_id)
        self._validate_spec(spec, version_id)
        stamp = now()
        item = self.session.get(models.RuntimeReleaseReadModel, release_id)
        if item and item.lab_version_id != version_id:
            raise ApiError("RUNTIME.RELEASE_VERSION_IMMUTABLE", "已登记发布不可切换实验版本", 409)
        if not item:
            item = models.RuntimeReleaseReadModel(lab_release_id=release_id, lab_version_id=version_id, course_id=course_id, class_id=class_id, status=status, spec_snapshot_json=spec, published_at=stamp, updated_at=stamp)
            self.session.add(item)
        else:
            item.status, item.updated_at = status, stamp
        self._event("runtime.release.context_updated", detail={"lab_release_id": release_id, "lab_version_id": version_id, "course_id": course_id, "class_id": class_id, "status": status})
        self.session.commit()
        return self.release_summary(release_id)

    def submit_release(self, release_id: str, student_id: str, instance_id: str | None) -> dict:
        self._permission("runtime.submit")
        detail = self.release_student(release_id, student_id)
        if instance_id and detail.get("runtime_instance_id") != instance_id:
            raise ApiError("RUNTIME.INSTANCE_MISMATCH", "提交的实例不属于该学生和实验发布", 409)
        request = self.session.get(models.RuntimeRequest, detail["runtime_request_id"])
        if request.submission_status == "SUBMITTED":
            return self._release_student_view(request)
        stamp = now()
        request.submission_status, request.submitted_at, request.last_activity_at, request.updated_at = "SUBMITTED", stamp, stamp, stamp
        instance = self.session.get(models.RuntimeInstance, detail["runtime_instance_id"]) if detail.get("runtime_instance_id") else None
        self._event("lab.submitted", instance_id=instance.runtime_instance_id if instance else None, group_id=instance.runtime_group_id if instance else None, detail=self._projection_payload(request, instance, status=instance.status if instance else request.status, current_step=len(request.spec_snapshot_json.get("steps", [])), raw_score=detail.get("raw_score", 0), max_score=detail.get("max_score", 100), source_id=request.runtime_request_id, submission_status="SUBMITTED", submitted_at=stamp.isoformat()), idempotency_key=f"lab.submitted:{release_id}:{student_id}")
        self.session.commit()
        return self._release_student_view(request)

    def signal_action(self, instance_id: str, action: str, reason: str | None = None) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, f"runtime.{action}")
        self._event(f"runtime.instance.{action}", instance_id=instance_id, group_id=item.runtime_group_id, detail={"reason": reason or "课堂操作"})
        self.session.commit()
        return {"runtime_instance_id": instance_id, "action": action, "status": "ACCEPTED"}

    def runtime_logs(self, *, class_id: str = "", release_id: str = "", student_id: str = "") -> dict:
        self._permission("runtime.read")
        if class_id and class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权查看该班级运行日志", 403)
        query = select(models.RuntimeEvent, models.RuntimeRequest).join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeEvent.runtime_group_id).join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id)
        if class_id: query = query.where(models.RuntimeRequest.class_id == class_id)
        if release_id: query = query.where(models.RuntimeRequest.lab_release_id == release_id)
        if student_id: query = query.where(models.RuntimeRequest.student_id == student_id)
        rows = self.session.execute(query.order_by(desc(models.RuntimeEvent.occurred_at)).limit(500))
        items = [{"event_id": event.runtime_event_id, "event_type": event.event_type, "runtime_instance_id": event.runtime_instance_id, "lab_release_id": request.lab_release_id, "course_id": request.course_id, "class_id": request.class_id, "student_id": request.student_id, "detail": event.detail_json, "occurred_at": event.occurred_at.isoformat()} for event, request in rows]
        return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}

    def traffic_logs(self, *, class_id: str = "", release_id: str = "", student_id: str = "") -> dict:
        self._permission("runtime.read")
        if class_id and class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权查看该班级流量制品", 403)
        query = select(models.RuntimeArtifact, models.RuntimeRequest).join(models.RuntimeInstance, models.RuntimeInstance.runtime_instance_id == models.RuntimeArtifact.runtime_instance_id).join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeInstance.runtime_group_id).join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id).where(models.RuntimeArtifact.artifact_type == "TRAFFIC")
        if class_id: query = query.where(models.RuntimeRequest.class_id == class_id)
        if release_id: query = query.where(models.RuntimeRequest.lab_release_id == release_id)
        if student_id: query = query.where(models.RuntimeRequest.student_id == student_id)
        rows = self.session.execute(query.order_by(desc(models.RuntimeArtifact.capture_ended_at)).limit(500))
        items = [{"artifact_id": artifact.runtime_artifact_id, "name": f"流量记录-{artifact.runtime_artifact_id}.pcap", "runtime_instance_id": artifact.runtime_instance_id, "lab_release_id": request.lab_release_id, "course_id": request.course_id, "class_id": request.class_id, "student_id": request.student_id, "file_id": artifact.file_id, "sha256": artifact.sha256, "size_bytes": artifact.size_bytes, "occurred_at": artifact.capture_ended_at.isoformat() if artifact.capture_ended_at else None} for artifact, request in rows]
        return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}

    def class_read_model(self, class_id: str) -> dict:
        self._permission("runtime.read")
        if self.user.role == "teacher" and class_id not in self.user.class_ids:
            raise ApiError("AUTH.CLASS_SCOPE_DENIED", "无权查看该班级运行统计", 403)
        requests = list(self.session.scalars(select(models.RuntimeRequest).where(models.RuntimeRequest.class_id == class_id).order_by(desc(models.RuntimeRequest.created_at))))
        latest: dict[str, models.RuntimeRequest] = {}
        for request in requests:
            if request.student_id and request.student_id not in latest:
                latest[request.student_id] = request
        return {"class_id": class_id, "summary": {status: sum(1 for x in latest.values() if x.status == status) for status in ["RUNNING", "QUEUED", "FAILED", "DESTROYED"]}, "students": [{"student_id": student_id, "runtime_request_id": x.runtime_request_id, "status": x.status, "updated_at": x.updated_at.isoformat()} for student_id, x in latest.items()]}

    def student_read_model(self, student_id: str) -> dict:
        self._permission("runtime.read")
        if self.user.role == "student" and student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "学生只能查看自己的运行统计", 403)
        requests = list(self.session.scalars(select(models.RuntimeRequest).where(models.RuntimeRequest.student_id == student_id).order_by(desc(models.RuntimeRequest.created_at))))
        scores = self.session.execute(select(func.coalesce(func.sum(models.CheckpointResult.score_awarded), 0), func.coalesce(func.sum(models.CheckpointResult.max_score), 0)).where(models.CheckpointResult.student_id == student_id)).one()
        return {"student_id": student_id, "total_requests": len(requests), "latest_status": requests[0].status if requests else None, "checkpoint_score_awarded": int(scores[0]), "checkpoint_score_possible": int(scores[1]), "updated_at": requests[0].updated_at.isoformat() if requests else None}

    @staticmethod
    def _checkpoint_view(item: models.CheckpointResult) -> dict:
        return {"checkpoint_result_id": item.checkpoint_result_id, "checkpoint_id": item.checkpoint_id, "attempt": item.attempt, "status": item.status, "score_awarded": item.score_awarded, "max_score": item.max_score, "evidence": item.evidence_json, "message": item.message, "judged_at": item.judged_at.isoformat()}

    @staticmethod
    def _display_status(status: str) -> str:
        return {"QUEUED": "排队中", "SCHEDULING": "调度中", "STARTING": "启动中", "RUNNING": "运行中", "FAILED": "失败", "CANCELED": "已取消", "CREATED": "已创建", "STOPPING": "停止中", "DESTROYED": "已销毁"}.get(status, status)
