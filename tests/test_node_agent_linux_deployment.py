"""独立 Linux Node Agent（节点代理）部署资料的静态安全门禁。"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ROOT = ROOT / "deploy" / "node-agent" / "linux"


def read(name: str) -> str:
    return (DEPLOY_ROOT / name).read_text(encoding="utf-8")


def test_systemd_unit_is_loopback_by_default_and_hardened() -> None:
    unit = read("yueke-node-agent.service")
    exact_required = {
        "User=yueke-agent",
        "Group=yueke-agent",
        "SupplementaryGroups=docker",
        "EnvironmentFile=/etc/yueke-node-agent/node-agent.env",
        "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "UnsetEnvironment=DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "PrivateTmp=yes",
        "PrivateDevices=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "RestrictNamespaces=yes",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "MemoryDenyWriteExecute=yes",
        "StateDirectory=yueke-node-agent",
        "UMask=0077",
    }
    fragments = {
        "--host ${YUEKE_NODE_AGENT_BIND_HOST}",
        "--port ${YUEKE_NODE_AGENT_PORT}",
        "--workers 1",
        "--no-access-log",
        "ExecStartPre=/opt/yueke-node-agent/current/deploy/node-agent/linux/preflight.sh",
    }
    missing = exact_required - set(unit.splitlines())
    missing.update(fragment for fragment in fragments if fragment not in unit)
    assert not missing, f"systemd 单元缺少安全约束：{sorted(missing)}"
    assert "--host 0.0.0.0" not in unit
    assert "--privileged" not in unit
    assert "--network host" not in unit
    assert "--pid host" not in unit
    assert "--ipc host" not in unit
    assert ".sock:" not in unit


def test_environment_template_contains_only_placeholder_secret_and_required_controls() -> None:
    template = read("node-agent.env.example")
    required = {
        "YUEKE_NODE_AGENT_BIND_HOST=127.0.0.1",
        "YUEKE_NODE_AGENT_PORT=19443",
        "YUEKE_NODE_AGENT_TOKEN=REPLACE_WITH_A_32_CHARACTER_OR_LONGER_RANDOM_SECRET",
        "YUEKE_AGENT_ALLOWED_DIGESTS=REPLACE_WITH_APPROVED_SHA256_DIGESTS",
        "YUEKE_AGENT_GRADER_DIGEST=REPLACE_WITH_APPROVED_GRADER_SHA256_DIGEST",
        "YUEKE_AGENT_CAPTURE_DIGEST=REPLACE_WITH_APPROVED_CAPTURE_SHA256_DIGEST",
        "YUEKE_AGENT_CAPTURE_DIR=/var/lib/yueke-node-agent/captures",
        "YUEKE_AGENT_CAPTURE_MAX_BYTES=33554432",
    }
    assert required <= set(template.splitlines())
    assert "Bearer " not in template
    assert "DOCKER_HOST=" not in template


def test_preflight_rejects_remote_docker_public_bind_and_insecure_config() -> None:
    preflight = read("preflight.sh")
    for required in (
        "DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH",
        "docker context show",
        "docker context inspect",
        "unix:///var/run/docker.sock|unix:///run/docker.sock",
        "docker info --format '{{.OSType}}'",
        "bind_address.is_loopback or bind_address.is_private",
        "YUEKE_AGENT_CAPTURE_DIR 必须位于 /var/lib/yueke-node-agent/ 下",
        "配置文件必须由 root 持有",
        "节点代理代码与解释器权限检查通过",
        "/opt/yueke-node-agent/releases/ 的同一受控发行目录",
        "YUEKE_AGENT_GRADER_DIGEST",
        "YUEKE_AGENT_CAPTURE_DIGEST",
        "未创建 Docker 资源",
    ):
        assert required in preflight
    assert "source " not in preflight
    assert "eval " not in preflight
    assert "docker run" not in preflight
    assert "docker pull" not in preflight


def test_verification_uses_in_memory_authorization_and_refuses_remote_plaintext() -> None:
    verifier = read("verify-service.sh")
    for required in (
        "urllib.request",
        "NoRedirect",
        "Authorization\": f\"Bearer {token}",
        "远程验证必须使用 HTTPS",
        'request_json("/health")',
        'request_json("/capacity")',
    ):
        assert required in verifier
    assert "curl " not in verifier
    assert "print(token" not in verifier


def test_deployment_document_does_not_claim_linux_or_production_verification() -> None:
    document = read("README.md")
    for required in (
        "未运行：真实 Linux",
        "不使用 Docker Socket",
        "Docker Socket（容器运行接口）挂载",
        "回退",
        "24x80",
        "30x100",
    ):
        assert required in document
