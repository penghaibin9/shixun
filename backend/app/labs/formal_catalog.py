from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import LabCreate, LabDefinitionSpec


CONTENT_VERSION = "1.0.0"
COURSE_ID = "course_data_security"
CONTENT_PATH = Path(__file__).with_name("content") / "lab-definitions-v1.json"
PACK_PATH = Path(__file__).resolve().parents[1] / "resources" / "content" / "lab-packs-v1.json"
RSA_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "rsa-v1.json"

IMAGE_PROFILES = {
    "ubuntu": (
        "img_python_openssl_gate",
        "sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca",
        "Python 3.11 / OpenSSL 教学终端",
    ),
    "python": (
        "img_python_openssl_gate",
        "sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca",
        "Python 3 数据处理终端",
    ),
    "mysql": (
        "img_mysql_84",
        "sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb",
        "MySQL 8.4 教学数据库",
    ),
    "web": (
        "img_nginx_127",
        "sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10",
        "Nginx 1.27 教学服务",
    ),
}


def load_formal_catalog() -> dict[str, Any]:
    catalog = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    if catalog.get("version") != CONTENT_VERSION or catalog.get("course_id") != COURSE_ID:
        raise ValueError("正式实验定义目录版本或课程标识不正确")
    definitions = catalog.get("definitions", [])
    if len(definitions) != 12:
        raise ValueError("正式实验定义目录必须包含 12 个实验")
    unique_fields = ("lesson_id", "lesson_code", "lab_definition_id", "code")
    for field in unique_fields:
        values = [item.get(field) for item in definitions]
        if not all(values) or len(values) != len(set(values)):
            raise ValueError(f"正式实验定义目录字段 {field} 缺失或重复")
    expected_codes = [f"实验{number:02d}" for number in range(1, 13)]
    if [item["lesson_code"] for item in definitions] != expected_codes:
        raise ValueError("正式实验定义目录必须按实验01至实验12连续排列")
    return catalog


def formal_definition_records() -> list[dict[str, Any]]:
    catalog = load_formal_catalog()
    packs = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    if packs.get("version") != CONTENT_VERSION or packs.get("courseId") != COURSE_ID:
        raise ValueError("B 线正式实验文件包目录版本或课程标识不正确")
    packs_by_lesson = {item["lessonId"]: item for item in packs.get("packs", [])}
    if len(packs_by_lesson) != 12:
        raise ValueError("B 线正式实验文件包目录必须包含 12 个实验")

    records: list[dict[str, Any]] = []
    for entry in catalog["definitions"]:
        pack = packs_by_lesson.get(entry["lesson_id"])
        if not pack or pack.get("lessonCode") != entry["lesson_code"]:
            raise ValueError(f"C/B 实验课时映射不一致：{entry['lesson_code']}")
        if entry["profile"] == "rsa-deep":
            spec = LabDefinitionSpec.model_validate_json(RSA_FIXTURE_PATH.read_text(encoding="utf-8"))
            if spec.lab_definition_id != entry["lab_definition_id"]:
                raise ValueError("RSA 深度定义与正式目录标识不一致")
        else:
            spec = LabDefinitionSpec.model_validate(_build_spec(entry, pack))
        records.append(
            {
                "lesson_id": entry["lesson_id"],
                "lesson_code": entry["lesson_code"],
                "family": entry["family"],
                "create": LabCreate(
                    course_id=COURSE_ID,
                    code=entry["code"],
                    category=entry["category"],
                    objective=pack["objective"],
                    spec=spec,
                ),
            }
        )
    return records


def _build_spec(entry: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    number = entry["lesson_code"][-2:]
    slug = f"lab{number}"
    network_key = f"lab-net-{slug}"
    student_kind, target_kind = {
        "dual-linux": ("ubuntu", "ubuntu"),
        "data-processing": ("python", "python"),
        "mysql": ("python", "mysql"),
        "web-service": ("python", "web"),
    }[entry["profile"]]
    student = _node(f"student-{slug}", "学生操作机", "STUDENT_WORKSTATION", network_key, student_kind, [22], 90)
    target_ports = [3306] if target_kind == "mysql" else [8080] if target_kind == "web" else [22]
    target = _node(f"target-{slug}", "目标验证节点", "TARGET", network_key, target_kind, target_ports, 390)
    nodes = [student, target]
    steps = [
        {"node_key": "start", "name": "启动实验环境", "description": "由 D 线运行底座创建隔离环境", "order_no": 1},
        *[
            {"node_key": f"task_{index}", "name": text, "description": text, "order_no": index + 1}
            for index, text in enumerate(pack["steps"], start=1)
        ],
        {"node_key": "report", "name": "提交实验报告", "description": "提交实验结果与复盘报告", "order_no": 6},
    ]
    if len(steps) != 6:
        raise ValueError(f"{entry['lesson_code']} 正式实验必须包含 4 个业务步骤")
    edges = [
        {"from_node_key": steps[index]["node_key"], "to_node_key": steps[index + 1]["node_key"]}
        for index in range(len(steps) - 1)
    ]
    expected = pack.get("expected", [])
    if len(expected) < 2:
        raise ValueError(f"{entry['lesson_code']} 正式实验至少需要两个可复核产物")
    special = entry.get("special_judge") or {
        "judge_type": "FILE_EXISTS",
        "judge_target": f"student-{slug}:{expected[min(2, len(expected) - 1)]}",
        "judge_config_json": {"path": expected[min(2, len(expected) - 1)], "minimum_size": 1},
    }
    checkpoints = [
        _checkpoint(slug, 1, "task_1", "首个实验产物存在", 20, "FILE_EXISTS", f"student-{slug}:{expected[0]}", {"path": expected[0], "minimum_size": 1}),
        _checkpoint(slug, 2, "task_2", "第二个实验产物存在", 20, "FILE_EXISTS", f"student-{slug}:{expected[1]}", {"path": expected[1], "minimum_size": 1}),
        _checkpoint(slug, 3, "task_3", "关键结果符合实验要求", 20, special["judge_type"], special["judge_target"], special["judge_config_json"]),
        _checkpoint(slug, 4, "task_4", "受限验证命令执行成功", 30, "COMMAND_EXIT", f"student-{slug}:verify_{slug}", {"command_ref": f"verify_{slug}", "expected_exit": 0}),
        _checkpoint(slug, 5, "report", "实验报告已提交", 10, "FILE_EXISTS", "submission:report.pdf", {"path": "report.pdf", "minimum_size": 1}),
    ]
    return {
        "lab_definition_id": entry["lab_definition_id"],
        "version": 1,
        "name": pack["title"],
        "duration_minutes": entry["duration_minutes"],
        "total_score": 100,
        "nodes": nodes,
        "networks": [{"network_key": network_key, "cidr_policy": "AUTO_PRIVATE_24", "internet_access": False, "egress_allowlist": [], "student_isolation": True}],
        "image_bindings": [{"node_key": node["node_key"], "infra_image_id": node["image_id"], "digest": node["image_digest"]} for node in nodes],
        "steps": steps,
        "edges": edges,
        "checkpoints": checkpoints,
        "runtime_policy": {"max_attempts": 3, "timeout_minutes": entry["duration_minutes"]},
    }


def _node(key: str, name: str, role: str, network_key: str, image_kind: str, ports: list[int], x: int) -> dict[str, Any]:
    image_id, digest, device_model = IMAGE_PROFILES[image_kind]
    return {
        "node_key": key,
        "display_name": name,
        "role": role,
        "network_env": "ISOLATED",
        "network_keys": [network_key],
        "device_model": device_model,
        "image_id": image_id,
        "image_digest": digest,
        "cpu_limit": 1,
        "memory_mb": 1024,
        "ip_policy": "DYNAMIC_PRIVATE",
        "ports": ports,
        "startup_command": "",
        "mounts": [],
        "position_x": x,
        "position_y": 130,
    }


def _checkpoint(slug: str, number: int, dag_node_id: str, name: str, score: int, judge_type: str, judge_target: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkpoint_id": f"cp_{slug}_{number}",
        "dag_node_id": dag_node_id,
        "name": name,
        "score": score,
        "judge_type": judge_type,
        "judge_target": judge_target,
        "judge_config_json": config,
        "failure_message": f"{name}未通过，请核对实验步骤和产物后重试。",
        "timeout_seconds": 30,
        "order_no": number,
    }
