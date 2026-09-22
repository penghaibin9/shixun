import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.labs.schemas import LabDefinitionSpec
from app.labs.formal_catalog import formal_definition_records
from app.labs.service import publishability_errors
from app.main import app

FIXTURE = Path(__file__).resolve().parents[1] / "app/labs/fixtures/rsa-v1.json"
SCHEMA = Path(__file__).resolve().parents[2] / "docs/contracts/lab-definition-v1.schema.json"
CURRICULUM_MAP = Path(__file__).resolve().parents[2] / "docs/contracts/lab-curriculum-map-v1.json"
MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20260922_0015_lab_curriculum_links.py"


def rsa_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rsa_schema_has_complete_g3_definition():
    spec = LabDefinitionSpec.model_validate(rsa_data())
    assert [node.node_key for node in spec.nodes] == ["student-rsa", "target-rsa"]
    assert len(spec.steps) == 6
    assert len(spec.checkpoints) == 5
    assert sum(item.score for item in spec.checkpoints) == 100
    assert all(binding.digest.startswith("sha256:") and len(binding.digest) == 71 for binding in spec.image_bindings)
    assert publishability_errors(spec) == []


def test_formal_catalog_has_twelve_distinct_publishable_definitions_and_frozen_links():
    records = formal_definition_records()
    mapping = json.loads(CURRICULUM_MAP.read_text(encoding="utf-8"))["mapping"]
    assert len(records) == len(mapping) == 12
    assert [record["lesson_code"] for record in records] == [f"实验{number:02d}" for number in range(1, 13)]
    assert [record["create"].spec.lab_definition_id for record in records] == [item["lab_definition_id"] for item in mapping]
    assert len({record["create"].spec.lab_definition_id for record in records}) == 12
    assert all(record["create"].spec.total_score == 100 for record in records)
    assert all(publishability_errors(record["create"].spec) == [] for record in records)
    assert {checkpoint.judge_type.value for record in records for checkpoint in record["create"].spec.checkpoints} == {
        "FILE_HASH", "COMMAND_EXIT", "FILE_EXISTS", "PORT_LISTEN", "HTTP_RESPONSE"
    }
    assert all(
        len({binding.digest for binding in record["create"].spec.image_bindings}) >= 1
        and all(len(set(binding.digest.removeprefix("sha256:"))) > 8 for binding in record["create"].spec.image_bindings)
        for record in records
    )


def test_checked_in_json_schema_exposes_frozen_fields_and_judge_types():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) == {"lab_definition_id", "version", "name", "duration_minutes", "total_score", "nodes", "networks", "image_bindings", "steps", "edges", "checkpoints", "runtime_policy"}
    assert set(schema["$defs"]["checkpoint"]["properties"]["judge_type"]["enum"]) == {"FILE_HASH", "COMMAND_EXIT", "FILE_EXISTS", "PORT_LISTEN", "HTTP_RESPONSE"}


def test_definition_schema_rejects_unknown_top_level_and_nested_fields():
    top_level = rsa_data()
    top_level["unknown_field"] = True
    with pytest.raises(ValidationError):
        LabDefinitionSpec.model_validate(top_level)

    nested = rsa_data()
    nested["runtime_policy"]["unknown_field"] = True
    with pytest.raises(ValidationError):
        LabDefinitionSpec.model_validate(nested)


def test_curriculum_freeze_migration_rejects_legacy_release_scope_gaps():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "WHERE lr.course_id <> ld.course_id" in source
    assert "WHERE lr.lesson_id IS NULL" in source
    assert "lesson.linked_lab_definition_id = ld.lab_definition_id" in source
    assert "WHERE lesson.lesson_resource_id IS NULL" in source
    assert '"lesson_id",\n        existing_type=sa.String(length=36),\n        nullable=False' in source


def test_openapi_exposes_all_lab_designer_routes():
    paths = app.openapi()["paths"]
    assert "/api/v1/labs" in paths
    assert "/api/v1/labs/import" in paths
    assert "/api/v1/lab-versions/{version_id}/validate" in paths
    assert "/api/v1/lab-versions/{version_id}/export.json" in paths
    assert "/api/v1/lab-releases/{release_id}/teacher-preview" in paths


def test_schema_rejects_edge_node_network_and_image_reference_errors():
    broken = rsa_data()
    broken["edges"][0]["to_node_key"] = "missing"
    with pytest.raises(ValidationError, match="DAG 边引用"):
        LabDefinitionSpec.model_validate(broken)

    broken = rsa_data()
    broken["nodes"][0]["network_keys"] = ["missing-net"]
    with pytest.raises(ValidationError, match="不存在的网络"):
        LabDefinitionSpec.model_validate(broken)

    broken = rsa_data()
    broken["image_bindings"][0]["digest"] = "latest"
    with pytest.raises(ValidationError):
        LabDefinitionSpec.model_validate(broken)


def test_publishability_blocks_cycle_and_score_mismatch():
    data = rsa_data()
    data["edges"].append({"from_node_key": "report", "to_node_key": "start"})
    spec = LabDefinitionSpec.model_validate(data)
    assert "DAG_CYCLE" in {error["code"] for error in publishability_errors(spec)}

    data = rsa_data()
    data["checkpoints"][0]["score"] = 19
    spec = LabDefinitionSpec.model_validate(data)
    assert "CHECKPOINT_SCORE_MISMATCH" in {error["code"] for error in publishability_errors(spec)}


@pytest.mark.parametrize(
    ("judge_type", "config"),
    [
        ("FILE_EXISTS", {"path": "a.txt"}),
        ("FILE_HASH", {"left_path": "a", "right_path": "b", "algorithm": "sha256"}),
        ("COMMAND_EXIT", {"command_ref": "verify_signature", "expected_exit": 0}),
        ("PORT_LISTEN", {"host": "127.0.0.1", "port": 8080}),
        ("HTTP_RESPONSE", {"path": "/health", "status_code": 200}),
    ],
)
def test_all_five_judge_contracts_are_supported(judge_type: str, config: dict):
    data = rsa_data()
    checkpoint = copy.deepcopy(data["checkpoints"][0])
    checkpoint["judge_type"] = judge_type
    checkpoint["judge_config_json"] = config
    data["checkpoints"][0] = checkpoint
    assert LabDefinitionSpec.model_validate(data).checkpoints[0].judge_type.value == judge_type


def test_control_plane_rejects_raw_judge_script():
    data = rsa_data()
    data["checkpoints"][0]["judge_config_json"] = {"path": "x", "script": "rm -rf /"}
    with pytest.raises(ValidationError, match="可执行脚本"):
        LabDefinitionSpec.model_validate(data)
