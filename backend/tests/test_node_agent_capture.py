import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from node_agent import app as agent


def completed(result: int = 0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], result, stdout=stdout, stderr=stderr)


def one_packet_pcap() -> bytes:
    packet = b"\x00\x01\x02\x03"
    header = b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 1)
    record = struct.pack("<IIII", 1, 0, len(packet), len(packet)) + packet
    return header + record


def test_capture_endpoint_requires_control_plane_identity(monkeypatch):
    monkeypatch.setenv("YUEKE_NODE_AGENT_TOKEN", "capture-secret")
    client = TestClient(agent.app)
    for method, path in (
        (client.post, "/runtime-groups/group-safe/capture/start"),
        (client.get, "/runtime-groups/group-safe/capture/artifact"),
    ):
        response = method(path)
        assert response.status_code == 401
        assert response.json()["detail"] == "控制面身份校验失败"


def test_capture_rejects_path_traversal_before_docker(monkeypatch, tmp_path):
    monkeypatch.setenv("YUEKE_AGENT_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setattr(agent, "docker", lambda *args, **kwargs: pytest.fail("不应访问 Docker"))
    with pytest.raises(HTTPException) as captured:
        agent.capture_start("../outside")
    assert captured.value.status_code == 422


def test_capture_stop_rejects_unknown_runtime_group(monkeypatch, tmp_path):
    monkeypatch.setenv("YUEKE_AGENT_CAPTURE_DIR", str(tmp_path))

    def unknown(_group_id):
        raise HTTPException(404, "实例组缺少唯一的学生操作容器")

    monkeypatch.setattr(agent, "capture_target", unknown)
    with pytest.raises(HTTPException) as captured:
        agent.capture_stop("unknown-group")
    assert captured.value.status_code == 404


def test_capture_target_rejects_unmanaged_spoofed_group(monkeypatch):
    monkeypatch.setattr(agent, "group_container_for_role", lambda group_id, role: "spoofed-student")
    detail = [{
        "Id": "a" * 64,
        "Config": {"Labels": {
            "io.yueke.runtime-group": "spoofed-group",
            "io.yueke.role": "STUDENT_WORKSTATION",
            "io.yueke.node-key": "student",
            "io.yueke.expires-at": "2099-01-01T00:00:00+00:00",
        }},
        "State": {"Status": "running"},
    }]
    monkeypatch.setattr(agent, "docker", lambda *args, **kwargs: completed(stdout=json.dumps(detail)))
    with pytest.raises(HTTPException, match="未处于可采集状态"):
        agent.capture_target("spoofed-group")


def test_capture_start_stop_are_idempotent_and_persist_verified_summary(monkeypatch, tmp_path):
    group_id = "group-capture-test"
    target_id = "a" * 64
    capture_container_id = "b" * 64
    image_digest = "sha256:" + "c" * 64
    monkeypatch.setenv("YUEKE_AGENT_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("YUEKE_AGENT_CAPTURE_MAX_BYTES", str(1024 * 1024))
    monkeypatch.setattr(agent, "capture_target", lambda value: ("student", target_id, "2099-01-01T00:00:00+00:00"))
    monkeypatch.setattr(agent, "capture_image_digest", lambda: image_digest)
    calls = []
    state = {"capture_id": None, "removed": False}

    def fake_docker(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "-a", "--filter"):
            return completed(stdout="")
        if args[0] == "create":
            capture_label = next(value for value in args if value.startswith("io.yueke.capture-id="))
            state["capture_id"] = capture_label.split("=", 1)[1]
            return completed(stdout=capture_container_id + "\n")
        if args[0] == "start":
            return completed(stdout=capture_container_id + "\n")
        if args[:3] == ("inspect", "--format", "{{.State.Status}}"):
            return completed(stdout="running\n")
        if args[0] == "exec":
            return completed()
        if args[0] == "inspect" and "{{.State.Status}}|" in args[2]:
            return completed(stdout=f"running|{group_id}|{state['capture_id']}\n")
        if args[0] == "inspect" and "{{.Id}}|" in args[2]:
            if state["removed"]:
                return completed(1, stderr="No such object")
            return completed(stdout=f"{capture_container_id}|{group_id}|{state['capture_id']}\n")
        if args[:2] == ("rm", "-f"):
            state["removed"] = True
            return completed(stdout=capture_container_id + "\n")
        raise AssertionError(f"未预期的 Docker 调用: {args}")

    monkeypatch.setattr(agent, "docker", fake_docker)
    monkeypatch.setattr(
        agent,
        "docker_bytes",
        lambda *args, **kwargs: completed(stdout=one_packet_pcap()),
    )

    started = agent.capture_start(group_id)
    replayed_start = agent.capture_start(group_id)
    assert started["status"] == "CAPTURING"
    assert started["idempotent_replay"] is False
    assert replayed_start == {**started, "idempotent_replay": True}

    stopped = agent.capture_stop(group_id)
    replayed_stop = agent.capture_stop(group_id)
    replayed_completed_start = agent.capture_start(group_id)
    artifact = tmp_path / stopped["file_id"]
    assert stopped["status"] == "COMPLETED"
    assert stopped["packet_count"] == 1
    assert stopped["size_bytes"] == len(one_packet_pcap())
    assert stopped["sha256"] == agent.sha256(one_packet_pcap()).hexdigest()
    assert artifact.read_bytes() == one_packet_pcap()
    assert replayed_stop == {**stopped, "idempotent_replay": True}
    assert replayed_completed_start == {**stopped, "idempotent_replay": True}
    assert state["removed"] is True

    monkeypatch.setenv("YUEKE_NODE_AGENT_TOKEN", "capture-secret")
    download = TestClient(agent.app).get(
        f"/runtime-groups/{group_id}/capture/artifact",
        headers={"Authorization": "Bearer capture-secret"},
    )
    assert download.status_code == 200
    assert download.content == one_packet_pcap()
    assert download.headers["content-type"] == "application/vnd.tcpdump.pcap"
    assert download.headers["x-content-sha256"] == stopped["sha256"]

    artifact.write_bytes(one_packet_pcap() + b"tampered")
    tampered = TestClient(agent.app).get(
        f"/runtime-groups/{group_id}/capture/artifact",
        headers={"Authorization": "Bearer capture-secret"},
    )
    assert tampered.status_code == 503
    assert "完整性" in tampered.json()["detail"] or "不可用" in tampered.json()["detail"]

    create_call = next(call for call in calls if call[0] == "create")
    assert ("--network", f"container:{target_id}") == tuple(create_call[create_call.index("--network"):create_call.index("--network") + 2])
    assert ("--cap-add", "NET_RAW") == tuple(create_call[create_call.index("--cap-add"):create_call.index("--cap-add") + 2])
    assert "--privileged" not in create_call
    assert "--volume" not in create_call
    assert "--mount" not in create_call
    assert "/var/run/docker.sock" not in " ".join(create_call)


def test_header_only_pcap_is_explicit_failure():
    header_only = b"\xd4\xc3\xb2\xa1" + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 1)
    with pytest.raises(HTTPException, match="没有捕获"):
        agent.pcap_packet_count(header_only)


def test_completed_manifest_file_id_cannot_escape_capture_root(monkeypatch, tmp_path):
    monkeypatch.setenv("YUEKE_AGENT_CAPTURE_DIR", str(tmp_path))
    manifest = {
        "runtime_group_id": "group-safe",
        "capture_id": "cap_" + "d" * 32,
        "status": "COMPLETED",
        "started_at": "2026-09-22T00:00:00+00:00",
        "file_id": "../outside.pcap",
        "size_bytes": 1,
        "sha256": "0" * 64,
    }
    with pytest.raises(HTTPException, match="产物不可用"):
        agent.validate_completed_capture(manifest)
