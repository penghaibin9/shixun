from __future__ import annotations

import json

from app.contentpacks.adapters.vulhub import parse_environment_index
from app.contentpacks.catalog import course_pack_registry, load_bundled_course_pack, load_course_pack_by_catalog
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


def test_all_registered_original_chinese_course_packs_are_valid_and_complete():
    registry = course_pack_registry()
    assert len(registry) == 10
    assert len({item["catalog_key"] for item in registry}) == 10
    for item in registry:
        pack = load_course_pack_by_catalog(item["catalog_key"])
        assert pack.content_origin.value == "ORIGINAL"
        assert pack.commercial_bundle_allowed is True
        assert pack.language == "zh-CN"
        assert len(pack.lessons) == 24
        assert sum(lesson.lesson_type == "THEORY" for lesson in pack.lessons) == 12
        assert sum(lesson.lesson_type == "LAB" for lesson in pack.lessons) == 12
        assert all(lesson.title and lesson.summary and lesson.objectives for lesson in pack.lessons)


def test_web_lab_readiness_keeps_only_four_original_specs_ready():
    path = __import__("pathlib").Path(__file__).parents[1] / "app" / "contentpacks" / "content" / "web-security-lab-candidates-v1.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    ready = {item["lesson_code"] for item in registry["labs"] if item["runtime_status"] == "FORMAL_SPEC_READY"}
    assert ready == {"实验01", "实验08", "实验09", "实验10"}
    external = [item for item in registry["labs"] if item["lesson_code"] not in ready]
    assert len(external) == 8
    assert all(item["runtime_status"] in {"REVIEW_REQUIRED", "EXTERNAL_IMAGE_REQUIRED", "LICENSE_REVIEW_REQUIRED"} for item in external)
