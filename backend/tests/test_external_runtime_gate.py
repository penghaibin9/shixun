from app.contentpacks.security import scan_compose_manifest
from app.labs.schemas import LabDefinitionSpec
from app.labs.service import publishability_errors


def test_external_runtime_requirement_blocks_publishability():
    spec = LabDefinitionSpec.model_validate({
        "lab_definition_id": "lab_web_03",
        "version": 1,
        "name": "SQL 注入原理与参数化修复",
        "duration_minutes": 60,
        "total_score": 100,
        "nodes": [{
            "node_key": "student", "display_name": "学生操作机", "role": "STUDENT_WORKSTATION",
            "network_env": "ISOLATED", "network_keys": ["lab-net"], "device_model": "Python",
            "image_id": "img_student", "image_digest": "sha256:" + "1" * 64,
            "cpu_limit": 1, "memory_mb": 512, "ip_policy": "DYNAMIC_PRIVATE", "ports": [], "startup_command": "", "mounts": []
        }],
        "networks": [{"network_key": "lab-net", "cidr_policy": "AUTO_PRIVATE_24", "internet_access": False, "student_isolation": True}],
        "image_bindings": [{"node_key": "student", "infra_image_id": "img_student", "digest": "sha256:" + "1" * 64}],
        "steps": [{"node_key": "start", "name": "开始", "order_no": 1}],
        "edges": [],
        "checkpoints": [{
            "checkpoint_id": "cp_start", "dag_node_id": "start", "name": "完成验证", "score": 100,
            "judge_type": "FILE_EXISTS", "judge_target": "student:report.txt",
            "judge_config_json": {"path": "report.txt"}, "failure_message": "未完成", "timeout_seconds": 30, "order_no": 1
        }],
        "runtime_policy": {"max_attempts": 3, "timeout_minutes": 60},
        "external_requirements": [{
            "source_name": "Vulhub", "source_ref": "cmsms/CVE-2019-9053", "license_id": "MIT",
            "status": "REVIEW_REQUIRED", "reason": "镜像 digest 尚未冻结"
        }]
    })
    errors = publishability_errors(spec)
    assert any(item["code"] == "EXTERNAL_RUNTIME_NOT_READY" for item in errors)



def test_compose_scanner_blocks_host_and_build_escape_surfaces():
    compose = {
        "services": {
            "target": {
                "image": "example/target:latest",
                "network_mode": "service:gateway",
                "ports": ["8080:80"],
                "build": ".",
                "extra_hosts": ["host.docker.internal:host-gateway"],
                "uts": "host",
                "userns_mode": "host",
                "security_opt": ["seccomp=unconfined"],
            }
        }
    }
    codes = {finding.code for finding in scan_compose_manifest(compose)}
    assert {
        "COMPOSE.CUSTOM_NETWORK_MODE",
        "COMPOSE.HOST_PORT",
        "COMPOSE.BUILD",
        "COMPOSE.HOST_GATEWAY",
        "COMPOSE.HOST_UTS",
        "COMPOSE.HOST_USERNS",
        "COMPOSE.SECURITY_OPT",
    } <= codes


def test_compose_scanner_accepts_minimal_metadata_only_candidate():
    findings = scan_compose_manifest(
        {
            "services": {
                "target": {
                    "image": "example/target@sha256:" + "a" * 64,
                    "networks": ["lab-net"],
                    "volumes": ["named-data:/var/lib/app"],
                }
            },
            "networks": {"lab-net": {"internal": True}},
            "volumes": {"named-data": {}},
        }
    )
    assert findings == []
