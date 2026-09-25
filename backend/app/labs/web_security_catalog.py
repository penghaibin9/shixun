from __future__ import annotations

from typing import Any

from .schemas import LabCreate, LabDefinitionSpec
from .service import publishability_errors


COURSE_ID = "course_web_security"
STUDENT_IMAGE = (
    "img_python_openssl_gate",
    "sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca",
)
WEB_TARGET_IMAGE = (
    "img_nginx_127",
    "sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10",
)

LABS: tuple[dict[str, Any], ...] = (
    {
        "number": 1,
        "title": "HTTP 请求观察与安全基线",
        "category": "Web 基础",
        "duration": 50,
        "solution_path": "work/http-baseline.json",
        "evidence_path": "work/security-review.md",
        "verify_ref": "verify_web01",
        "solution_checkpoint": "cp_web01_solution",
        "tasks": [
            "使用 Python 从学生操作机请求 target-web01:8080/health，记录状态码、响应头与正文。",
            "把真实请求结果写入 work/http-baseline.json。",
            "在 work/security-review.md 记录 Cookie、响应头和最小安全基线观察。",
            "运行固定判题合同并修正证据格式。",
        ],
    },
    {
        "number": 2,
        "title": "认证与对象授权验证",
        "category": "身份与访问控制",
        "duration": 60,
        "solution_path": "work/auth_policy.py",
        "evidence_path": "work/auth-matrix.md",
        "verify_ref": "verify_web02",
        "solution_checkpoint": "cp_web02_solution",
        "tasks": [
            "实现 authorize(actor_id, owner_id, role) 权限函数。",
            "覆盖本人访问、跨用户拒绝和教师授权三条路径。",
            "把正向/负向验证矩阵写入 work/auth-matrix.md。",
            "通过固定判题器验证对象级授权边界。",
        ],
    },
    {
        "number": 3,
        "title": "SQL 注入原理与参数化修复",
        "category": "注入安全",
        "duration": 70,
        "solution_path": "work/sql_lab.py",
        "evidence_path": "work/sql-review.md",
        "verify_ref": "verify_web03",
        "solution_checkpoint": "cp_web03_solution",
        "tasks": [
            "使用 Python sqlite3 实现 unsafe_search 与 safe_search。",
            "先观察字符串拼接查询在教学数据上的注入现象。",
            "把 safe_search 改为参数化查询并记录修复差异。",
            "由隔离判题器创建一次性数据库验证修复前后结果。",
        ],
    },
    {
        "number": 4,
        "title": "XSS 输入输出边界",
        "category": "浏览器安全",
        "duration": 60,
        "solution_path": "work/xss_lab.py",
        "evidence_path": "work/xss-review.md",
        "verify_ref": "verify_web04",
        "solution_checkpoint": "cp_web04_solution",
        "tasks": [
            "实现 render_unsafe 与 render_safe 两个输出函数。",
            "比较原样输出与上下文编码后的 HTML。",
            "记录输入校验、输出编码和 CSP 的职责边界。",
            "通过固定测试载荷验证危险标签不会出现在安全输出中。",
        ],
    },
    {
        "number": 5,
        "title": "文件上传与路径穿越防护",
        "category": "文件安全",
        "duration": 65,
        "solution_path": "work/file_policy.py",
        "evidence_path": "work/file-review.md",
        "verify_ref": "verify_web05",
        "solution_checkpoint": "cp_web05_solution",
        "tasks": [
            "实现 normalize_upload_name，拒绝绝对路径和目录穿越。",
            "实现 allow_upload，对扩展名、MIME 和大小做联合约束。",
            "记录允许与拒绝样例及存储隔离原则。",
            "由固定判题器执行正常文件、危险扩展名和穿越路径负向测试。",
        ],
    },
    {
        "number": 6,
        "title": "SSRF 出口控制",
        "category": "服务端请求安全",
        "duration": 65,
        "solution_path": "work/ssrf_policy.py",
        "evidence_path": "work/ssrf-review.md",
        "verify_ref": "verify_web06",
        "solution_checkpoint": "cp_web06_solution",
        "tasks": [
            "实现 allow_url，对协议、主机和地址范围做显式允许判断。",
            "允许课程指定 HTTPS 域名，拒绝 localhost、私网和链路本地地址。",
            "记录 DNS 重绑定、重定向复核和出口代理的生产防护要点。",
            "通过固定判题器执行允许/拒绝 URL 矩阵。",
        ],
    },
)


def web_security_definition_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in LABS:
        spec = LabDefinitionSpec.model_validate(_build_spec(item))
        errors = publishability_errors(spec)
        if errors:
            raise ValueError(f"Web 实验{item['number']:02d}未通过发布门禁：{errors}")
        records.append(
            {
                "number": item["number"],
                "lesson_code": f"实验{item['number']:02d}",
                "challenge_id": f"challenge_web_{item['number']:02d}",
                "solution_checkpoint": item["solution_checkpoint"],
                "create": LabCreate(
                    course_id=COURSE_ID,
                    code=f"EXP-WEB-{item['number']:02d}",
                    category=item["category"],
                    objective=f"在授权隔离环境中完成{item['title']}，形成可复核的允许路径、拒绝路径和修复证据。",
                    spec=spec,
                ),
            }
        )
    return records


def _build_spec(item: dict[str, Any]) -> dict[str, Any]:
    number = item["number"]
    slug = f"web{number:02d}"
    student_key = f"student-{slug}"
    target_key = f"target-{slug}"
    network_key = f"lab-net-{slug}"
    steps = [
        {"node_key": "start", "name": "启动隔离环境", "description": "由 Node Agent 创建固定摘要镜像和无外网私有网络。", "order_no": 1},
        {"node_key": "observe", "name": "理解任务与边界", "description": item["tasks"][0], "order_no": 2},
        {"node_key": "implement", "name": "完成核心实现", "description": item["tasks"][1], "order_no": 3},
        {"node_key": "test", "name": "完成正负向验证", "description": item["tasks"][2], "order_no": 4},
        {"node_key": "evidence", "name": "通过固定判题合同", "description": item["tasks"][3], "order_no": 5},
        {"node_key": "report", "name": "提交实验复盘", "description": "把关键证据、修复思路和回归结果写入 work/report.md。", "order_no": 6},
    ]
    edges = [
        {"from_node_key": steps[index]["node_key"], "to_node_key": steps[index + 1]["node_key"]}
        for index in range(len(steps) - 1)
    ]
    return {
        "lab_definition_id": f"lab_web_{number:02d}",
        "version": 1,
        "name": item["title"],
        "duration_minutes": item["duration"],
        "total_score": 100,
        "nodes": [
            {
                "node_key": student_key,
                "display_name": "学生安全编码工作站",
                "role": "STUDENT_WORKSTATION",
                "network_env": "ISOLATED",
                "network_keys": [network_key],
                "device_model": "Python 3.11 / OpenSSL 教学终端",
                "image_id": STUDENT_IMAGE[0],
                "image_digest": STUDENT_IMAGE[1],
                "cpu_limit": 1,
                "memory_mb": 1024,
                "ip_policy": "DYNAMIC_PRIVATE",
                "ports": [22],
                "startup_command": "",
                "mounts": [],
                "position_x": 100,
                "position_y": 130,
            },
            {
                "node_key": target_key,
                "display_name": "隔离 Web 目标服务",
                "role": "TARGET",
                "network_env": "ISOLATED",
                "network_keys": [network_key],
                "device_model": "Nginx 1.27 教学服务",
                "image_id": WEB_TARGET_IMAGE[0],
                "image_digest": WEB_TARGET_IMAGE[1],
                "cpu_limit": 1,
                "memory_mb": 256,
                "ip_policy": "DYNAMIC_PRIVATE",
                "ports": [8080],
                "startup_command": "",
                "mounts": [],
                "position_x": 400,
                "position_y": 130,
            },
        ],
        "networks": [
            {
                "network_key": network_key,
                "cidr_policy": "AUTO_PRIVATE_24",
                "internet_access": False,
                "egress_allowlist": [],
                "student_isolation": True,
            }
        ],
        "image_bindings": [
            {"node_key": student_key, "infra_image_id": STUDENT_IMAGE[0], "digest": STUDENT_IMAGE[1]},
            {"node_key": target_key, "infra_image_id": WEB_TARGET_IMAGE[0], "digest": WEB_TARGET_IMAGE[1]},
        ],
        "steps": steps,
        "edges": edges,
        "checkpoints": [
            {
                "checkpoint_id": f"cp_web{number:02d}_service",
                "dag_node_id": "observe",
                "name": "隔离 Web 目标服务可达",
                "score": 10,
                "judge_type": "HTTP_RESPONSE",
                "judge_target": f"{target_key}:/health",
                "judge_config_json": {"path": "/health", "port": 8080, "status_code": 200},
                "failure_message": "Web 目标服务未通过隔离网络健康检查。",
                "timeout_seconds": 15,
                "order_no": 1,
            },
            {
                "checkpoint_id": f"cp_web{number:02d}_source",
                "dag_node_id": "implement",
                "name": "核心实现已形成",
                "score": 20,
                "judge_type": "FILE_EXISTS",
                "judge_target": f"{student_key}:{item['solution_path']}",
                "judge_config_json": {"path": item["solution_path"], "minimum_size": 16},
                "failure_message": "核心实现文件不存在或内容为空。",
                "timeout_seconds": 15,
                "order_no": 2,
            },
            {
                "checkpoint_id": f"cp_web{number:02d}_review",
                "dag_node_id": "test",
                "name": "安全复核证据已形成",
                "score": 15,
                "judge_type": "FILE_EXISTS",
                "judge_target": f"{student_key}:{item['evidence_path']}",
                "judge_config_json": {"path": item["evidence_path"], "minimum_size": 32},
                "failure_message": "请补充允许路径、拒绝路径和修复差异的复核记录。",
                "timeout_seconds": 15,
                "order_no": 3,
            },
            {
                "checkpoint_id": item["solution_checkpoint"],
                "dag_node_id": "evidence",
                "name": "固定安全测试合同通过",
                "score": 45,
                "judge_type": "COMMAND_EXIT",
                "judge_target": f"{student_key}:{item['verify_ref']}",
                "judge_config_json": {"command_ref": item["verify_ref"], "expected_exit": 0},
                "failure_message": "固定安全测试未通过，请根据失败用例修正实现。",
                "timeout_seconds": 30,
                "order_no": 4,
            },
            {
                "checkpoint_id": f"cp_web{number:02d}_report",
                "dag_node_id": "report",
                "name": "实验复盘已提交",
                "score": 10,
                "judge_type": "FILE_EXISTS",
                "judge_target": f"{student_key}:work/report.md",
                "judge_config_json": {"path": "work/report.md", "minimum_size": 64},
                "failure_message": "请提交包含证据与修复结论的 work/report.md。",
                "timeout_seconds": 15,
                "order_no": 5,
            },
        ],
        "runtime_policy": {"max_attempts": 3, "timeout_minutes": item["duration"]},
        "external_requirements": [],
    }
