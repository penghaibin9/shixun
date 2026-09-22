import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ID = str
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
KEY_PATTERN = r"^[a-z][a-z0-9_-]{1,63}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LabVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class JudgeType(StrEnum):
    FILE_HASH = "FILE_HASH"
    COMMAND_EXIT = "COMMAND_EXIT"
    FILE_EXISTS = "FILE_EXISTS"
    PORT_LISTEN = "PORT_LISTEN"
    HTTP_RESPONSE = "HTTP_RESPONSE"


class NetworkEnvironment(StrEnum):
    ISOLATED = "ISOLATED"
    SHARED = "SHARED"
    CUSTOM = "CUSTOM"


class RuntimePolicy(StrictModel):
    max_attempts: int = Field(ge=1, le=10)
    timeout_minutes: int = Field(ge=5, le=240)


class SceneNetwork(StrictModel):
    network_key: str = Field(pattern=KEY_PATTERN)
    cidr_policy: str = Field(min_length=1, max_length=64)
    internet_access: bool = False
    egress_allowlist: list[str] = Field(default_factory=list, max_length=32)
    student_isolation: bool = True


class SceneNode(StrictModel):
    node_key: str = Field(pattern=KEY_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    network_env: NetworkEnvironment
    network_keys: list[str] = Field(min_length=1, max_length=8)
    device_model: str = Field(min_length=1, max_length=128)
    image_id: ID = Field(min_length=1, max_length=36)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    cpu_limit: float = Field(gt=0, le=16)
    memory_mb: int = Field(ge=128, le=32768)
    ip_policy: str = Field(min_length=1, max_length=64)
    ports: list[int] = Field(default_factory=list, max_length=32)
    startup_command: str = Field(default="", max_length=512)
    mounts: list[str] = Field(default_factory=list, max_length=16)
    position_x: int = Field(default=80, ge=0, le=4000)
    position_y: int = Field(default=80, ge=0, le=4000)

    @field_validator("ports")
    @classmethod
    def valid_ports(cls, ports: list[int]) -> list[int]:
        if any(port < 1 or port > 65535 for port in ports):
            raise ValueError("端口必须在 1 到 65535 之间")
        if len(ports) != len(set(ports)):
            raise ValueError("端口不能重复")
        return ports


class ImageBinding(StrictModel):
    node_key: str = Field(pattern=KEY_PATTERN)
    infra_image_id: ID = Field(min_length=1, max_length=36)
    digest: str = Field(pattern=DIGEST_PATTERN)


class DagNode(StrictModel):
    node_key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    order_no: int = Field(ge=0, le=999)


class DagEdge(StrictModel):
    from_node_key: str = Field(pattern=KEY_PATTERN)
    to_node_key: str = Field(pattern=KEY_PATTERN)

    @model_validator(mode="after")
    def not_self_referencing(self):
        if self.from_node_key == self.to_node_key:
            raise ValueError("DAG 边不能指向自身")
        return self


class Checkpoint(StrictModel):
    checkpoint_id: str = Field(pattern=KEY_PATTERN)
    dag_node_id: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    score: int = Field(ge=0, le=1000)
    judge_type: JudgeType
    judge_target: str = Field(min_length=1, max_length=512)
    judge_config_json: dict[str, Any]
    failure_message: str = Field(min_length=1, max_length=512)
    timeout_seconds: int = Field(ge=1, le=300)
    order_no: int = Field(ge=0, le=999)

    @field_validator("judge_config_json")
    @classmethod
    def bounded_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > 4096:
            raise ValueError("判定配置不得超过 4096 字节")
        blocked = {"script", "shell", "docker_socket", "privileged"}
        if blocked.intersection(value):
            raise ValueError("判定配置不得包含可执行脚本或特权参数")
        return value

    @model_validator(mode="after")
    def validate_judge_contract(self):
        config = self.judge_config_json
        required: dict[JudgeType, set[str]] = {
            JudgeType.FILE_EXISTS: {"path"},
            JudgeType.FILE_HASH: {"left_path", "right_path", "algorithm"},
            JudgeType.COMMAND_EXIT: {"command_ref", "expected_exit"},
            JudgeType.PORT_LISTEN: {"host", "port"},
            JudgeType.HTTP_RESPONSE: {"path", "status_code"},
        }
        allowed: dict[JudgeType, set[str]] = {
            JudgeType.FILE_EXISTS: {"path", "additional_paths", "minimum_size", "format"},
            JudgeType.FILE_HASH: {"left_path", "right_path", "algorithm"},
            JudgeType.COMMAND_EXIT: {"command_ref", "expected_exit", "output_contains"},
            JudgeType.PORT_LISTEN: {"host", "port"},
            JudgeType.HTTP_RESPONSE: {"path", "port", "status_code"},
        }
        missing = required[self.judge_type] - config.keys()
        if missing:
            raise ValueError(f"{self.judge_type} 缺少配置：{', '.join(sorted(missing))}")
        unknown = config.keys() - allowed[self.judge_type]
        if unknown:
            raise ValueError(f"{self.judge_type} 包含未批准配置：{', '.join(sorted(unknown))}")
        if self.judge_type == JudgeType.FILE_HASH and config.get("algorithm") != "sha256":
            raise ValueError("文件哈希判定当前只允许 sha256")
        if self.judge_type == JudgeType.COMMAND_EXIT and not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", str(config.get("command_ref", ""))):
            raise ValueError("命令判定必须引用经 D 线审核的命令标识，不能提交原始脚本")
        return self


class LabDefinitionSpec(StrictModel):
    lab_definition_id: ID = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(ge=5, le=240)
    total_score: int = Field(ge=1, le=1000)
    nodes: list[SceneNode] = Field(max_length=32)
    networks: list[SceneNetwork] = Field(max_length=16)
    image_bindings: list[ImageBinding] = Field(max_length=32)
    steps: list[DagNode] = Field(max_length=128)
    edges: list[DagEdge] = Field(max_length=256)
    checkpoints: list[Checkpoint] = Field(max_length=128)
    runtime_policy: RuntimePolicy

    @model_validator(mode="after")
    def validate_references_and_uniqueness(self):
        def keys(items: list[Any], attr: str, label: str) -> set[str]:
            values = [getattr(item, attr) for item in items]
            if len(values) != len(set(values)):
                raise ValueError(f"{label}存在重复标识")
            return set(values)

        network_keys = keys(self.networks, "network_key", "网络")
        node_keys = keys(self.nodes, "node_key", "场景节点")
        step_keys = keys(self.steps, "node_key", "DAG 节点")
        keys(self.checkpoints, "checkpoint_id", "得分点")
        for node in self.nodes:
            if not set(node.network_keys).issubset(network_keys):
                raise ValueError(f"场景节点 {node.node_key} 引用了不存在的网络")
        binding_nodes = keys(self.image_bindings, "node_key", "镜像绑定")
        if binding_nodes != node_keys:
            raise ValueError("每个场景节点必须且只能有一个镜像绑定")
        bindings = {item.node_key: item for item in self.image_bindings}
        for node in self.nodes:
            binding = bindings[node.node_key]
            if node.image_id != binding.infra_image_id or node.image_digest != binding.digest:
                raise ValueError(f"节点 {node.node_key} 与镜像绑定不一致")
        for edge in self.edges:
            if edge.from_node_key not in step_keys or edge.to_node_key not in step_keys:
                raise ValueError("DAG 边引用了不存在的步骤")
        for checkpoint in self.checkpoints:
            if checkpoint.dag_node_id not in step_keys:
                raise ValueError(f"得分点 {checkpoint.checkpoint_id} 引用了不存在的步骤")
        return self


class LabCreate(StrictModel):
    course_id: ID = Field(min_length=1, max_length=36)
    code: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=64)
    objective: str = Field(min_length=1, max_length=4000)
    spec: LabDefinitionSpec


class LabVersionPatch(StrictModel):
    spec: LabDefinitionSpec


class TemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=4000)
    spec: dict[str, Any]


class DiagramInput(StrictModel):
    file_id: ID = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    order_no: int = Field(ge=0, le=999)


class KnowledgeInput(StrictModel):
    course_id: ID = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    explain_text: str = Field(min_length=1, max_length=10000)
    question_ids: list[ID] = Field(default_factory=list, max_length=200)
    diagrams: list[DiagramInput] = Field(default_factory=list, max_length=20)


class ReleaseCreate(StrictModel):
    lab_version_id: ID
    course_id: ID
    class_id: ID
    lesson_id: ID
    opens_at: datetime
    closes_at: datetime
    max_attempts: int = Field(ge=1, le=10)
    timeout_minutes: int = Field(ge=5, le=240)
    max_concurrency: int = Field(ge=1, le=200)
    teacher_preview_required: bool = True

    @model_validator(mode="after")
    def valid_window(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class CloneVersionInput(StrictModel):
    source_lab_version_id: ID | None = None


class ListResponse(StrictModel):
    items: list[dict[str, Any]]
    page: int = 1
    page_size: int
    total: int

