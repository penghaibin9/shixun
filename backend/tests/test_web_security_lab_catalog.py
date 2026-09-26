from app.labs.service import publishability_errors
from app.labs.web_security_catalog import COURSE_ID, STUDENT_IMAGE, WEB_TARGET_IMAGE, web_security_definition_records


def test_four_original_web_security_labs_are_publishable_specs():
    records = web_security_definition_records()
    assert len(records) == 4
    assert [item["lesson_code"] for item in records] == ["实验01", "实验08", "实验09", "实验10"]
    assert [item["create"].spec.lab_definition_id for item in records] == ["lab_web_01", "lab_web_08", "lab_web_09", "lab_web_10"]
    assert all(item["create"].course_id == COURSE_ID for item in records)
    assert all(item["create"].spec.external_requirements == [] for item in records)
    assert all(publishability_errors(item["create"].spec) == [] for item in records)


def test_web_security_labs_keep_fixed_images_and_one_canonical_challenge_checkpoint():
    records = web_security_definition_records()
    allowed = {STUDENT_IMAGE[1], WEB_TARGET_IMAGE[1]}
    for item in records:
        spec = item["create"].spec
        assert {binding.digest for binding in spec.image_bindings} == allowed
        assert sum(checkpoint.score for checkpoint in spec.checkpoints) == 100
        assert item["solution_checkpoint"] in {checkpoint.checkpoint_id for checkpoint in spec.checkpoints}
        solution = next(checkpoint for checkpoint in spec.checkpoints if checkpoint.checkpoint_id == item["solution_checkpoint"])
        assert solution.judge_type.value == "COMMAND_EXIT"
        assert solution.judge_config_json["command_ref"] == f"verify_web{item['number']:02d}"


def test_web09_requires_real_security_headers_from_isolated_target():
    record = next(item for item in web_security_definition_records() if item["number"] == 9)
    service = next(checkpoint for checkpoint in record["create"].spec.checkpoints if checkpoint.checkpoint_id == "cp_web09_service")
    required = service.judge_config_json["required_headers"]
    assert required["Content-Security-Policy"] == "default-src 'self'"
    assert required["X-Content-Type-Options"] == "nosniff"
    assert required["Set-Cookie"] == "HttpOnly"
