from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.runtime.schemas import ImageRegister, RuntimeStart

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from node_agent import app as node_agent_module
from node_agent.app import approved_command, command_evidence_container, container_name, remove_labeled_container, remove_owned_container, safe_file


def test_runtime_start_requires_student_subject():
    with pytest.raises(ValidationError):
        RuntimeStart(lab_release_id="release", lab_version_id="version", mode="STUDENT")


def test_image_requires_fixed_sha256_digest():
    with pytest.raises(ValidationError):
        ImageRegister(image_id="image", name="test", tag="latest", digest="latest", size_bytes=1, scan_status="PASSED", startup_check_status="PASSED", teaching_validation_status="PASSED", enabled=True)


def test_node_agent_accepts_safe_nested_artifacts_but_rejects_traversal():
    assert safe_file("work/restored/records.json") == "work/restored/records.json"
    with pytest.raises(HTTPException):
        safe_file("../host-secret")
    with pytest.raises(HTTPException):
        safe_file("work/../../host-secret")


def test_node_agent_uses_only_approved_command_references():
    assert approved_command("verify_signature")[0] == "openssl"
    assert approved_command("verify_lab12")[:2] == ["/bin/sh", "-c"]
    with pytest.raises(HTTPException):
        approved_command("teacher_supplied_shell")


def test_node_agent_runtime_has_no_rsa_container_hardcode():
    source = (Path(__file__).resolve().parents[2] / "node_agent/app.py").read_text(encoding="utf-8")
    assert 'container_name(group_id, "student-rsa")' not in source


def test_approved_command_uses_declared_student_evidence_role(monkeypatch):
    monkeypatch.setattr(node_agent_module, "group_container_for_role", lambda group_id, role: f"{group_id}:{role}")
    assert command_evidence_container("group_a", "verify_signature") == "group_a:STUDENT_WORKSTATION"
    with pytest.raises(HTTPException):
        command_evidence_container("group_a", "unapproved")


def test_grader_cleanup_never_removes_another_evaluation(monkeypatch):
    calls = []

    def fake_docker(*args, **kwargs):
        calls.append(args)
        return node_agent_module.subprocess.CompletedProcess(args, 0, stdout=f"{'a' * 64}|another-evaluation\n", stderr="")

    monkeypatch.setattr(node_agent_module, "docker", fake_docker)
    assert remove_owned_container("grader", "this-evaluation") is False
    assert [call[0] for call in calls] == ["inspect"]


def test_grader_cleanup_removes_the_immutable_owned_container_id(monkeypatch):
    container_id = "b" * 64
    calls = []

    def fake_docker(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return node_agent_module.subprocess.CompletedProcess(args, 0, stdout=f"{container_id}|this-evaluation\n", stderr="")
        if args[:2] == ("rm", "-f"):
            return node_agent_module.subprocess.CompletedProcess(args, 0, stdout=container_id, stderr="")
        return node_agent_module.subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")

    monkeypatch.setattr(node_agent_module, "docker", fake_docker)
    assert remove_owned_container("grader-name", "this-evaluation") is True
    assert calls[1] == ("rm", "-f", container_id)
    assert calls[2] == ("inspect", container_id)


def test_docker_names_include_full_identifier_hash():
    common_prefix = "group_" + "a" * 40
    assert container_name(common_prefix + "x", "student-node") != container_name(common_prefix + "y", "student-node")
    assert container_name("group_a", "node_" + "a" * 40 + "x") != container_name("group_a", "node_" + "a" * 40 + "y")


def test_failed_group_cleanup_never_removes_a_name_owned_by_another_group(monkeypatch):
    calls = []

    def fake_docker(*args, **kwargs):
        calls.append(args)
        return node_agent_module.subprocess.CompletedProcess(args, 0, stdout="another-group\n", stderr="")

    monkeypatch.setattr(node_agent_module, "docker", fake_docker)
    remove_labeled_container("this-group", "colliding-name")
    assert [call[0] for call in calls] == ["inspect"]
