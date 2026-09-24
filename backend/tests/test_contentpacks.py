from __future__ import annotations

import json

from app.contentpacks.adapters.vulhub import parse_environment_index
from app.contentpacks.catalog import load_bundled_course_pack
from app.contentpacks.license_policy import LicenseDecision, evaluate_license
from app.contentpacks.security import scan_compose_manifest


def test_noncommercial_content_is_blocked_from_commercial_bundle():
    result = evaluate_license("CC-BY-NC-SA-4.0")
    assert result.decision == LicenseDecision.BLOCK


def test_known_permissive_sources_are_allowed_with_notice():
    assert evaluate_license("MIT").decision == LicenseDecision.ALLOW
    assert evaluate_license("Apache-2.0").decision == LicenseDecision.ALLOW
    assert evaluate_license("BSD-2-Clause").decision == LicenseDecision.ALLOW


def test_compose_guard_blocks_host_and_docker_socket_escape_paths():
    findings = scan_compose_manifest(
        {
            "services": {
                "target": {
                    "privileged": True,
                    "network_mode": "host",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
                }
            }
        }
    )
    codes = {item.code for item in findings}
    assert {"COMPOSE.PRIVILEGED", "COMPOSE.HOST_NETWORK", "COMPOSE.DOCKER_SOCKET"} <= codes


def test_vulhub_index_is_metadata_only_candidate():
    raw = b"""
[[environment]]
name = "Demo SQL Injection"
cve = ["CVE-2099-0001"]
app = "Demo"
path = "demo/CVE-2099-0001"
dockerfile = {"vulhub/demo:1.0" = "base/demo/1.0"}
tags = ["SQL Injection"]
"""
    candidates = parse_environment_index(raw)
    assert len(candidates) == 1
    assert candidates[0].source == "Vulhub"
    assert candidates[0].import_status == "REVIEW_REQUIRED"
    assert candidates[0].images == ["vulhub/demo:1.0"]


def test_first_web_security_pack_is_original_chinese_content():
    pack = load_bundled_course_pack("web-security-v1.json")
    assert pack.course_id == "course_web_security"
    assert pack.content_origin.value == "ORIGINAL"
    assert pack.commercial_bundle_allowed is True
    assert len(pack.lessons) == 24
    assert sum(item.lesson_type == "THEORY" for item in pack.lessons) == 12
    assert sum(item.lesson_type == "LAB" for item in pack.lessons) == 12
    assert all(item.title for item in pack.lessons)
