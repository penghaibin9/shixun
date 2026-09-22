import re
import os
import json
from urllib.parse import quote
from time import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import DomainEventOutbox, FileObject
from app.common.outbox import enqueue_event
from app.common.signed_capability import sign_capability, verify_capability

from . import models
from .artifact_storage import BundleEntry, build_bundle, store_capture_artifact
from .catalog import LabCatalogClient
from .provider import NodeAgentClient
from .schemas import ArtifactStorageClaims, DistributionDownloadClaims, ImageRegister, NodeRegister, RuntimeExtend, RuntimeMaintenanceRun, RuntimeStart


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")


def _reference_digest(references: list[dict]) -> str:
    return sha256(_canonical_json_bytes({"references": references})).hexdigest()


ALLOWED_TRANSITIONS = {
    "QUEUED": {"SCHEDULING", "CANCELED", "FAILED"},
    "SCHEDULING": {"STARTING", "QUEUED", "FAILED"},
    "STARTING": {"RUNNING", "FAILED"},
    "RUNNING": {"FAILED", "CANCELED"},
    "FAILED": {"SCHEDULING", "CANCELED"},
    "CANCELED": set(),
    "DESTROYED": set(),
}
QUEUE_LEASE_SECONDS = 240
ADMIN_ACTION_LEASE_SECONDS = 300
LEASE_ERROR_CODES = {"RUNTIME.QUEUE_LEASE_LOST", "RUNTIME.RECOVERY_LEASE_LOST", "RUNTIME.PROVISION_LEASE_LOST"}


class RuntimeService:
    def __init__(self, session: Session, user: UserContext, catalog: LabCatalogClient | None = None, agent_factory=None):
        self.session = session
        self.user = user
        self.catalog = catalog or LabCatalogClient()
        self.agent_factory = agent_factory or (lambda url: NodeAgentClient(url))

    def _permission(self, name: str) -> None:
        if name not in self.user.permissions:
            raise ApiError("AUTH.FORBIDDEN", "当前账号没有此操作权限", 403, {"required_permission": name})

    def _admin_control(self) -> None:
        self._permission("infrastructure.write")
        if self.user.role != "admin":
            raise ApiError("AUTH.ADMIN_REQUIRED", "仅管理员可执行运行底座恢复操作", 403)

    def _claim_admin_action(self, action_type: str, target_id: str, action_key: str, request_json: dict) -> tuple[models.RuntimeAdminAction, bool]:
        def load(*, lock: bool = False) -> models.RuntimeAdminAction | None:
            query = select(models.RuntimeAdminAction).where(
                    models.RuntimeAdminAction.actor_user_id == self.user.user_id,
                    models.RuntimeAdminAction.idempotency_key == action_key,
                )
            if lock:
                query = query.with_for_update().execution_options(populate_existing=True)
            return self.session.scalar(query)

        action = load(lock=True)
        if action:
            self._validate_admin_action(action, action_type, target_id, request_json)
            if action.status == "IN_PROGRESS" and action.lease_expires_at <= now():
                action.status = "FAILED"
                action.error_code = "RUNTIME.RECOVERY_INTERRUPTED"
                action.error_message = "恢复动作租约已过期，请使用新的幂等键重试"
                action.error_status_code = 503
                action.error_details_json = {"action_id": action.action_id}
                action.updated_at = now()
                self.session.commit()
            return action, False
        stamp = now()
        action = models.RuntimeAdminAction(
            action_id=new_id("raa"), actor_user_id=self.user.user_id, idempotency_key=action_key,
            action_type=action_type, target_id=target_id, request_json=request_json, status="IN_PROGRESS",
            owner_token=uuid4().hex, generation=1, lease_expires_at=stamp + timedelta(seconds=ADMIN_ACTION_LEASE_SECONDS),
            result_json=None, error_code=None, error_message=None, error_status_code=None,
            error_details_json=None,
            created_at=stamp, updated_at=stamp,
        )
        self.session.add(action)
        try:
            self.session.commit()
            return action, True
        except IntegrityError:
            self.session.rollback()
            action = load(lock=True)
            if not action:
                raise
            self._validate_admin_action(action, action_type, target_id, request_json)
            return action, False

    @staticmethod
    def _validate_admin_action(action: models.RuntimeAdminAction, action_type: str, target_id: str, request_json: dict) -> None:
        if action.action_type != action_type or action.target_id != target_id or action.request_json != request_json:
            raise ApiError("RUNTIME.IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他恢复动作或参数", 409)

    @staticmethod
    def _validate_destroy_result(result: dict, expected_group_id: str) -> None:
        if (
            not isinstance(result, dict)
            or result.get("status") != "DESTROYED"
            or result.get("provider_group_id") != expected_group_id
        ):
            raise ApiError("RUNTIME.PROVIDER_RESPONSE_INVALID", "计算节点代理销毁响应无效", 503)

    @staticmethod
    def _validate_create_result(result: dict, spec: dict, expected_group_id: str) -> None:
        def bounded_string(value, max_length: int) -> bool:
            return isinstance(value, str) and bool(value.strip()) and len(value) <= max_length

        valid = (
            isinstance(result, dict) and result.get("provider_group_id") == expected_group_id
            and result.get("status") == "RUNNING"
            and isinstance(result.get("containers"), list) and isinstance(result.get("networks"), list)
            and all(
                isinstance(item, dict)
                and bounded_string(item.get("container_id"), 128)
                and bounded_string(item.get("node_key"), 64)
                for item in result["containers"]
            )
            and all(
                isinstance(item, dict)
                and bounded_string(item.get("network_id"), 128)
                and bounded_string(item.get("network_key"), 64)
                for item in result["networks"]
            )
        )
        if valid:
            node_keys = [item["node_key"] for item in result["containers"]]
            network_keys = [item["network_key"] for item in result["networks"]]
            container_ids = [item["container_id"] for item in result["containers"]]
            network_ids = [item["network_id"] for item in result["networks"]]
            valid = (
                len(node_keys) == len(set(node_keys)) == len(spec["nodes"])
                and set(node_keys) == {item["node_key"] for item in spec["nodes"]}
                and len(container_ids) == len(set(container_ids))
                and len(network_keys) == len(set(network_keys)) == len(spec["networks"])
                and set(network_keys) == {item["network_key"] for item in spec["networks"]}
                and len(network_ids) == len(set(network_ids))
            )
        if not valid:
            raise ApiError("RUNTIME.PROVIDER_RESPONSE_INVALID", "计算节点代理创建响应无效", 503)

    @staticmethod
    def _validate_capture_start_result(result: dict, expected_group_id: str) -> None:
        if (
            not isinstance(result, dict)
            or result.get("provider_group_id") != expected_group_id
            or result.get("status") != "CAPTURING"
            or not re.fullmatch(r"cap_[0-9a-f]{32}", str(result.get("capture_id", "")))
            or not isinstance(result.get("started_at"), str)
            or not isinstance(result.get("idempotent_replay"), bool)
        ):
            raise ApiError("RUNTIME.CAPTURE_RESPONSE_INVALID", "节点代理抓包启动响应无效", 503)

    @staticmethod
    def _capture_datetime(value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError) as error:
            raise ApiError("RUNTIME.CAPTURE_RESPONSE_INVALID", f"节点代理抓包{field}无效", 503) from error

    @classmethod
    def _validate_capture_stop_result(cls, result: dict, expected_group_id: str) -> dict:
        if (
            not isinstance(result, dict)
            or result.get("provider_group_id") != expected_group_id
            or result.get("status") != "COMPLETED"
            or not re.fullmatch(r"cap_[0-9a-f]{32}", str(result.get("capture_id", "")))
            or result.get("file_id") != f"{result.get('capture_id')}.pcap"
            or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("sha256", "")))
            or isinstance(result.get("size_bytes"), bool)
            or not isinstance(result.get("size_bytes"), int)
            or not 24 < result["size_bytes"] <= 128 * 1024 * 1024
            or isinstance(result.get("packet_count"), bool)
            or not isinstance(result.get("packet_count"), int)
            or result["packet_count"] < 1
        ):
            raise ApiError("RUNTIME.CAPTURE_RESPONSE_INVALID", "节点代理抓包停止响应无效", 503)
        started_at = cls._capture_datetime(result.get("started_at"), "开始时间")
        ended_at = cls._capture_datetime(result.get("ended_at"), "结束时间")
        if ended_at < started_at:
            raise ApiError("RUNTIME.CAPTURE_RESPONSE_INVALID", "节点代理抓包时间范围无效", 503)
        return {**result, "capture_started_at": started_at, "capture_ended_at": ended_at}

    @staticmethod
    def _validate_capture_artifact(result: dict, stopped: dict) -> bytes:
        content = result.get("content") if isinstance(result, dict) else None
        content_length = result.get("content_length") if isinstance(result, dict) else None
        if content_length not in (None, ""):
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError) as error:
                raise ApiError("RUNTIME.CAPTURE_ARTIFACT_INVALID", "节点抓包下载长度响应无效", 503) from error
        else:
            declared_length = stopped["size_bytes"]
        if (
            not isinstance(content, bytes)
            or not str(result.get("content_type", "")).split(";", 1)[0].strip() == "application/vnd.tcpdump.pcap"
            or result.get("capture_id") != stopped["capture_id"]
            or result.get("sha256") != stopped["sha256"]
            or declared_length != stopped["size_bytes"]
            or len(content) != stopped["size_bytes"]
            or sha256(content).hexdigest() != stopped["sha256"]
        ):
            raise ApiError("RUNTIME.CAPTURE_ARTIFACT_INVALID", "节点抓包下载内容与停止摘要不一致", 503)
        return content

    async def _capture_before_cleanup(self, agent, provider_group_id: str, runtime_group_id: str) -> dict:
        primary = self.session.scalar(
            select(models.RuntimeInstance)
            .where(
                models.RuntimeInstance.runtime_group_id == runtime_group_id,
                models.RuntimeInstance.role == "STUDENT_WORKSTATION",
            )
            .order_by(models.RuntimeInstance.runtime_instance_id)
        )
        if not primary:
            return {"status": "SKIPPED", "reason": "NO_STUDENT_INSTANCE"}
        instance_id = primary.runtime_instance_id
        student_id = primary.student_id
        try:
            stopped = self._validate_capture_stop_result(
                await agent.capture_stop(provider_group_id), provider_group_id
            )
            content = self._validate_capture_artifact(
                await agent.capture_artifact(provider_group_id), stopped
            )
            object_key = store_capture_artifact(content, stopped["sha256"], stopped["size_bytes"])
            existing_artifact = self.session.scalar(
                select(models.RuntimeArtifact).where(
                    models.RuntimeArtifact.runtime_instance_id == instance_id,
                    models.RuntimeArtifact.artifact_type == "TRAFFIC",
                    models.RuntimeArtifact.sha256 == stopped["sha256"],
                    models.RuntimeArtifact.size_bytes == stopped["size_bytes"],
                )
            )
            if existing_artifact:
                file_object = self.session.get(FileObject, existing_artifact.file_id)
                if (
                    not file_object
                    or file_object.storage_provider != "local"
                    or file_object.bucket != "runtime-artifacts"
                    or file_object.object_key != object_key
                    or file_object.sha256 != stopped["sha256"]
                    or file_object.size_bytes != stopped["size_bytes"]
                ):
                    raise ApiError("RUNTIME.ARTIFACT_REGISTRATION_MISMATCH", "既有流量制品登记与真实文件不一致", 409)
                return {"status": "COMPLETED", "artifact_id": existing_artifact.runtime_artifact_id, "idempotent_replay": True}

            file_object = self.session.scalar(
                select(FileObject).where(
                    FileObject.sha256 == stopped["sha256"],
                    FileObject.size_bytes == stopped["size_bytes"],
                )
            )
            if file_object and (
                file_object.storage_provider != "local"
                or file_object.bucket != "runtime-artifacts"
                or file_object.object_key != object_key
            ):
                raise ApiError("RUNTIME.ARTIFACT_REGISTRATION_MISMATCH", "相同内容已登记到其他存储位置", 409)
            if not file_object:
                file_object = FileObject(
                    file_id=new_id("fil"), storage_provider="local", bucket="runtime-artifacts",
                    object_key=object_key, original_name=f"流量记录-{stopped['capture_id']}.pcap",
                    mime_type="application/vnd.tcpdump.pcap", size_bytes=stopped["size_bytes"],
                    sha256=stopped["sha256"], created_by=self.user.user_id, created_at=now(),
                )
                self.session.add(file_object)
            artifact = models.RuntimeArtifact(
                runtime_artifact_id=new_id("rta"), runtime_instance_id=instance_id,
                student_id=student_id, artifact_type="TRAFFIC", file_id=file_object.file_id,
                sha256=stopped["sha256"], size_bytes=stopped["size_bytes"],
                capture_started_at=stopped["capture_started_at"], capture_ended_at=stopped["capture_ended_at"],
            )
            self.session.add(artifact)
            self._event(
                "runtime.capture.completed", instance_id=instance_id, group_id=runtime_group_id,
                detail={
                    "artifact_id": artifact.runtime_artifact_id,
                    "capture_id": stopped["capture_id"],
                    "sha256": stopped["sha256"],
                    "size_bytes": stopped["size_bytes"],
                    "packet_count": stopped["packet_count"],
                },
            )
            self.session.commit()
            return {"status": "COMPLETED", "artifact_id": artifact.runtime_artifact_id, "idempotent_replay": False}
        except Exception as raw_error:
            self.session.rollback()
            if isinstance(raw_error, ApiError):
                error = raw_error
            elif isinstance(raw_error, IntegrityError):
                error = ApiError("RUNTIME.ARTIFACT_REGISTRATION_FAILED", "流量制品登记冲突", 503)
            else:
                error = ApiError("RUNTIME.CAPTURE_FINALIZATION_FAILED", "流量采集结束处理失败", 503)
            try:
                self._event(
                    "runtime.capture.failed", instance_id=instance_id, group_id=runtime_group_id,
                    detail={"provider_group_id": provider_group_id, "error_code": error.code, "message": error.message},
                )
                self.session.commit()
            except Exception:
                # 采集审计本身不可用时也不能阻断随后对运行组的安全销毁。
                self.session.rollback()
            return {"status": "FAILED", "error_code": error.code, "message": error.message}

    @staticmethod
    def _provider_group_id(runtime_group_id: str, generation: int) -> str:
        return runtime_group_id if generation == 1 else f"{runtime_group_id}-g{generation}"

    @staticmethod
    def _validate_capacity_result(result: dict) -> dict:
        if not isinstance(result, dict):
            raise ApiError("RUNTIME.NODE_RESPONSE_INVALID", "节点代理容量响应无效", 503)
        engine = result.get("engine")
        cpu_total = result.get("cpu_total")
        memory_total = result.get("memory_total_mb")
        cpu = result.get("cpu_available")
        memory = result.get("memory_available_mb")
        running = result.get("running_groups")
        digests = result.get("image_digests")
        max_database_integer = 2_147_483_647
        max_supported_cpu = 1_000_000.0
        if (
            not isinstance(engine, str) or not engine.strip() or len(engine) > 128
            or isinstance(cpu_total, bool) or not isinstance(cpu_total, (int, float))
            or not isfinite(float(cpu_total)) or not 0 <= float(cpu_total) <= max_supported_cpu
            or isinstance(memory_total, bool) or not isinstance(memory_total, int)
            or not 0 <= memory_total <= max_database_integer
            or isinstance(cpu, bool) or not isinstance(cpu, (int, float))
            or not isfinite(float(cpu)) or not 0 <= float(cpu) <= max_supported_cpu
            or float(cpu) > float(cpu_total)
            or isinstance(memory, bool) or not isinstance(memory, int)
            or not 0 <= memory <= memory_total
            or isinstance(running, bool) or not isinstance(running, int)
            or not 0 <= running <= max_database_integer
            or not isinstance(digests, list)
            or any(
                not isinstance(digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                for digest in digests
            )
        ):
            raise ApiError("RUNTIME.NODE_RESPONSE_INVALID", "节点代理容量响应无效", 503)
        return {
            "engine": engine,
            "cpu_total": float(cpu_total),
            "memory_total_mb": memory_total,
            "cpu_available": float(cpu),
            "memory_available_mb": memory,
            "running_groups": running,
            "image_digests": digests,
        }

    @staticmethod
    def _admin_action_replay(action: models.RuntimeAdminAction) -> dict:
        if action.status == "SUCCEEDED":
            return {**(action.result_json or {}), "idempotent_replay": True}
        if action.status == "FAILED":
            raise ApiError(
                action.error_code or "RUNTIME.RECOVERY_FAILED",
                action.error_message or "恢复动作执行失败",
                action.error_status_code or 503,
                {**(action.error_details_json or {}), "idempotent_replay": True},
            )
        raise ApiError(
            "RUNTIME.RECOVERY_IN_PROGRESS", "相同幂等键的恢复动作仍在执行", 409,
            {"action_id": action.action_id, "retryable": True},
        )

    def _renew_admin_action(self, action: models.RuntimeAdminAction, *, lease_seconds: int = ADMIN_ACTION_LEASE_SECONDS) -> models.RuntimeAdminAction:
        expected_owner = action.owner_token
        expected_generation = action.generation
        current = self.session.scalar(
            select(models.RuntimeAdminAction).where(models.RuntimeAdminAction.action_id == action.action_id).with_for_update().execution_options(populate_existing=True)
        )
        stamp = now()
        if (
            not current or current.status != "IN_PROGRESS" or current.owner_token != expected_owner
            or current.generation != expected_generation or current.lease_expires_at <= stamp
        ):
            raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "恢复动作执行权已失效", 409)
        current.lease_expires_at = stamp + timedelta(seconds=lease_seconds)
        current.updated_at = stamp
        self.session.commit()
        return current

    def _complete_admin_action(self, action: models.RuntimeAdminAction, result: dict) -> None:
        expected_owner = action.owner_token
        expected_generation = action.generation
        current = self.session.scalar(
            select(models.RuntimeAdminAction).where(models.RuntimeAdminAction.action_id == action.action_id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not current or current.status != "IN_PROGRESS" or current.owner_token != expected_owner
            or current.generation != expected_generation or current.lease_expires_at <= now()
        ):
            raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "恢复动作执行权已失效", 409)
        current.status = "SUCCEEDED"
        current.result_json = {**result, "idempotent_replay": False}
        current.error_code = current.error_message = None
        current.error_status_code = None
        current.error_details_json = None
        current.updated_at = now()

    def _fail_admin_action(self, action: models.RuntimeAdminAction, error: ApiError) -> None:
        expected_owner = action.owner_token
        expected_generation = action.generation
        current = self.session.scalar(
            select(models.RuntimeAdminAction).where(models.RuntimeAdminAction.action_id == action.action_id).with_for_update().execution_options(populate_existing=True)
        )
        if (
            not current or current.status != "IN_PROGRESS" or current.owner_token != expected_owner
            or current.generation != expected_generation
        ):
            return
        current.status = "FAILED"
        current.result_json = None
        current.error_code = error.code
        current.error_message = error.message
        current.error_status_code = error.status_code
        current.error_details_json = error.details
        current.updated_at = now()

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

    def _renew_queue_lease(self, request_id: str, owner: str) -> models.RuntimeQueue:
        queued = self.session.scalar(
            select(models.RuntimeQueue)
            .where(models.RuntimeQueue.runtime_request_id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stamp = now()
        if (
            not queued or queued.status != "PROCESSING" or queued.processing_owner != owner
            or not queued.lease_expires_at or queued.lease_expires_at <= stamp
        ):
            raise ApiError("RUNTIME.QUEUE_LEASE_LOST", "运行队列处理租约已失效", 409)
        action = self.session.scalar(
            select(models.RuntimeAdminAction).where(
                models.RuntimeAdminAction.owner_token == owner,
                models.RuntimeAdminAction.status == "IN_PROGRESS",
            ).with_for_update().execution_options(populate_existing=True)
        )
        if not action or action.lease_expires_at <= stamp:
            raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "恢复动作执行权已失效", 409)
        queued.lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
        action.lease_expires_at = stamp + timedelta(seconds=ADMIN_ACTION_LEASE_SECONDS)
        action.updated_at = stamp
        self.session.commit()
        return queued

    def _assert_queue_lease(self, request_id: str, owner: str) -> models.RuntimeQueue:
        queued = self.session.scalar(
            select(models.RuntimeQueue)
            .where(models.RuntimeQueue.runtime_request_id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not queued or queued.status != "PROCESSING" or queued.processing_owner != owner
            or not queued.lease_expires_at or queued.lease_expires_at <= now()
        ):
            raise ApiError("RUNTIME.QUEUE_LEASE_LOST", "运行队列处理租约已失效", 409)
        action = self.session.scalar(select(models.RuntimeAdminAction).where(models.RuntimeAdminAction.owner_token == owner))
        if not action or action.status != "IN_PROGRESS" or action.lease_expires_at <= now():
            raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "恢复动作执行权已失效", 409)
        return queued

    def _renew_request_provision(self, request_id: str, owner: str) -> models.RuntimeRequest:
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stamp = now()
        if (
            not request or request.status != "SCHEDULING" or request.provision_owner != owner
            or not request.provision_lease_expires_at or request.provision_lease_expires_at <= stamp
        ):
            raise ApiError("RUNTIME.PROVISION_LEASE_LOST", "实验环境创建执行权已失效", 409)
        request.provision_lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
        request.updated_at = stamp
        self.session.commit()
        return request

    def _lock_provision_owner(
        self, request_id: str, group_id: str, owner: str, *, renew: bool = False
    ) -> tuple[models.RuntimeInstanceGroup, models.RuntimeRequest]:
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stamp = now()
        if (
            not group or not request or group.status != "STARTING" or group.cleanup_intent != "PROVISIONING"
            or group.cleanup_owner != owner or not group.cleanup_lease_expires_at
            or group.cleanup_lease_expires_at <= stamp
            or request.provision_owner != owner or not request.provision_lease_expires_at
            or request.provision_lease_expires_at <= stamp
        ):
            raise ApiError("RUNTIME.PROVISION_LEASE_LOST", "实验环境创建执行权已失效", 409)
        if renew:
            group.cleanup_lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
            group.cleanup_not_before = group.cleanup_lease_expires_at
            request.provision_lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
        return group, request

    def _record_cleanup_task(
        self,
        *,
        runtime_group_id: str,
        node_id: str,
        provider_group_id: str,
        provider_generation: int,
        intent: str,
        error: ApiError,
    ) -> models.RuntimeCleanupTask:
        self.session.rollback()
        stamp = now()
        task = self.session.scalar(
            select(models.RuntimeCleanupTask)
            .where(
                models.RuntimeCleanupTask.node_id == node_id,
                models.RuntimeCleanupTask.provider_group_id == provider_group_id,
                models.RuntimeCleanupTask.intent == intent,
            )
            .with_for_update()
        )
        if not task:
            task = models.RuntimeCleanupTask(
                cleanup_task_id=new_id("rct"), runtime_group_id=runtime_group_id,
                node_id=node_id, provider_group_id=provider_group_id,
                provider_generation=provider_generation, intent=intent,
                status="WAITING", attempts=0, not_before=stamp,
                processing_owner=None, lease_expires_at=None,
                error_code=error.code, error_message=error.message,
                created_at=stamp, updated_at=stamp,
            )
            self.session.add(task)
        else:
            task.runtime_group_id = runtime_group_id
            task.provider_generation = provider_generation
            task.status = "WAITING"
            task.not_before = stamp
            task.processing_owner = None
            task.lease_expires_at = None
            task.error_code = error.code
            task.error_message = error.message
            task.updated_at = stamp
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            task = self.session.scalar(
                select(models.RuntimeCleanupTask)
                .where(
                    models.RuntimeCleanupTask.node_id == node_id,
                    models.RuntimeCleanupTask.provider_group_id == provider_group_id,
                    models.RuntimeCleanupTask.intent == intent,
                )
                .with_for_update()
            )
            if not task:
                raise
            task.runtime_group_id = runtime_group_id
            task.provider_generation = provider_generation
            task.status = "WAITING"
            task.not_before = stamp
            task.processing_owner = None
            task.lease_expires_at = None
            task.error_code = error.code
            task.error_message = error.message
            task.updated_at = stamp
            self.session.commit()
        return task

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
        provision_owner = f"provision-{uuid4().hex}"
        if data.course_id and data.class_id:
            context = self.session.get(models.RuntimeReleaseReadModel, data.lab_release_id)
            if not context:
                self.session.add(models.RuntimeReleaseReadModel(lab_release_id=data.lab_release_id, lab_version_id=data.lab_version_id, course_id=data.course_id, class_id=data.class_id, status="OPEN", spec_snapshot_json=spec, published_at=stamp, updated_at=stamp))
        request = models.RuntimeRequest(
            runtime_request_id=new_id("rrq"), lab_release_id=data.lab_release_id, lab_version_id=data.lab_version_id,
            course_id=data.course_id, class_id=data.class_id, student_id=data.student_id, mode=data.mode, status="SCHEDULING",
            requested_by=self.user.user_id, idempotency_key=idempotency_key, spec_snapshot_json=spec,
            error_code=None, error_message=None, provision_owner=provision_owner,
            provision_lease_expires_at=stamp + timedelta(seconds=QUEUE_LEASE_SECONDS),
            submission_status="DRAFT", submitted_at=None, last_activity_at=stamp, created_at=stamp, updated_at=stamp,
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
        return await self._schedule_and_provision(request, provision_owner=provision_owner)

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

    async def _schedule_and_provision(
        self,
        request: models.RuntimeRequest,
        *,
        provision_owner: str | None = None,
        queue_owner: str | None = None,
        parent_action: models.RuntimeAdminAction | None = None,
    ) -> dict:
        provision_owner = provision_owner or queue_owner or f"provision-{uuid4().hex}"
        request = self._renew_request_provision(request.runtime_request_id, provision_owner)
        spec = request.spec_snapshot_json
        cpu = sum(float(node["cpu_limit"]) for node in spec["nodes"])
        memory = sum(int(node["memory_mb"]) for node in spec["nodes"])
        digests = {node["image_digest"] for node in spec["nodes"]}
        enabled = set(self.session.scalars(select(models.InfraImage.digest).where(models.InfraImage.enabled.is_(True), models.InfraImage.scan_status == "PASSED", models.InfraImage.startup_check_status == "PASSED", models.InfraImage.teaching_validation_status == "PASSED")))
        missing = sorted(digests - enabled)
        if missing:
            if queue_owner:
                self._assert_queue_lease(request.runtime_request_id, queue_owner)
            return self._pending(request, "RUNTIME.IMAGE_NOT_READY", "实验镜像尚未完成三重验证", {"missing_digests": missing}, commit=not queue_owner)
        candidates = []
        for node in self.session.scalars(select(models.InfraNode).where(models.InfraNode.status == "READY", models.InfraNode.scheduling_paused.is_(False))):
            try:
                if parent_action:
                    parent_action = self._renew_admin_action(parent_action)
                if queue_owner:
                    self._renew_queue_lease(request.runtime_request_id, queue_owner)
                request = self._renew_request_provision(request.runtime_request_id, provision_owner)
                capacity = await self.agent_factory(node.agent_url).capacity()
                capacity = self._validate_capacity_result(capacity)
                if queue_owner:
                    self._renew_queue_lease(request.runtime_request_id, queue_owner)
                request = self._renew_request_provision(request.runtime_request_id, provision_owner)
                observed = now()
                node.last_seen_at = observed
                heartbeat = models.InfraNodeHeartbeat(
                    heartbeat_id=new_id("hbt"), node_id=node.node_id, observed_at=observed,
                    cpu_available=capacity["cpu_available"], memory_available_mb=capacity["memory_available_mb"],
                    running_groups=capacity["running_groups"], image_digests_json=capacity["image_digests"],
                    detail_json={"engine": capacity.get("engine")},
                )
                self.session.add(heartbeat)
                self.session.flush()
                if heartbeat.cpu_available >= cpu and heartbeat.memory_available_mb >= memory:
                    cached = len(digests.intersection(heartbeat.image_digests_json))
                    score = node.weight + heartbeat.cpu_available * 10 + heartbeat.memory_available_mb / 1024 + cached * 50 - heartbeat.running_groups * 5
                    candidates.append((score, node, heartbeat, cached))
            except ApiError as error:
                if error.code in LEASE_ERROR_CODES:
                    raise
                continue
            except (KeyError, TypeError, ValueError):
                continue
        if not candidates:
            if queue_owner:
                self._assert_queue_lease(request.runtime_request_id, queue_owner)
            return self._pending(request, "RUNTIME.CAPACITY_UNAVAILABLE", "暂无满足资源和健康要求的计算节点", {"cpu": cpu, "memory_mb": memory}, commit=not queue_owner)
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, node, _, cached = candidates[0]
        timeout = int(spec["runtime_policy"]["timeout_minutes"])
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == request.runtime_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not request or request.status != "SCHEDULING" or request.provision_owner != provision_owner
            or not request.provision_lease_expires_at or request.provision_lease_expires_at <= now()
        ):
            raise ApiError("RUNTIME.PROVISION_LEASE_LOST", "实验环境创建执行权已失效", 409)
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup).where(
                models.RuntimeInstanceGroup.runtime_request_id == request.runtime_request_id
            )
        )
        if group:
            if group.status != "FAILED" or self.session.scalar(
                select(func.count()).select_from(models.RuntimeInstance).where(
                    models.RuntimeInstance.runtime_group_id == group.runtime_group_id
                )
            ):
                raise ApiError("RUNTIME.RETRY_STATE_CONFLICT", "当前运行组状态不允许重新调度", 409)
            group.node_id = node.node_id
            group.provider_generation = int(group.provider_generation or 1) + 1
            group.status = "STARTING"
            group.scheduler_score = score
            group.scheduler_reason = f"健康节点；资源满足；命中 {cached}/{len(digests)} 个镜像缓存"
            group.scheduled_at = now()
            group.expires_at = now() + timedelta(minutes=timeout)
            group.destroyed_at = None
            group.cleanup_attempts = 0
            group.cleanup_not_before = None
            group.cleanup_intent = None
            group.cleanup_owner = None
            group.cleanup_lease_expires_at = None
            group.cleanup_error_code = group.cleanup_error_message = None
        else:
            group = models.RuntimeInstanceGroup(runtime_group_id=new_id("rtg"), runtime_request_id=request.runtime_request_id, node_id=node.node_id, provider_group_id=None, provider_generation=1, status="STARTING", scheduler_score=score, scheduler_reason=f"健康节点；资源满足；命中 {cached}/{len(digests)} 个镜像缓存", scheduled_at=now(), expires_at=now() + timedelta(minutes=timeout), destroyed_at=None)
            self.session.add(group)
        provider_generation = group.provider_generation
        provider_group_id = self._provider_group_id(group.runtime_group_id, provider_generation)
        group.provider_group_id = provider_group_id
        group.cleanup_intent = "PROVISIONING"
        group.cleanup_owner = provision_owner
        group.cleanup_lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
        group.cleanup_not_before = group.cleanup_lease_expires_at
        request.status = "STARTING"
        request.error_code = request.error_message = None
        request.updated_at = now()
        group_id = group.runtime_group_id
        self.session.commit()
        payload = {
            "runtime_group_id": provider_group_id,
            "expires_at": group.expires_at.isoformat(),
            "networks": spec["networks"],
            "containers": [{"node_key": item["node_key"], "role": item["role"], "image_digest": item["image_digest"], "cpu_limit": item["cpu_limit"], "memory_mb": item["memory_mb"], "pids_limit": 128, "startup_command": item.get("startup_command", ""), "network_keys": item["network_keys"]} for item in spec["nodes"]],
        }
        async def rollback_candidate(candidate_node: models.InfraNode, cause: ApiError) -> None:
            try:
                cleanup_result = await self.agent_factory(candidate_node.agent_url).destroy(provider_group_id)
                self._validate_destroy_result(cleanup_result, provider_group_id)
            except (ApiError, KeyError, TypeError, ValueError) as raw_cleanup_error:
                cleanup_error = raw_cleanup_error if isinstance(raw_cleanup_error, ApiError) else ApiError(
                    "RUNTIME.PROVISION_ROLLBACK_FAILED", "节点代理回滚响应无效", 503
                )
                cleanup_error = ApiError(
                    "RUNTIME.PROVISION_ROLLBACK_FAILED", cleanup_error.message, 503,
                    {"node_id": candidate_node.node_id, "cause": cause.code},
                )
                self._record_cleanup_task(
                    runtime_group_id=group_id, node_id=candidate_node.node_id,
                    provider_group_id=provider_group_id, provider_generation=provider_generation,
                    intent="PROVISION_ORPHAN", error=cleanup_error,
                )
                current_group = self.session.scalar(
                    select(models.RuntimeInstanceGroup)
                    .where(models.RuntimeInstanceGroup.runtime_group_id == group_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                current_request = self.session.scalar(
                    select(models.RuntimeRequest)
                    .where(models.RuntimeRequest.runtime_request_id == request.runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                claim_time = now()
                if (
                    current_group and current_request and current_group.status == "STARTING"
                    and current_group.cleanup_owner == provision_owner
                    and current_group.cleanup_lease_expires_at and current_group.cleanup_lease_expires_at > claim_time
                    and current_request.provision_owner == provision_owner
                    and current_request.provision_lease_expires_at and current_request.provision_lease_expires_at > claim_time
                ):
                    current_group.status = "FAILED"
                    current_group.provider_group_id = None
                    current_group.cleanup_intent = None
                    current_group.cleanup_owner = None
                    current_group.cleanup_lease_expires_at = None
                    current_group.cleanup_not_before = None
                    current_group.cleanup_error_code = cleanup_error.code
                    current_group.cleanup_error_message = cleanup_error.message
                    current_request.status = "FAILED"
                    current_request.provision_owner = None
                    current_request.provision_lease_expires_at = None
                    current_request.error_code = cleanup_error.code
                    current_request.error_message = cleanup_error.message
                    current_request.updated_at = claim_time
                    self.session.commit()
                raise cleanup_error from raw_cleanup_error
            try:
                if parent_action:
                    self._renew_admin_action(parent_action)
                if queue_owner:
                    self._assert_queue_lease(request.runtime_request_id, queue_owner)
                current_group, _ = self._lock_provision_owner(request.runtime_request_id, group_id, provision_owner, renew=True)
                if current_group.provider_group_id == provider_group_id:
                    current_group.provider_group_id = None
                self.session.commit()
            except ApiError as lease_error:
                if lease_error.code not in LEASE_ERROR_CODES:
                    raise
                self.session.rollback()
                raise

        result = None
        last_error = None
        for attempt, (candidate_score, candidate_node, _, candidate_cached) in enumerate(candidates, start=1):
            node = self.session.scalar(
                select(models.InfraNode)
                .where(models.InfraNode.node_id == candidate_node.node_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not node or node.status != "READY" or node.scheduling_paused:
                continue
            group, request = self._lock_provision_owner(
                request.runtime_request_id, group_id, provision_owner, renew=True
            )
            node.last_seen_at = now()
            score, cached = candidate_score, candidate_cached
            group.node_id, group.scheduler_score = node.node_id, score
            group.provider_group_id = provider_group_id
            group.scheduler_reason = f"健康节点；资源满足；命中 {cached}/{len(digests)} 个镜像缓存；第 {attempt} 次调度"
            group.scheduled_at = now()
            self._event("runtime.group.scheduled", group_id=group_id, detail={"node_id": node.node_id, "score": score, "reason": group.scheduler_reason, "scheduled_at": group.scheduled_at.isoformat(), "attempt": attempt})
            self.session.commit()
            try:
                if parent_action:
                    parent_action = self._renew_admin_action(parent_action)
                if queue_owner:
                    self._renew_queue_lease(request.runtime_request_id, queue_owner)
                result = await self.agent_factory(node.agent_url).create_group(payload)
            except ApiError as error:
                if error.code in LEASE_ERROR_CODES:
                    raise
                last_error = error
                await rollback_candidate(node, error)
                self._event("runtime.group.retry", group_id=group_id, detail={"node_id": node.node_id, "attempt": attempt, "error_code": error.code})
                self.session.commit()
                continue
            except (KeyError, TypeError, ValueError) as error:
                last_error = ApiError("RUNTIME.PROVIDER_RESPONSE_INVALID", "计算节点代理创建响应无效", 503)
                await rollback_candidate(node, last_error)
                self._event("runtime.group.retry", group_id=group_id, detail={"node_id": node.node_id, "attempt": attempt, "error_code": last_error.code})
                self.session.commit()
                continue
            try:
                self._validate_create_result(result, spec, provider_group_id)
            except (ApiError, KeyError, TypeError, ValueError) as validation_error:
                last_error = ApiError("RUNTIME.PROVIDER_RESPONSE_INVALID", "计算节点代理创建响应无效", 503)
                await rollback_candidate(node, last_error)
                result = None
                continue
            try:
                capture_result = await self.agent_factory(node.agent_url).capture_start(provider_group_id)
                self._validate_capture_start_result(capture_result, provider_group_id)
            except (ApiError, KeyError, TypeError, ValueError) as raw_capture_error:
                capture_error = raw_capture_error if isinstance(raw_capture_error, ApiError) else ApiError(
                    "RUNTIME.CAPTURE_RESPONSE_INVALID", "节点代理抓包启动响应无效", 503
                )
                last_error = ApiError(
                    "RUNTIME.CAPTURE_START_FAILED", "实验流量采集启动失败，运行组已回滚", 503,
                    {"provider_error": capture_error.code},
                )
                await rollback_candidate(node, last_error)
                result = None
                continue
            try:
                if queue_owner:
                    self._assert_queue_lease(request.runtime_request_id, queue_owner)
                group, request = self._lock_provision_owner(
                    request.runtime_request_id, group_id, provision_owner, renew=True
                )
                self.session.commit()
            except ApiError as lease_error:
                if lease_error.code not in LEASE_ERROR_CODES:
                    raise
                try:
                    cleanup_result = await self.agent_factory(node.agent_url).destroy(provider_group_id)
                    self._validate_destroy_result(cleanup_result, provider_group_id)
                except (ApiError, KeyError, TypeError, ValueError) as raw_cleanup_error:
                    cleanup_error = raw_cleanup_error if isinstance(raw_cleanup_error, ApiError) else ApiError(
                        "RUNTIME.PROVISION_ROLLBACK_FAILED", "节点代理回滚响应无效", 503
                    )
                    self._record_cleanup_task(
                        runtime_group_id=group_id, node_id=node.node_id,
                        provider_group_id=provider_group_id, provider_generation=provider_generation,
                        intent="PROVISION_ORPHAN", error=cleanup_error,
                    )
                raise lease_error
            break
        if result is None:
            if queue_owner:
                self._assert_queue_lease(request.runtime_request_id, queue_owner)
            group, request = self._lock_provision_owner(
                request.runtime_request_id, group_id, provision_owner
            )
            error = last_error or ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "计算节点代理不可用", 503)
            request.status, request.error_code, request.error_message, request.updated_at = "FAILED", error.code, error.message, now()
            request.provision_owner = None
            request.provision_lease_expires_at = None
            group.status = "FAILED"
            group.cleanup_intent = None
            group.cleanup_owner = None
            group.cleanup_lease_expires_at = None
            group.cleanup_not_before = None
            self._event("lab.instance.failed", group_id=group_id, detail=self._projection_payload(request, None, status="FAILED", error_code=error.code), idempotency_key=f"lab.instance.failed:{request.runtime_request_id}:{int(group.scheduled_at.timestamp() * 1_000_000)}")
            self.session.flush() if queue_owner else self.session.commit()
            raise ApiError(error.code, error.message, error.status_code, {**error.details, "runtime_request_id": request.runtime_request_id}) from error
        if queue_owner:
            self._assert_queue_lease(request.runtime_request_id, queue_owner)
        group, request = self._lock_provision_owner(
            request.runtime_request_id, group_id, provision_owner
        )
        group.provider_group_id = result["provider_group_id"]
        group.status = "RUNNING"
        group.cleanup_intent = None
        group.cleanup_owner = None
        group.cleanup_lease_expires_at = None
        group.cleanup_not_before = None
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
        self._event(
            "runtime.capture.started", instance_id=primary.runtime_instance_id if primary else None, group_id=group_id,
            detail={"provider_group_id": provider_group_id, "capture_id": capture_result["capture_id"], "started_at": capture_result["started_at"]},
        )
        self._event("lab.instance.started", instance_id=primary.runtime_instance_id if primary else None, group_id=group_id, detail=self._projection_payload(request, primary, status="RUNNING"), idempotency_key=f"lab.instance.started:{primary.runtime_instance_id if primary else group_id}:1")
        queued = self.session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == request.runtime_request_id))
        if queued:
            queued.status = "DONE"
            queued.not_before = None
            queued.processing_owner = None
            queued.lease_expires_at = None
        self.session.flush() if queue_owner else self.session.commit()
        return self.request_view(request)

    def _pending(self, request: models.RuntimeRequest, code: str, message: str, detail: dict, *, commit: bool = True) -> dict:
        request.status, request.error_code, request.error_message, request.updated_at = "QUEUED", code, message, now()
        request.provision_owner = None
        request.provision_lease_expires_at = None
        queued = self.session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == request.runtime_request_id))
        if not queued:
            queued = models.RuntimeQueue(queue_id=new_id("rtq"), runtime_request_id=request.runtime_request_id, status="WAITING", priority=100, attempts=0, not_before=None, enqueued_at=now())
            self.session.add(queued)
        else:
            queued.status = "WAITING"
            queued.not_before = now() + timedelta(seconds=min(300, 5 * (2 ** min(queued.attempts, 6))))
            queued.processing_owner = None
            queued.lease_expires_at = None
        self._event("runtime.request.queued", detail={"runtime_request_id": request.runtime_request_id, "reason": code})
        self.session.commit() if commit else self.session.flush()
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
        item.provision_owner = None
        item.provision_lease_expires_at = None
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
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if group.status == "DESTROYED":
            return self.instance(instance_id)
        if group.status == "DESTROYING" or (
            group.cleanup_owner and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now()
        ):
            raise ApiError("RUNTIME.CLEANUP_IN_PROGRESS", "实验环境正在清理，请稍后重试", 409)
        node = self.session.get(models.InfraNode, group.node_id)
        if not node:
            raise ApiError("RUNTIME.NODE_NOT_FOUND", "计算节点不存在", 503)
        cleanup_owner = f"manual-{uuid4().hex}"
        cleanup_started = now()
        group.status = "DESTROYING"
        group.cleanup_attempts = int(group.cleanup_attempts or 0) + 1
        group.cleanup_intent = "MANUAL"
        group.cleanup_owner = cleanup_owner
        group.cleanup_lease_expires_at = cleanup_started + timedelta(seconds=QUEUE_LEASE_SECONDS)
        group.cleanup_not_before = group.cleanup_lease_expires_at
        for sibling in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)):
            sibling.status = "STOPPING"
        self.session.commit()
        destroy_target = group.provider_group_id or group.runtime_group_id
        agent = self.agent_factory(node.agent_url)
        await self._capture_before_cleanup(agent, destroy_target, group.runtime_group_id)
        try:
            cleanup_result = await agent.destroy(destroy_target)
            self._validate_destroy_result(cleanup_result, destroy_target)
        except (ApiError, KeyError, TypeError, ValueError) as raw_error:
            error = raw_error if isinstance(raw_error, ApiError) else ApiError(
                "RUNTIME.MANUAL_CLEANUP_FAILED", "节点代理销毁响应无效", 503
            )
            group = self.session.scalar(
                select(models.RuntimeInstanceGroup)
                .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if group and group.cleanup_owner == cleanup_owner:
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_not_before = now() + timedelta(seconds=min(300, 5 * (2 ** min(group.cleanup_attempts, 6))))
                group.cleanup_error_code = "RUNTIME.MANUAL_CLEANUP_FAILED"
                group.cleanup_error_message = error.message
                self.session.commit()
            raise error from raw_error
        stamp = now()
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not group or group.cleanup_owner != cleanup_owner
            or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= stamp
        ):
            raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "实验环境清理执行权已失效", 409)
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        siblings = list(self.session.scalars(
            select(models.RuntimeInstance)
            .where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ))
        item = next((sibling for sibling in siblings if sibling.runtime_instance_id == instance_id), item)
        group.status, group.destroyed_at = "DESTROYED", stamp
        group.cleanup_intent = None
        group.cleanup_owner = None
        group.cleanup_lease_expires_at = None
        group.cleanup_not_before = None
        group.cleanup_error_code = group.cleanup_error_message = None
        for sibling in siblings:
            sibling.status, sibling.ended_at = "DESTROYED", stamp
        request.status, request.updated_at, request.last_activity_at = "CANCELED", stamp, stamp
        self._event("lab.instance.destroyed", instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status="DESTROYED", reason=reason), idempotency_key=f"lab.instance.destroyed:{group.runtime_group_id}:g{group.provider_generation}")
        self.session.commit()
        return self.instance(instance_id)

    async def rebuild(self, instance_id: str, reason: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.rebuild")
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if group.status == "DESTROYING":
            raise ApiError("RUNTIME.CLEANUP_IN_PROGRESS", "实验环境正在清理，暂不能重建", 409)
        if group.cleanup_owner and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now():
            raise ApiError("RUNTIME.CLEANUP_IN_PROGRESS", "实验环境存在正在执行的恢复动作，暂不能重建", 409)
        if group.status not in {"RUNNING", "FAILED", "DESTROYED"}:
            raise ApiError("RUNTIME.REBUILD_STATE_CONFLICT", "当前实验状态不能重建", 409)
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        instances = list(self.session.scalars(
            select(models.RuntimeInstance)
            .where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ))
        node = self.session.get(models.InfraNode, group.node_id)
        if not node or not request:
            raise ApiError("RUNTIME.REBUILD_FACT_INVALID", "实验重建所需事实不完整", 503)
        spec = request.spec_snapshot_json
        rebuild_started = now()
        group.expires_at = rebuild_started + timedelta(minutes=int(spec["runtime_policy"]["timeout_minutes"]))
        owner = f"rebuild-{uuid4().hex}"
        group_id = group.runtime_group_id
        request_id = request.runtime_request_id
        destroy_target = group.provider_group_id
        provider_generation = int(group.provider_generation or 1) + 1
        provider_group_id = self._provider_group_id(group_id, provider_generation)
        group.status = "DESTROYING" if destroy_target else "STARTING"
        if not destroy_target:
            group.provider_generation = provider_generation
            group.provider_group_id = provider_group_id
        group.cleanup_attempts = int(group.cleanup_attempts or 0) + 1
        group.cleanup_intent = "REBUILD"
        group.cleanup_owner = owner
        group.cleanup_lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
        group.cleanup_not_before = group.cleanup_lease_expires_at
        group.cleanup_error_code = group.cleanup_error_message = None
        for sibling in instances:
            sibling.status = "STOPPING"
        payload = {
            "runtime_group_id": provider_group_id,
            "expires_at": group.expires_at.isoformat(),
            "networks": spec["networks"],
            "containers": [
                {"node_key": x["node_key"], "role": x["role"], "image_digest": x["image_digest"], "cpu_limit": x["cpu_limit"], "memory_mb": x["memory_mb"], "pids_limit": 128, "startup_command": x.get("startup_command", ""), "network_keys": x["network_keys"]}
                for x in spec["nodes"]
            ],
        }
        self.session.commit()

        async def compensate_rebuild_orphan(error: ApiError) -> bool:
            try:
                cleanup_result = await self.agent_factory(node.agent_url).destroy(provider_group_id)
                self._validate_destroy_result(cleanup_result, provider_group_id)
                return True
            except (ApiError, KeyError, TypeError, ValueError) as raw_cleanup_error:
                cleanup_error = raw_cleanup_error if isinstance(raw_cleanup_error, ApiError) else ApiError(
                    "RUNTIME.REBUILD_ORPHAN_CLEANUP_FAILED", "节点代理重建回滚响应无效", 503
                )
                self._record_cleanup_task(
                    runtime_group_id=group_id, node_id=node.node_id,
                    provider_group_id=provider_group_id, provider_generation=provider_generation,
                    intent="REBUILD_ORPHAN", error=cleanup_error,
                )
                return False

        if destroy_target:
            agent = self.agent_factory(node.agent_url)
            await self._capture_before_cleanup(agent, destroy_target, group_id)
            try:
                cleanup_result = await agent.destroy(destroy_target)
                self._validate_destroy_result(cleanup_result, destroy_target)
            except (ApiError, KeyError, TypeError, ValueError) as raw_error:
                error = raw_error if isinstance(raw_error, ApiError) else ApiError("RUNTIME.REBUILD_CLEANUP_FAILED", "节点代理销毁响应无效", 503)
                group = self.session.scalar(
                    select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
                )
                request = self.session.scalar(
                    select(models.RuntimeRequest).where(models.RuntimeRequest.runtime_request_id == request_id).with_for_update().execution_options(populate_existing=True)
                )
                if not group or group.cleanup_owner != owner or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now():
                    lease_error = ApiError("RUNTIME.RECOVERY_LEASE_LOST", "实验重建执行权已失效", 409)
                    await compensate_rebuild_orphan(lease_error)
                    raise lease_error
                group.status = "DESTROYING"
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_not_before = now() + timedelta(seconds=min(300, 5 * (2 ** min(group.cleanup_attempts, 6))))
                group.cleanup_error_code = "RUNTIME.REBUILD_CLEANUP_FAILED"
                group.cleanup_error_message = error.message
                request.status, request.error_code, request.error_message, request.updated_at = "FAILED", group.cleanup_error_code, error.message, now()
                self.session.commit()
                raise error from raw_error

            group = self.session.scalar(
                select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
            )
            request = self.session.scalar(
                select(models.RuntimeRequest).where(models.RuntimeRequest.runtime_request_id == request_id).with_for_update().execution_options(populate_existing=True)
            )
            if not group or not request or group.cleanup_owner != owner or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now():
                raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "实验重建执行权已失效", 409)
            group.provider_generation = provider_generation
            group.provider_group_id = provider_group_id
            group.status = "STARTING"
            group.cleanup_lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
            group.cleanup_not_before = group.cleanup_lease_expires_at
            self.session.commit()

        new_group_created = False
        try:
            result = await self.agent_factory(node.agent_url).create_group(payload)
            self._validate_create_result(result, spec, provider_group_id)
            new_group_created = True
            try:
                capture_result = await self.agent_factory(node.agent_url).capture_start(provider_group_id)
                self._validate_capture_start_result(capture_result, provider_group_id)
            except (ApiError, KeyError, TypeError, ValueError) as raw_capture_error:
                capture_error = raw_capture_error if isinstance(raw_capture_error, ApiError) else ApiError(
                    "RUNTIME.CAPTURE_RESPONSE_INVALID", "节点代理抓包启动响应无效", 503
                )
                raise ApiError(
                    "RUNTIME.CAPTURE_START_FAILED", "重建后的实验流量采集启动失败", 503,
                    {"provider_error": capture_error.code},
                ) from raw_capture_error
        except (ApiError, KeyError, TypeError, ValueError) as raw_error:
            error = raw_error if isinstance(raw_error, ApiError) else ApiError("RUNTIME.PROVIDER_RESPONSE_INVALID", "计算节点代理创建响应无效", 503)
            cleanup_completed = await compensate_rebuild_orphan(error) if new_group_created else False
            group = self.session.scalar(
                select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
            )
            request = self.session.scalar(
                select(models.RuntimeRequest).where(models.RuntimeRequest.runtime_request_id == request_id).with_for_update().execution_options(populate_existing=True)
            )
            if not group or group.cleanup_owner != owner or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now():
                lease_error = ApiError("RUNTIME.RECOVERY_LEASE_LOST", "实验重建执行权已失效", 409)
                await compensate_rebuild_orphan(lease_error)
                raise lease_error
            group.status = "FAILED" if cleanup_completed else "DESTROYING"
            group.provider_group_id = None if cleanup_completed else provider_group_id
            group.cleanup_intent = None if cleanup_completed else "REBUILD"
            group.cleanup_owner = None
            group.cleanup_lease_expires_at = None
            group.cleanup_not_before = None if cleanup_completed else now()
            group.cleanup_error_code = "RUNTIME.CAPTURE_START_FAILED" if error.code == "RUNTIME.CAPTURE_START_FAILED" else "RUNTIME.REBUILD_CREATE_FAILED"
            group.cleanup_error_message = error.message
            request.status, request.error_code, request.error_message, request.updated_at = "FAILED", group.cleanup_error_code, error.message, now()
            if cleanup_completed:
                for failed_instance in self.session.scalars(select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group_id)):
                    failed_instance.status = "FAILED"
                    failed_instance.ended_at = failed_instance.ended_at or now()
            self.session.commit()
            raise error from raw_error

        group = self.session.scalar(
            select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
        )
        request = self.session.scalar(
            select(models.RuntimeRequest).where(models.RuntimeRequest.runtime_request_id == request_id).with_for_update().execution_options(populate_existing=True)
        )
        instances = list(self.session.scalars(
            select(models.RuntimeInstance).where(models.RuntimeInstance.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
        ))
        if not group or not request or group.status != "STARTING" or group.cleanup_owner != owner or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now():
            lease_error = ApiError("RUNTIME.RECOVERY_LEASE_LOST", "实验重建执行权已失效", 409)
            await compensate_rebuild_orphan(lease_error)
            raise lease_error
        group.provider_group_id, group.status = result["provider_group_id"], "RUNNING"
        group.destroyed_at = None
        group.cleanup_intent = None
        group.cleanup_owner = None
        group.cleanup_lease_expires_at = None
        group.cleanup_not_before = None
        group.cleanup_error_code = group.cleanup_error_message = None
        existing = {x.node_key: x for x in instances}
        for container in result["containers"]:
            instance = existing[container["node_key"]]
            instance.status, instance.started_at, instance.ended_at, instance.expires_at = "RUNNING", now(), None, group.expires_at
            stored = self.session.scalar(select(models.RuntimeContainer).where(models.RuntimeContainer.runtime_instance_id == instance.runtime_instance_id))
            stored.provider_container_id, stored.status = container["container_id"], "RUNNING"
        existing_networks = {x.network_key: x for x in self.session.scalars(select(models.RuntimeNetwork).where(models.RuntimeNetwork.runtime_group_id == group_id))}
        for network in result["networks"]:
            stored_network = existing_networks[network["network_key"]]
            stored_network.provider_network_id = network["network_id"]
            stored_network.status = "ACTIVE"
            stored_network.isolation_checks_json = network.get("isolation_checks", {})
        request.last_activity_at = now()
        request.status = "RUNNING"
        request.provision_owner = None
        request.provision_lease_expires_at = None
        request.error_code = request.error_message = None
        item = existing[next(instance.node_key for instance in instances if instance.runtime_instance_id == instance_id)]
        self._event(
            "runtime.capture.started", instance_id=instance_id, group_id=group.runtime_group_id,
            detail={"provider_group_id": provider_group_id, "capture_id": capture_result["capture_id"], "started_at": capture_result["started_at"], "rebuild": True},
        )
        self._event("lab.instance.started", instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status="RUNNING", reason=reason, checkpoint_results_preserved=True), idempotency_key=f"lab.instance.started:{instance_id}:rebuild:{owner}")
        self.session.commit()
        return self.instance(instance_id)

    def extend(self, instance_id: str, data: RuntimeExtend) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.extend")
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        siblings = list(self.session.scalars(
            select(models.RuntimeInstance)
            .where(models.RuntimeInstance.runtime_group_id == group.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ))
        if group.status != "RUNNING" or item.status != "RUNNING" or (
            group.cleanup_owner and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now()
        ):
            raise ApiError("RUNTIME.EXTEND_STATE_CONFLICT", "当前实验状态不能延长时限", 409)
        group.expires_at += timedelta(minutes=data.minutes)
        for sibling in siblings:
            sibling.expires_at = group.expires_at
        request.last_activity_at = now()
        self._event("runtime.instance.extended", instance_id=instance_id, group_id=group.runtime_group_id, detail={"minutes": data.minutes, "reason": data.reason})
        self.session.commit()
        return self.instance(instance_id)

    async def rejudge(self, instance_id: str) -> dict:
        item = self.session.get(models.RuntimeInstance, instance_id)
        if not item:
            raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
        self._instance_scope(item, "runtime.rejudge")
        group = self.session.scalar(
            select(models.RuntimeInstanceGroup)
            .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        request = self.session.scalar(
            select(models.RuntimeRequest)
            .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        item = self.session.scalar(
            select(models.RuntimeInstance)
            .where(models.RuntimeInstance.runtime_instance_id == instance_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if group.status != "RUNNING" or item.status != "RUNNING" or (
            group.cleanup_owner and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now()
        ):
            raise ApiError("RUNTIME.REJUDGE_STATE_CONFLICT", "当前实验状态不能重新判题", 409)
        node = self.session.get(models.InfraNode, group.node_id)
        if not node or not group.provider_group_id:
            raise ApiError("RUNTIME.REJUDGE_FACT_INVALID", "重新判题所需运行事实不完整", 503)
        self.session.commit()
        agent = self.agent_factory(node.agent_url)
        previous_results = list(self.session.scalars(
            select(models.CheckpointResult)
            .where(models.CheckpointResult.runtime_instance_id == item.runtime_instance_id)
            .order_by(models.CheckpointResult.judged_at)
        ))
        latest_scores = {result.checkpoint_id: result.score_awarded for result in previous_results}
        total_score = int(request.spec_snapshot_json.get("total_score", 100))
        for checkpoint in request.spec_snapshot_json["checkpoints"]:
            result = await agent.exec(group.provider_group_id, {"operation": "judge", "checkpoint": checkpoint, "timeout_seconds": min(int(checkpoint["timeout_seconds"]), 30), "output_limit_bytes": 8192})
            group = self.session.scalar(
                select(models.RuntimeInstanceGroup)
                .where(models.RuntimeInstanceGroup.runtime_group_id == item.runtime_group_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            request = self.session.scalar(
                select(models.RuntimeRequest)
                .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            item = self.session.scalar(
                select(models.RuntimeInstance)
                .where(models.RuntimeInstance.runtime_instance_id == instance_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if group.status != "RUNNING" or item.status != "RUNNING" or (
                group.cleanup_owner and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now()
            ):
                raise ApiError("RUNTIME.REJUDGE_STATE_CONFLICT", "重新判题期间实验状态已变化", 409)
            attempt = (self.session.scalar(select(func.max(models.CheckpointResult.attempt)).where(models.CheckpointResult.runtime_instance_id == item.runtime_instance_id, models.CheckpointResult.checkpoint_id == checkpoint["checkpoint_id"])) or 0) + 1
            passed = bool(result.get("passed"))
            evidence = {**result.get("evidence", {}), "order_no": int(checkpoint.get("order_no", 0))}
            stored = models.CheckpointResult(checkpoint_result_id=new_id("cpr"), runtime_instance_id=item.runtime_instance_id, student_id=item.student_id, checkpoint_id=checkpoint["checkpoint_id"], attempt=attempt, status="PASSED" if passed else "FAILED", score_awarded=checkpoint["score"] if passed else 0, max_score=checkpoint["score"], evidence_json=evidence, message=result.get("message", "通过" if passed else checkpoint["failure_message"]), judged_at=now())
            self.session.add(stored)
            latest_scores[checkpoint["checkpoint_id"]] = stored.score_awarded
            event_type = "lab.checkpoint.passed" if passed else "lab.checkpoint.failed"
            self._event(event_type, instance_id=instance_id, group_id=group.runtime_group_id, detail=self._projection_payload(request, item, status=item.status, current_step=int(checkpoint.get("order_no", 0)), raw_score=sum(latest_scores.values()), max_score=total_score, source_id=stored.checkpoint_result_id, checkpoint_id=checkpoint["checkpoint_id"], checkpoint_status=stored.status, score_awarded=stored.score_awarded), idempotency_key=f"{event_type}:{instance_id}:{checkpoint['checkpoint_id']}:{attempt}")
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

    @staticmethod
    def _distribution_signing_key() -> str:
        secret = os.getenv("YUEKE_LOG_DISTRIBUTION_SIGNING_KEY", "")
        if len(secret.encode("utf-8")) < 32:
            raise ApiError("RUNTIME.DISTRIBUTION_SIGNING_UNAVAILABLE", "日志分发签名密钥尚未安全配置", 503)
        return secret

    @staticmethod
    def _artifact_storage_signing_key() -> str:
        secret = os.getenv("YUEKE_ARTIFACT_STORAGE_SIGNING_KEY", "")
        if len(secret.encode("utf-8")) < 32:
            raise ApiError("RUNTIME.ARTIFACT_STORAGE_SIGNING_UNAVAILABLE", "制品存储签名密钥尚未安全配置", 503)
        return secret

    def distribution_artifact_bundle(self, authorization: str) -> dict:
        """Exchange E's narrow grant for a short-lived storage capability.

        The student's ordinary runtime scope is deliberately not relaxed.  E
        signs the exact assignment and reference set after checking its own
        assignment facts; D verifies the signature and every D-owned source
        fact before issuing the capability.
        """
        self._permission("runtime.distributed-artifact.download")
        if self.user.role != "student" or not self.user.student_id:
            raise ApiError("AUTH.STUDENT_REQUIRED", "仅日志任务的目标学生可下载", 403)
        secret = self._distribution_signing_key()
        try:
            claims = DistributionDownloadClaims.model_validate(verify_capability(authorization, secret))
        except ValueError as exc:
            raise ApiError("RUNTIME.DISTRIBUTION_AUTH_INVALID", "日志分发下载授权无效", 403) from exc
        epoch = int(time())
        if claims.issued_at > epoch + 30 or claims.expires_at <= epoch:
            raise ApiError("RUNTIME.DISTRIBUTION_AUTH_EXPIRED", "日志分发下载授权已过期", 403)
        if claims.student_id != self.user.student_id:
            raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "日志分发下载授权不属于当前学生", 403)
        if claims.class_id not in self.user.class_ids or claims.course_id not in self.user.course_ids:
            raise ApiError("AUTH.SCOPE_DENIED", "日志分发下载授权超出当前课程或班级", 403)

        storage_references: list[dict] = []
        for reference_id in claims.reference_ids:
            if claims.distribution_type == "TRAFFIC":
                source = self.session.execute(
                    select(models.RuntimeArtifact, models.RuntimeRequest)
                    .join(models.RuntimeInstance, models.RuntimeInstance.runtime_instance_id == models.RuntimeArtifact.runtime_instance_id)
                    .join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeInstance.runtime_group_id)
                    .join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id)
                    .where(models.RuntimeArtifact.runtime_artifact_id == reference_id, models.RuntimeArtifact.artifact_type == "TRAFFIC")
                ).one_or_none()
                if not source:
                    raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_NOT_FOUND", "分发的流量日志制品不存在", 404, {"reference_id": reference_id})
                artifact, request = source
                file_object = self.session.get(FileObject, artifact.file_id)
                if not file_object:
                    raise ApiError("RUNTIME.ARTIFACT_FILE_OBJECT_MISSING", "流量日志制品未登记文件对象", 409, {"reference_id": reference_id, "file_id": artifact.file_id})
                if file_object.sha256 != artifact.sha256 or file_object.size_bytes != artifact.size_bytes:
                    raise ApiError("RUNTIME.ARTIFACT_REGISTRATION_MISMATCH", "流量日志制品与文件对象登记信息不一致", 409, {"reference_id": reference_id, "file_id": artifact.file_id})
                storage_references.append({
                    "reference_id": reference_id,
                    "file_id": artifact.file_id,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "original_name": file_object.original_name,
                })
            else:
                source = self.session.execute(
                    select(models.RuntimeEvent, models.RuntimeRequest)
                    .join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeEvent.runtime_group_id)
                    .join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id)
                    .where(models.RuntimeEvent.runtime_event_id == reference_id)
                ).one_or_none()
                if not source:
                    raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_NOT_FOUND", "分发的审计日志不存在", 404, {"reference_id": reference_id})
                event, request = source
                content = self._audit_log_content(event, request)
                storage_references.append({
                    "reference_id": reference_id,
                    "file_id": None,
                    "sha256": sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "original_name": f"audit-{reference_id}.json",
                })
            if (
                request.course_id != claims.course_id
                or request.class_id != claims.class_id
                or request.lab_release_id != claims.lab_release_id
            ):
                raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_SCOPE_MISMATCH", "分发日志来源超出授权实验范围", 403, {"reference_id": reference_id})

        base = os.getenv("YUEKE_ARTIFACT_DOWNLOAD_BASE_URL", "/api/v1/artifact-storage")
        reference_digest = _reference_digest(storage_references)
        storage_claims = {
            "version": 1, "issuer": "lab-runtime", "audience": "artifact-storage",
            "grant_type": "DISTRIBUTION",
            "assignment_id": claims.assignment_id, "distribution_id": claims.distribution_id,
            "distribution_type": claims.distribution_type, "student_id": claims.student_id,
            "subject_user_id": self.user.user_id, "subject_role": self.user.role,
            "course_id": claims.course_id, "class_id": claims.class_id, "lab_release_id": claims.lab_release_id,
            "references": storage_references, "reference_digest": reference_digest,
            "nonce": claims.nonce, "issued_at": claims.issued_at, "expires_at": claims.expires_at,
        }
        capability = sign_capability(storage_claims, self._artifact_storage_signing_key())
        download_url = f"{base.rstrip('/')}/bundles/{claims.assignment_id}?capability={quote(capability, safe='')}"
        event_key = f"{claims.assignment_id}:{claims.nonce}"
        already_audited = self.session.scalar(select(DomainEventOutbox.event_id).where(
            DomainEventOutbox.event_type == "runtime.artifact.distribution_download_authorized",
            DomainEventOutbox.idempotency_key == event_key,
        ))
        if not already_audited:
            enqueue_event(
                self.session,
                event_type="runtime.artifact.distribution_download_authorized",
                aggregate_type="student_log_assignment",
                aggregate_id=claims.assignment_id,
                actor_user_id=self.user.user_id,
                idempotency_key=event_key,
                payload={
                    "distribution_id": claims.distribution_id,
                    "student_id": claims.student_id,
                    "course_id": claims.course_id,
                    "class_id": claims.class_id,
                    "lab_release_id": claims.lab_release_id,
                    "distribution_type": claims.distribution_type,
                    "reference_ids": claims.reference_ids,
                    "reference_count": len(storage_references),
                    "expires_at": claims.expires_at,
                },
            )
            try:
                self.session.commit()
            except IntegrityError:
                # A concurrent replay may win the outbox uniqueness race.  It
                # is the same signed grant, so return the deterministic result
                # after proving that the winner exists instead of surfacing a
                # false failure or creating a second audit fact.
                self.session.rollback()
                replay_event = self.session.scalar(select(DomainEventOutbox.event_id).where(
                    DomainEventOutbox.event_type == "runtime.artifact.distribution_download_authorized",
                    DomainEventOutbox.idempotency_key == event_key,
                ))
                if not replay_event:
                    raise
        return {
            "download_url": download_url,
            "expires_in": claims.expires_at - claims.issued_at,
            "artifact_count": len(storage_references),
            "status": "READY",
        }

    def direct_artifact_bundle(self, artifact_ids: list[str]) -> dict:
        self._permission("runtime.read")
        if not artifact_ids or len(artifact_ids) > 200 or len(artifact_ids) != len(set(artifact_ids)):
            raise ApiError("RUNTIME.INVALID_ARTIFACT_BUNDLE", "制品列表不能为空、不能重复且最多 200 项", 422)
        references: list[dict] = []
        for artifact_id in artifact_ids:
            artifact = self.session.get(models.RuntimeArtifact, artifact_id)
            if not artifact:
                raise ApiError("RUNTIME.ARTIFACT_NOT_FOUND", "日志制品不存在", 404, {"artifact_id": artifact_id})
            instance = self.session.get(models.RuntimeInstance, artifact.runtime_instance_id)
            if not instance:
                raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
            self._instance_scope(instance)
            file_object = self.session.get(FileObject, artifact.file_id)
            if not file_object:
                raise ApiError("RUNTIME.ARTIFACT_FILE_OBJECT_MISSING", "流量日志制品未登记文件对象", 409, {"reference_id": artifact_id, "file_id": artifact.file_id})
            if file_object.sha256 != artifact.sha256 or file_object.size_bytes != artifact.size_bytes:
                raise ApiError("RUNTIME.ARTIFACT_REGISTRATION_MISMATCH", "流量日志制品与文件对象登记信息不一致", 409, {"reference_id": artifact_id, "file_id": artifact.file_id})
            references.append({
                "reference_id": artifact_id,
                "file_id": artifact.file_id,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "original_name": file_object.original_name,
            })
        epoch = int(time())
        bundle_id = f"direct_{uuid4().hex[:24]}"
        nonce = uuid4().hex
        storage_claims = {
            "version": 1,
            "issuer": "lab-runtime",
            "audience": "artifact-storage",
            "grant_type": "DIRECT",
            "assignment_id": bundle_id,
            "distribution_id": None,
            "distribution_type": "TRAFFIC",
            "subject_user_id": self.user.user_id,
            "subject_role": self.user.role,
            "student_id": self.user.student_id,
            "course_id": None,
            "class_id": None,
            "lab_release_id": None,
            "references": references,
            "reference_digest": _reference_digest(references),
            "nonce": nonce,
            "issued_at": epoch,
            "expires_at": epoch + 60,
        }
        capability = sign_capability(storage_claims, self._artifact_storage_signing_key())
        base = os.getenv("YUEKE_ARTIFACT_DOWNLOAD_BASE_URL", "/api/v1/artifact-storage")
        enqueue_event(
            self.session,
            event_type="runtime.artifact.direct_download_authorized",
            aggregate_type="runtime_artifact_bundle",
            aggregate_id=bundle_id,
            actor_user_id=self.user.user_id,
            idempotency_key=f"{bundle_id}:{nonce}",
            payload={"reference_ids": artifact_ids, "reference_count": len(artifact_ids), "expires_at": epoch + 60},
        )
        self.session.commit()
        return {
            "download_url": f"{base.rstrip('/')}/bundles/{bundle_id}?capability={quote(capability, safe='')}",
            "expires_in": 60,
            "artifact_count": len(references),
            "status": "READY",
        }

    @staticmethod
    def _audit_log_content(event: models.RuntimeEvent, request: models.RuntimeRequest) -> bytes:
        return _canonical_json_bytes({
            "event_id": event.runtime_event_id,
            "event_type": event.event_type,
            "runtime_instance_id": event.runtime_instance_id,
            "runtime_group_id": event.runtime_group_id,
            "actor_user_id": event.actor_user_id,
            "occurred_at": event.occurred_at.isoformat(),
            "detail": event.detail_json,
            "lab_release_id": request.lab_release_id,
            "course_id": request.course_id,
            "class_id": request.class_id,
            "student_id": request.student_id,
        })

    def download_artifact_bundle(self, assignment_id: str, capability: str):
        try:
            claims = ArtifactStorageClaims.model_validate(verify_capability(capability, self._artifact_storage_signing_key()))
        except ValueError as exc:
            raise ApiError("RUNTIME.ARTIFACT_STORAGE_CAPABILITY_INVALID", "制品存储下载能力无效", 403) from exc
        epoch = int(time())
        if claims.issued_at > epoch + 30 or claims.expires_at <= epoch:
            raise ApiError("RUNTIME.ARTIFACT_STORAGE_CAPABILITY_EXPIRED", "制品存储下载能力已过期", 403)
        if claims.assignment_id != assignment_id:
            raise ApiError("RUNTIME.ARTIFACT_ASSIGNMENT_MISMATCH", "下载地址与日志任务不一致", 403)
        if claims.grant_type == "DISTRIBUTION":
            if self.user.role != "student" or not self.user.student_id or claims.student_id != self.user.student_id:
                raise ApiError("AUTH.STUDENT_SCOPE_DENIED", "不能下载他人的日志任务", 403)
            if claims.subject_user_id != self.user.user_id or claims.subject_role != self.user.role:
                raise ApiError("AUTH.SCOPE_DENIED", "制品下载能力不属于当前账号", 403)
            if claims.class_id not in self.user.class_ids or claims.course_id not in self.user.course_ids:
                raise ApiError("AUTH.SCOPE_DENIED", "日志任务已超出当前课程或班级范围", 403)
        else:
            if claims.subject_user_id != self.user.user_id or claims.subject_role != self.user.role:
                raise ApiError("AUTH.SCOPE_DENIED", "制品下载能力不属于当前账号", 403)
            self._permission("runtime.read")
        signed_references = [item.model_dump(mode="json") for item in claims.references]
        if _reference_digest(signed_references) != claims.reference_digest:
            raise ApiError("RUNTIME.ARTIFACT_REFERENCE_SET_INVALID", "日志制品引用集合校验失败", 403)

        entries: list[BundleEntry] = []
        for reference in claims.references:
            if claims.distribution_type == "TRAFFIC":
                source = self.session.execute(
                    select(models.RuntimeArtifact, models.RuntimeRequest)
                    .join(models.RuntimeInstance, models.RuntimeInstance.runtime_instance_id == models.RuntimeArtifact.runtime_instance_id)
                    .join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeInstance.runtime_group_id)
                    .join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id)
                    .where(models.RuntimeArtifact.runtime_artifact_id == reference.reference_id, models.RuntimeArtifact.artifact_type == "TRAFFIC")
                ).one_or_none()
                if not source:
                    raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_NOT_FOUND", "分发的流量日志制品不存在", 404, {"reference_id": reference.reference_id})
                artifact, request = source
                if artifact.file_id != reference.file_id or artifact.sha256 != reference.sha256 or artifact.size_bytes != reference.size_bytes:
                    raise ApiError("RUNTIME.ARTIFACT_REFERENCE_MISMATCH", "流量日志制品引用已变化", 409, {"reference_id": reference.reference_id})
                file_object = self.session.get(FileObject, reference.file_id)
                if not file_object:
                    raise ApiError("RUNTIME.ARTIFACT_FILE_OBJECT_MISSING", "流量日志制品未登记文件对象", 409, {"reference_id": reference.reference_id, "file_id": reference.file_id})
                if file_object.sha256 != reference.sha256 or file_object.size_bytes != reference.size_bytes or file_object.original_name != reference.original_name:
                    raise ApiError("RUNTIME.ARTIFACT_REGISTRATION_MISMATCH", "流量日志制品与文件对象登记信息不一致", 409, {"reference_id": reference.reference_id, "file_id": reference.file_id})
                if claims.grant_type == "DIRECT":
                    instance = self.session.get(models.RuntimeInstance, artifact.runtime_instance_id)
                    if not instance:
                        raise ApiError("RUNTIME.NOT_FOUND", "实验实例不存在", 404)
                    self._instance_scope(instance)
                entries.append(BundleEntry(reference.reference_id, reference.original_name, reference.sha256, reference.size_bytes, file_object=file_object))
            else:
                source = self.session.execute(
                    select(models.RuntimeEvent, models.RuntimeRequest)
                    .join(models.RuntimeInstanceGroup, models.RuntimeInstanceGroup.runtime_group_id == models.RuntimeEvent.runtime_group_id)
                    .join(models.RuntimeRequest, models.RuntimeRequest.runtime_request_id == models.RuntimeInstanceGroup.runtime_request_id)
                    .where(models.RuntimeEvent.runtime_event_id == reference.reference_id)
                ).one_or_none()
                if not source:
                    raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_NOT_FOUND", "分发的审计日志不存在", 404, {"reference_id": reference.reference_id})
                event, request = source
                content = self._audit_log_content(event, request)
                entries.append(BundleEntry(reference.reference_id, reference.original_name, reference.sha256, reference.size_bytes, content=content))
            if claims.grant_type == "DISTRIBUTION" and (request.course_id != claims.course_id or request.class_id != claims.class_id or request.lab_release_id != claims.lab_release_id):
                raise ApiError("RUNTIME.DISTRIBUTION_SOURCE_SCOPE_MISMATCH", "分发日志来源超出授权实验范围", 403, {"reference_id": reference.reference_id})

        bundle_path = build_bundle(entries, assignment_id)
        event_key = f"{assignment_id}:{claims.nonce}"
        download_event_type = "runtime.artifact.distribution_bundle_downloaded" if claims.grant_type == "DISTRIBUTION" else "runtime.artifact.direct_bundle_downloaded"
        try:
            if not self.session.scalar(select(DomainEventOutbox.event_id).where(
                DomainEventOutbox.event_type == download_event_type,
                DomainEventOutbox.idempotency_key == event_key,
            )):
                enqueue_event(
                    self.session,
                    event_type=download_event_type,
                    aggregate_type="student_log_assignment" if claims.grant_type == "DISTRIBUTION" else "runtime_artifact_bundle",
                    aggregate_id=assignment_id,
                    actor_user_id=self.user.user_id,
                    idempotency_key=event_key,
                    payload={
                        "distribution_id": claims.distribution_id,
                        "grant_type": claims.grant_type,
                        "student_id": claims.student_id,
                        "course_id": claims.course_id,
                        "class_id": claims.class_id,
                        "lab_release_id": claims.lab_release_id,
                        "distribution_type": claims.distribution_type,
                        "reference_ids": [item.reference_id for item in claims.references],
                        "reference_count": len(claims.references),
                    },
                )
                try:
                    self.session.commit()
                except IntegrityError:
                    self.session.rollback()
                    if not self.session.scalar(select(DomainEventOutbox.event_id).where(
                        DomainEventOutbox.event_type == download_event_type,
                        DomainEventOutbox.idempotency_key == event_key,
                    )):
                        raise
            return bundle_path
        except Exception:
            bundle_path.unlink(missing_ok=True)
            raise

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
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise ApiError("RUNTIME.NODE_NOT_READY", "节点代理健康检查未通过", 422)
        capacity = self._validate_capacity_result(capacity)
        stamp = now()
        node = self.session.get(models.InfraNode, data.node_id) or models.InfraNode(node_id=data.node_id, name=data.name, agent_url=data.agent_url, status="READY", scheduling_paused=False, weight=data.weight, labels_json=data.labels, cpu_total=capacity["cpu_total"], memory_total_mb=capacity["memory_total_mb"], last_seen_at=stamp, created_at=stamp)
        node.name, node.agent_url, node.status, node.weight, node.labels_json, node.cpu_total, node.memory_total_mb, node.last_seen_at = data.name, data.agent_url, "READY", data.weight, data.labels, capacity["cpu_total"], capacity["memory_total_mb"], stamp
        self.session.add(node)
        self.session.add(models.InfraNodeHeartbeat(heartbeat_id=new_id("hbt"), node_id=node.node_id, observed_at=stamp, cpu_available=capacity["cpu_available"], memory_available_mb=capacity["memory_available_mb"], running_groups=capacity["running_groups"], image_digests_json=capacity.get("image_digests", []), detail_json={"engine": capacity.get("engine")}))
        self._event("infrastructure.node.registered", detail={"node_id": node.node_id, "name": node.name})
        self.session.commit()
        return next(x for x in self.nodes() if x["node_id"] == node.node_id)

    async def refresh_node_heartbeat(self, node_id: str, action_key: str) -> dict:
        self._admin_control()
        action, claimed = self._claim_admin_action("NODE_HEARTBEAT", node_id, action_key, {})
        if not claimed:
            return self._admin_action_replay(action)
        node = None
        try:
            node = self.session.scalar(
                select(models.InfraNode).where(models.InfraNode.node_id == node_id).with_for_update()
            )
            if not node:
                raise ApiError("RUNTIME.NODE_NOT_FOUND", "计算节点不存在", 404, {"node_id": node_id})
            client = self.agent_factory(node.agent_url)
            health, capacity = await client.health(), await client.capacity()
            if not isinstance(health, dict) or health.get("status") != "ok":
                raise ApiError("RUNTIME.NODE_NOT_READY", "节点代理健康检查未通过", 503)
            capacity = self._validate_capacity_result(capacity)
            stamp = now()
            node.status = "READY"
            node.cpu_total = float(capacity["cpu_total"])
            node.memory_total_mb = int(capacity["memory_total_mb"])
            node.last_seen_at = stamp
            heartbeat = models.InfraNodeHeartbeat(
                heartbeat_id=new_id("hbt"),
                node_id=node.node_id,
                observed_at=stamp,
                cpu_available=float(capacity["cpu_available"]),
                memory_available_mb=int(capacity["memory_available_mb"]),
                running_groups=int(capacity["running_groups"]),
                image_digests_json=capacity.get("image_digests", []),
                detail_json={"engine": capacity.get("engine"), "source": "ADMIN_REFRESH"},
            )
            self.session.add(heartbeat)
            result = {
                "node_id": node.node_id,
                "status": "READY",
                "observed_at": stamp.isoformat(),
                "cpu_available": heartbeat.cpu_available,
                "memory_available_mb": heartbeat.memory_available_mb,
                "running_groups": heartbeat.running_groups,
                "idempotent_replay": False,
            }
            self._event("runtime.node.heartbeat.completed", detail={"action_id": action.action_id, "result": result})
            self._complete_admin_action(action, result)
            self.session.commit()
            return result
        except (ApiError, KeyError, TypeError, ValueError) as raw_error:
            error = raw_error if isinstance(raw_error, ApiError) else ApiError("RUNTIME.NODE_RESPONSE_INVALID", "节点代理容量响应无效", 503)
            if error.code in LEASE_ERROR_CODES:
                self.session.rollback()
                raise error
            error = ApiError(error.code, error.message, error.status_code, {**error.details, "node_id": node_id})
            if node:
                node.status = "OFFLINE"
            self._event("runtime.node.heartbeat.failed", detail={"action_id": action.action_id, "node_id": node_id, "error_code": error.code})
            self._fail_admin_action(action, error)
            self.session.commit()
            raise error from raw_error

    async def retry_queue(
        self,
        queue_id: str,
        action_key: str,
        *,
        max_attempts: int = 5,
        ignore_not_before: bool = False,
        parent_action: models.RuntimeAdminAction | None = None,
    ) -> dict:
        self._admin_control()
        action, claimed = self._claim_admin_action(
            "QUEUE_RETRY", queue_id, action_key,
            {"max_attempts": max_attempts, "ignore_not_before": ignore_not_before},
        )
        if not claimed:
            return self._admin_action_replay(action)
        try:
            queued = self.session.scalar(
                select(models.RuntimeQueue).where(models.RuntimeQueue.queue_id == queue_id).with_for_update()
            )
            if not queued:
                raise ApiError("RUNTIME.QUEUE_NOT_FOUND", "运行队列项不存在", 404, {"queue_id": queue_id})
            request = self.session.get(models.RuntimeRequest, queued.runtime_request_id)
            if not request:
                raise ApiError("RUNTIME.REQUEST_NOT_FOUND", "运行请求不存在", 404)
            if queued.status == "DONE" and request.status == "RUNNING":
                result = {**self.request_view(request), "queue_id": queue_id, "idempotent_replay": False}
                self._complete_admin_action(action, result)
                self._event("runtime.queue.retry.noop", group_id=result.get("runtime_group_id"), detail={"action_id": action.action_id, "queue_id": queue_id})
                self.session.commit()
                return result
            if queued.status not in {"WAITING", "FAILED"}:
                raise ApiError("RUNTIME.QUEUE_RETRY_CONFLICT", "当前队列状态不允许重试", 409, {"queue_id": queue_id, "status": queued.status})
            if queued.attempts >= max_attempts:
                queued.status = "FAILED"
                request.status = "FAILED"
                request.provision_owner = None
                request.provision_lease_expires_at = None
                request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED"
                request.error_message = "运行队列已达到最大重试次数"
                request.updated_at = now()
                self._event("runtime.queue.retry.exhausted", detail={"action_id": action.action_id, "queue_id": queue_id, "attempts": queued.attempts})
                raise ApiError("RUNTIME.QUEUE_RETRY_EXHAUSTED", "运行队列已达到最大重试次数", 409, {"queue_id": queue_id, "attempts": queued.attempts})
            stamp = now()
            if queued.not_before and queued.not_before > stamp and not ignore_not_before:
                raise ApiError("RUNTIME.QUEUE_RETRY_TOO_EARLY", "运行队列尚未到可重试时间", 409, {"queue_id": queue_id, "not_before": queued.not_before.isoformat()})
            queued.status = "PROCESSING"
            queued.attempts += 1
            queued.enqueued_at = stamp
            queued.processing_owner = action.owner_token
            queued.lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
            request.status = "SCHEDULING"
            request.error_code = request.error_message = None
            request.provision_owner = action.owner_token
            request.provision_lease_expires_at = stamp + timedelta(seconds=QUEUE_LEASE_SECONDS)
            request.updated_at = stamp
            self._event(
                "runtime.queue.retry.requested",
                detail={"action_id": action.action_id, "queue_id": queue_id, "runtime_request_id": request.runtime_request_id, "attempt": queued.attempts},
            )
            self.session.commit()
            result = await self._schedule_and_provision(
                request,
                queue_owner=action.owner_token,
                parent_action=parent_action,
            )
            result = {**result, "queue_id": queue_id, "idempotent_replay": False}
            self._event("runtime.queue.retry.completed", group_id=result.get("runtime_group_id"), detail={"action_id": action.action_id, "queue_id": queue_id, "runtime_request_id": request.runtime_request_id, "status": result["status"]})
            self._complete_admin_action(action, result)
            self.session.commit()
            return result
        except ApiError as error:
            if error.code in LEASE_ERROR_CODES:
                self.session.rollback()
                raise
            queued = self.session.scalar(
                select(models.RuntimeQueue).where(models.RuntimeQueue.queue_id == queue_id).with_for_update().execution_options(populate_existing=True)
            )
            request_id = queued.runtime_request_id if queued else None
            if queued and queued.status == "PROCESSING" and queued.processing_owner == action.owner_token:
                request = self.session.get(models.RuntimeRequest, queued.runtime_request_id)
                if error.code == "RUNTIME.RETRY_STATE_CONFLICT":
                    queued.lease_expires_at = now() - timedelta(seconds=1)
                    if request:
                        request.status = "STARTING"
                else:
                    queued.status = "FAILED" if queued.attempts >= max_attempts else "WAITING"
                    queued.not_before = None if queued.status == "FAILED" else now() + timedelta(seconds=min(300, 5 * (2 ** min(queued.attempts, 6))))
                    if error.code == "RUNTIME.PROVISION_ROLLBACK_FAILED" and queued.status == "WAITING":
                        cleanup_group = self.session.scalar(
                            select(models.RuntimeInstanceGroup).where(
                                models.RuntimeInstanceGroup.runtime_request_id == queued.runtime_request_id
                            )
                        )
                        if cleanup_group and cleanup_group.cleanup_not_before:
                            queued.not_before = cleanup_group.cleanup_not_before
                    queued.processing_owner = None
                    queued.lease_expires_at = None
                    if request and request.status in {"SCHEDULING", "STARTING"}:
                        request.status = "QUEUED" if queued.status == "WAITING" else "FAILED"
                        request.provision_owner = None
                        request.provision_lease_expires_at = None
                        request.error_code = error.code
                        request.error_message = error.message
                        request.updated_at = now()
            self._event("runtime.queue.retry.failed", detail={"action_id": action.action_id, "queue_id": queue_id, "runtime_request_id": request_id, "error_code": error.code, "error_message": error.message, "status_code": error.status_code})
            self._fail_admin_action(action, error)
            self.session.commit()
            raise

    async def run_maintenance(self, data: RuntimeMaintenanceRun, action_key: str) -> dict:
        self._admin_control()
        request_parameters = data.model_dump()
        action, claimed = self._claim_admin_action("MAINTENANCE", "runtime", action_key, request_parameters)
        if not claimed:
            return self._admin_action_replay(action)
        try:
            return await self._run_maintenance_action(data, action)
        except ApiError as error:
            self._fail_admin_action(action, error)
            self.session.commit()
            raise
        except (KeyError, TypeError, ValueError) as raw_error:
            error = ApiError("RUNTIME.MAINTENANCE_FACT_INVALID", "运行底座恢复事实不完整", 503)
            self._fail_admin_action(action, error)
            self.session.commit()
            raise error from raw_error

    async def _run_maintenance_action(self, data: RuntimeMaintenanceRun, action: models.RuntimeAdminAction) -> dict:
        action = self._renew_admin_action(action)
        stamp = now()
        stale_before = stamp - timedelta(seconds=data.node_timeout_seconds)
        processing_before = stamp - timedelta(seconds=data.processing_timeout_seconds)
        stale_nodes = list(self.session.scalars(
            select(models.InfraNode).where(
                models.InfraNode.status == "READY",
                (models.InfraNode.last_seen_at.is_(None)) | (models.InfraNode.last_seen_at < stale_before),
            ).with_for_update()
        ))
        for node in stale_nodes:
            node.status = "OFFLINE"
            self._event("runtime.node.timed_out", detail={"node_id": node.node_id, "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None, "timeout_seconds": data.node_timeout_seconds})
        stale_processing_ids = list(self.session.scalars(
            select(models.RuntimeQueue.queue_id).where(
                models.RuntimeQueue.status == "PROCESSING",
                or_(
                    models.RuntimeQueue.lease_expires_at < stamp,
                    (models.RuntimeQueue.lease_expires_at.is_(None)) & (models.RuntimeQueue.enqueued_at < processing_before),
                ),
            )
        ))
        stale_scheduling_ids = list(self.session.scalars(
            select(models.RuntimeRequest.runtime_request_id).where(
                models.RuntimeRequest.status == "SCHEDULING",
                or_(
                    models.RuntimeRequest.provision_lease_expires_at < stamp,
                    and_(
                        models.RuntimeRequest.provision_lease_expires_at.is_(None),
                        models.RuntimeRequest.updated_at < processing_before,
                    ),
                ),
                ~select(models.RuntimeQueue.queue_id).where(
                    models.RuntimeQueue.runtime_request_id == models.RuntimeRequest.runtime_request_id
                ).exists(),
                ~select(models.RuntimeInstanceGroup.runtime_group_id).where(
                    models.RuntimeInstanceGroup.runtime_request_id == models.RuntimeRequest.runtime_request_id
                ).exists(),
            )
        ))
        stale_actions = list(self.session.scalars(
            select(models.RuntimeAdminAction).where(
                models.RuntimeAdminAction.status == "IN_PROGRESS",
                models.RuntimeAdminAction.lease_expires_at < stamp,
                models.RuntimeAdminAction.action_id != action.action_id,
            ).with_for_update()
        ))
        for stale_action in stale_actions:
            stale_action.status = "FAILED"
            stale_action.error_code = "RUNTIME.RECOVERY_INTERRUPTED"
            stale_action.error_message = "恢复动作执行中断，已由维护任务终止"
            stale_action.error_status_code = 503
            stale_action.error_details_json = {"action_id": stale_action.action_id, "recovered_by": action.action_id}
            stale_action.updated_at = stamp
        self.session.commit()

        recovered_processing: list[str] = []
        processing_results: list[dict] = []
        for request_id in stale_scheduling_ids:
            action = self._renew_admin_action(action)
            request = self.session.scalar(
                select(models.RuntimeRequest)
                .where(models.RuntimeRequest.runtime_request_id == request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not request or request.status != "SCHEDULING" or not (
                (request.provision_lease_expires_at and request.provision_lease_expires_at <= now())
                or (request.provision_lease_expires_at is None and request.updated_at < processing_before)
            ):
                continue
            existing_queue = self.session.scalar(select(models.RuntimeQueue).where(models.RuntimeQueue.runtime_request_id == request_id))
            existing_group = self.session.scalar(select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_request_id == request_id))
            if existing_queue or existing_group:
                continue
            queued = models.RuntimeQueue(
                queue_id=new_id("rtq"), runtime_request_id=request_id, status="WAITING",
                priority=100, attempts=0, not_before=None, processing_owner=None,
                lease_expires_at=None, enqueued_at=now(),
            )
            self.session.add(queued)
            request.status = "QUEUED"
            request.provision_owner = None
            request.provision_lease_expires_at = None
            request.error_code = "RUNTIME.RETRY_INTERRUPTED"
            request.error_message = "运行请求在调度前中断，已恢复为待处理"
            request.updated_at = now()
            self._event("runtime.request.scheduling_recovered", detail={"runtime_request_id": request_id, "queue_id": queued.queue_id})
            recovered_processing.append(queued.queue_id)
            processing_results.append({"queue_id": queued.queue_id, "status": "WAITING"})
            self.session.commit()
        for queue_id in stale_processing_ids:
            action = self._renew_admin_action(action)
            queued = self.session.scalar(
                select(models.RuntimeQueue).where(models.RuntimeQueue.queue_id == queue_id).with_for_update().execution_options(populate_existing=True)
            )
            if not queued or queued.status != "PROCESSING" or (queued.lease_expires_at and queued.lease_expires_at > now()):
                continue
            previous_owner = queued.processing_owner
            if previous_owner and previous_owner != action.owner_token:
                previous_action = self.session.scalar(
                    select(models.RuntimeAdminAction)
                    .where(models.RuntimeAdminAction.owner_token == previous_owner)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if previous_action and previous_action.status == "IN_PROGRESS":
                    previous_action.status = "FAILED"
                    previous_action.error_code = "RUNTIME.RECOVERY_INTERRUPTED"
                    previous_action.error_message = "队列处理租约已过期，执行权已由维护任务接管"
                    previous_action.error_status_code = 503
                    previous_action.error_details_json = {"queue_id": queue_id, "recovered_by": action.action_id}
                    previous_action.updated_at = now()
            queued.processing_owner = action.owner_token
            queued.lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
            group = self.session.scalar(
                select(models.RuntimeInstanceGroup)
                .where(models.RuntimeInstanceGroup.runtime_request_id == queued.runtime_request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            request = self.session.scalar(
                select(models.RuntimeRequest)
                .where(models.RuntimeRequest.runtime_request_id == queued.runtime_request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not request:
                queued.status = "FAILED"
                queued.processing_owner = None
                queued.lease_expires_at = None
                processing_results.append({"queue_id": queue_id, "status": "FAILED", "error_code": "RUNTIME.REQUEST_NOT_FOUND"})
                self.session.commit()
                continue
            request.provision_owner = None
            request.provision_lease_expires_at = None
            retry_exhausted = queued.attempts >= data.max_queue_attempts
            if request.status == "RUNNING":
                queued.status = "DONE"
            elif group and group.status in {"STARTING", "DESTROYING"}:
                cleanup_in_progress = (
                    group.status == "DESTROYING"
                    and (
                        group.cleanup_intent != "RETRY_RECOVERY"
                        or (
                            group.cleanup_owner and group.cleanup_owner != action.owner_token
                            and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > now()
                        )
                    )
                )
                if cleanup_in_progress:
                    queued.status = "FAILED" if retry_exhausted else "WAITING"
                    queued.not_before = None if retry_exhausted else group.cleanup_not_before or group.cleanup_lease_expires_at
                    queued.processing_owner = None
                    queued.lease_expires_at = None
                    if retry_exhausted:
                        request.status = "FAILED"
                        request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED"
                        request.error_message = "运行队列已达到最大重试次数，残留资源仍由清理任务接管"
                        request.updated_at = now()
                    processing_results.append({"queue_id": queue_id, "status": queued.status, "error_code": request.error_code or "RUNTIME.CLEANUP_IN_PROGRESS"})
                    self.session.commit()
                    continue
                node = self.session.get(models.InfraNode, group.node_id)
                if not node:
                    group.status = "DESTROYING"
                    group.cleanup_intent = "RETRY_RECOVERY"
                    group.cleanup_owner = None
                    group.cleanup_lease_expires_at = None
                    group.cleanup_error_code = "RUNTIME.NODE_NOT_FOUND"
                    group.cleanup_error_message = "运行组所属计算节点不存在"
                    group.cleanup_not_before = now() + timedelta(seconds=30)
                    queued.lease_expires_at = now() + timedelta(seconds=30)
                    processing_results.append({"queue_id": queue_id, "status": "FAILED", "error_code": "RUNTIME.NODE_NOT_FOUND"})
                    self.session.commit()
                    continue
                group.status = "DESTROYING"
                group.cleanup_attempts = int(group.cleanup_attempts or 0) + 1
                group.cleanup_intent = "RETRY_RECOVERY"
                group.cleanup_owner = action.owner_token
                group.cleanup_lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
                group.cleanup_not_before = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
                queued.lease_expires_at = now() + timedelta(seconds=QUEUE_LEASE_SECONDS)
                self.session.commit()
                try:
                    destroy_target = group.provider_group_id or group.runtime_group_id
                    agent = self.agent_factory(node.agent_url)
                    await self._capture_before_cleanup(agent, destroy_target, group.runtime_group_id)
                    cleanup_result = await agent.destroy(destroy_target)
                    self._validate_destroy_result(cleanup_result, destroy_target)
                except (ApiError, KeyError, TypeError, ValueError) as raw_error:
                    error = raw_error if isinstance(raw_error, ApiError) else ApiError(
                        "RUNTIME.RETRY_CLEANUP_FAILED", "节点代理销毁响应无效", 503
                    )
                    action = self._renew_admin_action(action)
                    queued = self.session.scalar(
                        select(models.RuntimeQueue).where(models.RuntimeQueue.queue_id == queue_id).with_for_update().execution_options(populate_existing=True)
                    )
                    group = self.session.scalar(
                        select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group.runtime_group_id).with_for_update().execution_options(populate_existing=True)
                    )
                    request = self.session.scalar(
                        select(models.RuntimeRequest)
                        .where(models.RuntimeRequest.runtime_request_id == request.runtime_request_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if (
                        not queued or queued.processing_owner != action.owner_token
                        or not queued.lease_expires_at or queued.lease_expires_at <= now()
                        or not group or group.cleanup_owner != action.owner_token
                        or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now()
                        or not request
                    ):
                        raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "队列恢复清理执行权已失效", 409)
                    group.cleanup_error_code = "RUNTIME.RETRY_CLEANUP_FAILED"
                    group.cleanup_error_message = error.message
                    group.cleanup_not_before = now() + timedelta(seconds=min(300, 5 * (2 ** min(group.cleanup_attempts, 6))))
                    group.cleanup_owner = None
                    group.cleanup_lease_expires_at = None
                    queued.lease_expires_at = group.cleanup_not_before
                    processing_results.append({"queue_id": queue_id, "status": "FAILED", "error_code": group.cleanup_error_code})
                    self.session.commit()
                    continue
                action = self._renew_admin_action(action)
                queued = self.session.scalar(
                    select(models.RuntimeQueue).where(models.RuntimeQueue.queue_id == queue_id).with_for_update().execution_options(populate_existing=True)
                )
                group = self.session.scalar(
                    select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group.runtime_group_id).with_for_update().execution_options(populate_existing=True)
                )
                request = self.session.scalar(
                    select(models.RuntimeRequest)
                    .where(models.RuntimeRequest.runtime_request_id == request.runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    not queued or queued.processing_owner != action.owner_token
                    or not queued.lease_expires_at or queued.lease_expires_at <= now()
                    or not group or group.cleanup_owner != action.owner_token
                    or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= now()
                    or not request
                ):
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "队列恢复清理执行权已失效", 409)
                group.status = "FAILED"
                group.provider_group_id = None
                group.cleanup_not_before = None
                group.cleanup_intent = None
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_error_code = group.cleanup_error_message = None
                request.status = "FAILED" if retry_exhausted else "QUEUED"
                request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED" if retry_exhausted else "RUNTIME.RETRY_INTERRUPTED"
                request.error_message = "运行队列已达到最大重试次数，残留资源已清理" if retry_exhausted else "上次队列重试未完成，远端资源已清理"
                request.updated_at = now()
                queued.status = "FAILED" if retry_exhausted else "WAITING"
            else:
                queued.status = "FAILED" if retry_exhausted else "WAITING"
                request.status = "FAILED" if retry_exhausted else "QUEUED"
                request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED" if retry_exhausted else "RUNTIME.RETRY_INTERRUPTED"
                request.error_message = "运行队列已达到最大重试次数" if retry_exhausted else "上次队列重试未完成，已恢复为待处理"
                request.updated_at = now()
            if retry_exhausted:
                self._event("runtime.queue.retry.exhausted", detail={"queue_id": queue_id, "attempts": queued.attempts})
            queued.not_before = None
            queued.processing_owner = None
            queued.lease_expires_at = None
            recovered_processing.append(queue_id)
            processing_results.append({"queue_id": queue_id, "status": queued.status})
            self._event("runtime.queue.processing_recovered", detail={"queue_id": queue_id, "runtime_request_id": queued.runtime_request_id})
            self.session.commit()

        expired_group_ids = list(self.session.scalars(
            select(models.RuntimeInstanceGroup.runtime_group_id).where(
                or_(
                    models.RuntimeInstanceGroup.status.in_(["RUNNING", "STARTING"]) & (models.RuntimeInstanceGroup.expires_at <= stamp),
                    and_(
                        models.RuntimeInstanceGroup.status == "STARTING",
                        or_(
                            and_(
                                models.RuntimeInstanceGroup.cleanup_intent.in_(["PROVISIONING", "REBUILD"]),
                                or_(models.RuntimeInstanceGroup.cleanup_lease_expires_at.is_(None), models.RuntimeInstanceGroup.cleanup_lease_expires_at <= stamp),
                            ),
                            and_(
                                models.RuntimeInstanceGroup.cleanup_intent.is_(None),
                                models.RuntimeInstanceGroup.scheduled_at <= processing_before,
                            ),
                        ),
                    ),
                    and_(
                        models.RuntimeInstanceGroup.status == "DESTROYING",
                        or_(models.RuntimeInstanceGroup.cleanup_intent.is_(None), models.RuntimeInstanceGroup.cleanup_intent.in_(["EXPIRY", "PROVISION_ROLLBACK", "MANUAL", "REBUILD", "ORPHAN_DESTROYED", "ORPHAN_FAILED"])),
                        or_(models.RuntimeInstanceGroup.cleanup_not_before.is_(None), models.RuntimeInstanceGroup.cleanup_not_before <= stamp),
                    ),
                ),
            ).order_by(models.RuntimeInstanceGroup.expires_at).limit(data.expiry_limit)
        ))

        expiry_results = []
        for group_id in expired_group_ids:
            action = self._renew_admin_action(action)
            preview = self.session.scalar(
                select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).execution_options(populate_existing=True)
            )
            cleanup_queue = None
            if preview and preview.cleanup_intent in {"PROVISION_ROLLBACK", "ORPHAN_FAILED"}:
                cleanup_queue = self.session.scalar(
                    select(models.RuntimeQueue)
                    .where(models.RuntimeQueue.runtime_request_id == preview.runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            group = self.session.scalar(
                select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
            )
            if not group or group.status not in {"RUNNING", "STARTING", "DESTROYING"}:
                continue
            claim_time = now()
            active_cleanup_owner = (
                group.cleanup_owner and group.cleanup_owner != action.owner_token
                and group.cleanup_lease_expires_at and group.cleanup_lease_expires_at > claim_time
            )
            if active_cleanup_owner:
                continue
            stale_starting = group.status == "STARTING" and (
                (group.cleanup_intent in {"PROVISIONING", "REBUILD"} and (not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= claim_time))
                or (group.cleanup_intent is None and group.scheduled_at <= processing_before)
            )
            if group.status in {"RUNNING", "STARTING"} and group.expires_at > claim_time and not stale_starting:
                continue
            if group.status == "DESTROYING" and (
                group.cleanup_intent not in {None, "EXPIRY", "PROVISION_ROLLBACK", "MANUAL", "REBUILD", "ORPHAN_DESTROYED", "ORPHAN_FAILED"}
                or (group.cleanup_not_before and group.cleanup_not_before > claim_time)
            ):
                continue
            if group.cleanup_intent == "PROVISIONING" or (group.status == "STARTING" and group.cleanup_intent is None):
                cleanup_intent = "PROVISION_ROLLBACK"
            elif group.cleanup_intent in {"PROVISION_ROLLBACK", "MANUAL", "REBUILD", "ORPHAN_DESTROYED", "ORPHAN_FAILED"}:
                cleanup_intent = group.cleanup_intent
            else:
                cleanup_intent = "EXPIRY"
            if cleanup_intent in {"PROVISION_ROLLBACK", "ORPHAN_FAILED"} and cleanup_queue is None:
                cleanup_queue = self.session.scalar(
                    select(models.RuntimeQueue)
                    .where(models.RuntimeQueue.runtime_request_id == group.runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            node = self.session.get(models.InfraNode, group.node_id)
            request = self.session.scalar(
                select(models.RuntimeRequest)
                .where(models.RuntimeRequest.runtime_request_id == group.runtime_request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            instances = list(self.session.scalars(
                select(models.RuntimeInstance)
                .where(models.RuntimeInstance.runtime_group_id == group_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ))
            primary = next((item for item in instances if item.role == "STUDENT_WORKSTATION"), instances[0] if instances else None)
            if not node or not request:
                group.status = "DESTROYING"
                group.cleanup_intent = cleanup_intent
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_error_code = "RUNTIME.CLEANUP_FACT_INVALID"
                group.cleanup_error_message = "运行组缺少节点或请求事实"
                group.cleanup_not_before = now() + timedelta(seconds=60)
                expiry_results.append({"runtime_group_id": group_id, "status": "DESTROYING", "error_code": group.cleanup_error_code})
                self.session.commit()
                continue
            request.provision_owner = None
            request.provision_lease_expires_at = None
            group.status = "DESTROYING"
            group.cleanup_attempts = int(group.cleanup_attempts or 0) + 1
            group.cleanup_intent = cleanup_intent
            group.cleanup_owner = action.owner_token
            group.cleanup_lease_expires_at = claim_time + timedelta(seconds=QUEUE_LEASE_SECONDS)
            group.cleanup_not_before = group.cleanup_lease_expires_at
            if cleanup_queue:
                cleanup_queue.not_before = group.cleanup_not_before
            for item in instances:
                item.status = "DESTROYING"
            runtime_request_id = group.runtime_request_id
            destroy_target = group.provider_group_id or group.runtime_group_id
            self.session.commit()
            try:
                agent = self.agent_factory(node.agent_url)
                await self._capture_before_cleanup(agent, destroy_target, group_id)
                cleanup_result = await agent.destroy(destroy_target)
                self._validate_destroy_result(cleanup_result, destroy_target)
                action = self._renew_admin_action(action)
                ended = now()
                if cleanup_intent in {"PROVISION_ROLLBACK", "ORPHAN_FAILED"}:
                    cleanup_queue = self.session.scalar(
                        select(models.RuntimeQueue)
                        .where(models.RuntimeQueue.runtime_request_id == runtime_request_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                group = self.session.scalar(
                    select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
                )
                if (
                    not group or group.status != "DESTROYING" or group.cleanup_owner != action.owner_token
                    or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= ended
                    or group.cleanup_intent != cleanup_intent
                ):
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "运行组清理执行权已失效", 409)
                request = self.session.scalar(
                    select(models.RuntimeRequest)
                    .where(models.RuntimeRequest.runtime_request_id == runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                instances = list(self.session.scalars(
                    select(models.RuntimeInstance)
                    .where(models.RuntimeInstance.runtime_group_id == group_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ))
                if not request:
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "运行请求恢复事实已失效", 409)
                primary = next((item for item in instances if item.role == "STUDENT_WORKSTATION"), instances[0] if instances else None)
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_not_before = None
                group.cleanup_error_code = group.cleanup_error_message = None
                if cleanup_intent == "PROVISION_ROLLBACK":
                    group.status = "FAILED"
                    group.provider_group_id = None
                    group.cleanup_intent = None
                    if cleanup_queue is None:
                        cleanup_queue = models.RuntimeQueue(
                            queue_id=new_id("rtq"), runtime_request_id=request.runtime_request_id,
                            status="WAITING", priority=100, attempts=0, not_before=None,
                            processing_owner=None, lease_expires_at=None, enqueued_at=ended,
                        )
                        self.session.add(cleanup_queue)
                    retry_exhausted = cleanup_queue.attempts >= data.max_queue_attempts
                    request.status = "FAILED" if retry_exhausted else "QUEUED"
                    request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED" if retry_exhausted else "RUNTIME.RETRY_INTERRUPTED"
                    request.error_message = "运行队列已达到最大重试次数，创建残留资源已清理" if retry_exhausted else "创建失败残留资源已清理，可重新调度"
                    request.updated_at = ended
                    if cleanup_queue:
                        cleanup_queue.status = "FAILED" if retry_exhausted else "WAITING"
                        cleanup_queue.not_before = None
                        cleanup_queue.processing_owner = None
                        cleanup_queue.lease_expires_at = None
                    self._event("runtime.group.rollback_completed", group_id=group_id, detail={"runtime_request_id": request.runtime_request_id})
                    expiry_results.append({"runtime_group_id": group_id, "status": "FAILED", "cleanup_intent": cleanup_intent})
                elif cleanup_intent == "ORPHAN_FAILED":
                    group.status = "FAILED"
                    group.provider_group_id = None
                    group.cleanup_intent = None
                    if cleanup_queue:
                        retry_exhausted = cleanup_queue.attempts >= data.max_queue_attempts
                        cleanup_queue.status = "FAILED" if retry_exhausted else "WAITING"
                        cleanup_queue.not_before = None
                        cleanup_queue.processing_owner = None
                        cleanup_queue.lease_expires_at = None
                        request.status = "FAILED" if retry_exhausted else "QUEUED"
                        request.error_code = "RUNTIME.QUEUE_RETRY_EXHAUSTED" if retry_exhausted else "RUNTIME.RETRY_INTERRUPTED"
                        request.error_message = "运行队列已达到最大重试次数，孤儿资源已清理" if retry_exhausted else "迟到创建产生的孤儿资源已清理，可重新调度"
                        request.updated_at = ended
                    self._event("runtime.group.orphan_cleanup_completed", group_id=group_id, detail={"runtime_request_id": request.runtime_request_id, "restored_status": "FAILED"})
                    expiry_results.append({"runtime_group_id": group_id, "status": "FAILED", "cleanup_intent": cleanup_intent})
                elif cleanup_intent == "REBUILD":
                    group.status = "FAILED"
                    group.provider_group_id = None
                    group.cleanup_intent = None
                    for item in instances:
                        item.status, item.ended_at = "FAILED", ended
                    request.status, request.error_code, request.error_message, request.updated_at = "FAILED", "RUNTIME.REBUILD_INTERRUPTED", "实验重建中断，残留资源已清理", ended
                    self._event("runtime.group.rebuild_cleanup_completed", group_id=group_id, detail={"runtime_request_id": request.runtime_request_id})
                    expiry_results.append({"runtime_group_id": group_id, "status": "FAILED", "cleanup_intent": cleanup_intent})
                elif cleanup_intent == "ORPHAN_DESTROYED":
                    group.status = "DESTROYED"
                    group.provider_group_id = None
                    group.cleanup_intent = None
                    for item in instances:
                        item.status = "DESTROYED"
                        item.ended_at = item.ended_at or ended
                    self._event("runtime.group.orphan_cleanup_completed", group_id=group_id, detail={"runtime_request_id": request.runtime_request_id, "restored_status": "DESTROYED"})
                    expiry_results.append({"runtime_group_id": group_id, "status": "DESTROYED", "cleanup_intent": cleanup_intent})
                else:
                    group.status, group.destroyed_at = "DESTROYED", ended
                    group.cleanup_intent = None
                    for item in instances:
                        item.status, item.ended_at = "DESTROYED", ended
                    request.status, request.updated_at, request.last_activity_at = "CANCELED", ended, ended
                    cleanup_reason = "待完成的人工销毁已恢复" if cleanup_intent == "MANUAL" else "运行时限到期自动回收"
                    self._event("lab.instance.destroyed", instance_id=primary.runtime_instance_id if primary else None, group_id=group_id, detail=self._projection_payload(request, primary, status="DESTROYED", reason=cleanup_reason), idempotency_key=f"lab.instance.destroyed:{group_id}:g{group.provider_generation}")
                    expiry_results.append({"runtime_group_id": group_id, "status": "DESTROYED"})
            except (ApiError, KeyError, TypeError, ValueError) as raw_error:
                if isinstance(raw_error, ApiError) and raw_error.code in LEASE_ERROR_CODES:
                    raise
                error = raw_error if isinstance(raw_error, ApiError) else ApiError("RUNTIME.EXPIRY_CLEANUP_FAILED", "节点代理销毁响应无效", 503)
                action = self._renew_admin_action(action)
                failed = now()
                if cleanup_intent in {"PROVISION_ROLLBACK", "ORPHAN_FAILED"}:
                    cleanup_queue = self.session.scalar(
                        select(models.RuntimeQueue)
                        .where(models.RuntimeQueue.runtime_request_id == runtime_request_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                group = self.session.scalar(
                    select(models.RuntimeInstanceGroup).where(models.RuntimeInstanceGroup.runtime_group_id == group_id).with_for_update().execution_options(populate_existing=True)
                )
                if (
                    not group or group.cleanup_owner != action.owner_token
                    or not group.cleanup_lease_expires_at or group.cleanup_lease_expires_at <= failed
                    or group.cleanup_intent != cleanup_intent
                ):
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "运行组清理执行权已失效", 409)
                request = self.session.scalar(
                    select(models.RuntimeRequest)
                    .where(models.RuntimeRequest.runtime_request_id == runtime_request_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if not request:
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "运行请求恢复事实已失效", 409)
                group.status = "DESTROYING"
                group.cleanup_owner = None
                group.cleanup_lease_expires_at = None
                group.cleanup_error_code = (
                    "RUNTIME.PROVISION_ROLLBACK_FAILED" if cleanup_intent == "PROVISION_ROLLBACK"
                    else "RUNTIME.MANUAL_CLEANUP_FAILED" if cleanup_intent == "MANUAL"
                    else "RUNTIME.REBUILD_CLEANUP_FAILED" if cleanup_intent == "REBUILD"
                    else "RUNTIME.ORPHAN_CLEANUP_FAILED" if cleanup_intent in {"ORPHAN_FAILED", "ORPHAN_DESTROYED"}
                    else "RUNTIME.EXPIRY_CLEANUP_FAILED"
                )
                group.cleanup_error_message = error.message
                group.cleanup_not_before = failed + timedelta(seconds=min(300, 5 * (2 ** min(group.cleanup_attempts, 6))))
                retry_exhausted = bool(cleanup_queue and cleanup_queue.attempts >= data.max_queue_attempts)
                if cleanup_queue:
                    cleanup_queue.status = "FAILED" if retry_exhausted else "WAITING"
                    cleanup_queue.not_before = None if retry_exhausted else group.cleanup_not_before
                    cleanup_queue.processing_owner = None
                    cleanup_queue.lease_expires_at = None
                elif cleanup_intent == "PROVISION_ROLLBACK":
                    cleanup_queue = models.RuntimeQueue(
                        queue_id=new_id("rtq"), runtime_request_id=request.runtime_request_id,
                        status="WAITING", priority=100, attempts=0, not_before=group.cleanup_not_before,
                        processing_owner=None, lease_expires_at=None, enqueued_at=failed,
                    )
                    self.session.add(cleanup_queue)
                request.status, request.error_code, request.error_message, request.updated_at = (
                    (
                        "FAILED" if retry_exhausted else "QUEUED",
                        "RUNTIME.QUEUE_RETRY_EXHAUSTED" if retry_exhausted else group.cleanup_error_code,
                        "运行队列已达到最大重试次数，创建残留资源仍待清理" if retry_exhausted else error.message,
                        failed,
                    )
                    if cleanup_intent == "PROVISION_ROLLBACK"
                    else (request.status, request.error_code, request.error_message, request.updated_at)
                    if cleanup_intent in {"ORPHAN_FAILED", "ORPHAN_DESTROYED"}
                    else ("FAILED", group.cleanup_error_code, error.message, failed)
                    if cleanup_intent == "REBUILD"
                    else ("FAILED", group.cleanup_error_code, error.message, failed)
                )
                self._event("runtime.group.cleanup_failed", instance_id=primary.runtime_instance_id if primary else None, group_id=group_id, detail={"error_code": group.cleanup_error_code, "attempt": group.cleanup_attempts, "retry_at": group.cleanup_not_before.isoformat()})
                expiry_results.append({"runtime_group_id": group_id, "status": "DESTROYING", "error_code": group.cleanup_error_code})
            self.session.commit()

        cleanup_task_ids = list(self.session.scalars(
            select(models.RuntimeCleanupTask.cleanup_task_id).where(
                or_(
                    and_(
                        models.RuntimeCleanupTask.status.in_(["WAITING", "FAILED"]),
                        models.RuntimeCleanupTask.attempts < data.max_queue_attempts,
                        or_(
                            models.RuntimeCleanupTask.not_before.is_(None),
                            models.RuntimeCleanupTask.not_before <= now(),
                        ),
                    ),
                    and_(
                        models.RuntimeCleanupTask.status == "PROCESSING",
                        or_(
                            models.RuntimeCleanupTask.lease_expires_at.is_(None),
                            models.RuntimeCleanupTask.lease_expires_at <= now(),
                        ),
                    ),
                ),
            ).order_by(models.RuntimeCleanupTask.created_at).limit(data.expiry_limit)
        ))
        for cleanup_task_id in cleanup_task_ids:
            action = self._renew_admin_action(action)
            task = self.session.scalar(
                select(models.RuntimeCleanupTask)
                .where(models.RuntimeCleanupTask.cleanup_task_id == cleanup_task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            claim_time = now()
            if (
                not task or task.status not in {"WAITING", "FAILED", "PROCESSING"}
                or (task.status != "PROCESSING" and task.attempts >= data.max_queue_attempts)
                or (task.status != "PROCESSING" and task.not_before and task.not_before > claim_time)
                or (task.status == "PROCESSING" and task.lease_expires_at and task.lease_expires_at > claim_time)
                or (
                    task.processing_owner and task.processing_owner != action.owner_token
                    and task.lease_expires_at and task.lease_expires_at > claim_time
                )
            ):
                continue
            current_group = self.session.scalar(
                select(models.RuntimeInstanceGroup)
                .where(models.RuntimeInstanceGroup.runtime_group_id == task.runtime_group_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            targets_current_generation = bool(
                current_group
                and current_group.node_id == task.node_id
                and current_group.provider_generation == task.provider_generation
                and current_group.provider_group_id == task.provider_group_id
            )
            if targets_current_generation:
                task.processing_owner = None
                task.lease_expires_at = None
                task.updated_at = claim_time
                if current_group.status in {"RUNNING", "DESTROYED"}:
                    task.status = "DONE"
                    task.not_before = None
                    task.error_code = task.error_message = None
                    self._event(
                        "runtime.orphan.cleanup_superseded", group_id=task.runtime_group_id,
                        detail={
                            "cleanup_task_id": task.cleanup_task_id,
                            "node_id": task.node_id,
                            "provider_generation": task.provider_generation,
                            "group_status": current_group.status,
                        },
                    )
                else:
                    task.status = "WAITING"
                    task.not_before = max(
                        claim_time + timedelta(seconds=60),
                        current_group.cleanup_lease_expires_at or claim_time,
                    )
                    task.error_code = "RUNTIME.CLEANUP_FENCED_CURRENT_GENERATION"
                    task.error_message = "清理任务仍指向当前运行代次，已延后处理"
                self.session.commit()
                continue
            node = self.session.get(models.InfraNode, task.node_id)
            if not node:
                task.attempts += 1
                task.status = "FAILED" if task.attempts >= data.max_queue_attempts else "WAITING"
                task.not_before = None if task.status == "FAILED" else claim_time + timedelta(seconds=60)
                task.processing_owner = None
                task.lease_expires_at = None
                task.error_code = "RUNTIME.NODE_NOT_FOUND"
                task.error_message = "孤儿资源所属计算节点不存在"
                task.updated_at = claim_time
                expiry_results.append({
                    "runtime_group_id": task.runtime_group_id,
                    "status": "FAILED" if task.status == "FAILED" else "DESTROYING",
                    "error_code": task.error_code,
                    "cleanup_intent": task.intent,
                })
                self.session.commit()
                continue
            task.status = "PROCESSING"
            task.attempts += 1
            task.processing_owner = action.owner_token
            task.lease_expires_at = claim_time + timedelta(seconds=QUEUE_LEASE_SECONDS)
            task.not_before = task.lease_expires_at
            task.updated_at = claim_time
            node_url = node.agent_url
            provider_group_id = task.provider_group_id
            runtime_group_id = task.runtime_group_id
            cleanup_intent = task.intent
            self.session.commit()
            try:
                agent = self.agent_factory(node_url)
                await self._capture_before_cleanup(agent, provider_group_id, runtime_group_id)
                cleanup_result = await agent.destroy(provider_group_id)
                self._validate_destroy_result(cleanup_result, provider_group_id)
                action = self._renew_admin_action(action)
                finished = now()
                task = self.session.scalar(
                    select(models.RuntimeCleanupTask)
                    .where(models.RuntimeCleanupTask.cleanup_task_id == cleanup_task_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    not task or task.status != "PROCESSING" or task.processing_owner != action.owner_token
                    or not task.lease_expires_at or task.lease_expires_at <= finished
                ):
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "孤儿资源清理执行权已失效", 409)
                task.status = "DONE"
                task.not_before = None
                task.processing_owner = None
                task.lease_expires_at = None
                task.error_code = task.error_message = None
                task.updated_at = finished
                self._event(
                    "runtime.orphan.cleanup_completed", group_id=runtime_group_id,
                    detail={"cleanup_task_id": cleanup_task_id, "node_id": task.node_id, "intent": cleanup_intent, "provider_generation": task.provider_generation},
                )
                expiry_results.append({
                    "runtime_group_id": runtime_group_id,
                    "status": "ORPHAN_CLEANED",
                    "cleanup_intent": cleanup_intent,
                })
            except (ApiError, KeyError, TypeError, ValueError) as raw_error:
                if isinstance(raw_error, ApiError) and raw_error.code in LEASE_ERROR_CODES:
                    raise
                error = raw_error if isinstance(raw_error, ApiError) else ApiError(
                    "RUNTIME.ORPHAN_CLEANUP_FAILED", "节点代理孤儿资源清理响应无效", 503
                )
                action = self._renew_admin_action(action)
                failed = now()
                task = self.session.scalar(
                    select(models.RuntimeCleanupTask)
                    .where(models.RuntimeCleanupTask.cleanup_task_id == cleanup_task_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    not task or task.status != "PROCESSING" or task.processing_owner != action.owner_token
                    or not task.lease_expires_at or task.lease_expires_at <= failed
                ):
                    raise ApiError("RUNTIME.RECOVERY_LEASE_LOST", "孤儿资源清理执行权已失效", 409)
                task.status = "FAILED" if task.attempts >= data.max_queue_attempts else "WAITING"
                task.not_before = None if task.status == "FAILED" else failed + timedelta(seconds=min(300, 5 * (2 ** min(task.attempts, 6))))
                task.processing_owner = None
                task.lease_expires_at = None
                task.error_code = "RUNTIME.ORPHAN_CLEANUP_FAILED"
                task.error_message = error.message
                task.updated_at = failed
                expiry_results.append({
                    "runtime_group_id": runtime_group_id,
                    "status": "FAILED" if task.status == "FAILED" else "DESTROYING",
                    "error_code": task.error_code,
                    "cleanup_intent": cleanup_intent,
                })
            self.session.commit()

        eligible_queue_ids = list(self.session.scalars(
            select(models.RuntimeQueue.queue_id).where(
                models.RuntimeQueue.status == "WAITING",
                models.RuntimeQueue.attempts < data.max_queue_attempts,
                (models.RuntimeQueue.not_before.is_(None)) | (models.RuntimeQueue.not_before <= now()),
            ).order_by(desc(models.RuntimeQueue.priority), models.RuntimeQueue.enqueued_at).limit(data.retry_limit)
        ))
        queue_results = []
        for queue_id in eligible_queue_ids:
            action = self._renew_admin_action(action)
            try:
                retried = await self.retry_queue(
                    queue_id,
                    f"maintenance:{action.action_id}:{queue_id}",
                    max_attempts=data.max_queue_attempts,
                    parent_action=action,
                )
                action = self._renew_admin_action(action)
                queue_results.append({"queue_id": queue_id, "status": retried["status"]})
            except ApiError as error:
                if error.code in LEASE_ERROR_CODES:
                    raise
                action = self._renew_admin_action(action)
                queue_results.append({"queue_id": queue_id, "status": "FAILED", "error_code": error.code})
        result = {
            "status": "COMPLETED_WITH_ERRORS" if any(item.get("status") in {"FAILED", "DESTROYING"} for item in [*processing_results, *expiry_results, *queue_results]) else "COMPLETED",
            "automatic": False,
            "node_timeouts": [node.node_id for node in stale_nodes],
            "processing_recovered": recovered_processing,
            "processing_results": processing_results,
            "expiry_results": expiry_results,
            "queue_results": queue_results,
            "completed_at": now().isoformat(),
            "idempotent_replay": False,
        }
        self._event("runtime.maintenance.completed", detail={"action_id": action.action_id, "request": data.model_dump(), "result": result})
        self._complete_admin_action(action, result)
        self.session.commit()
        return result

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
