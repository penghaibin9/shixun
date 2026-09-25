from app.labs.service import publishability_errors
from app.labs.web_security_catalog import COURSE_ID, STUDENT_IMAGE, WEB_TARGET_IMAGE, web_security_definition_records


def test_first_six_web_security_labs_are_publishable_original_specs():
    records = web_security_definition_records()
    assert len(records) == 6
    assert [item["lesson_code"] for item in records] == [f"实验{number:02d}" for number in range(1, 7)]
    assert [item["create"].spec.lab_definition_id for item in records] == [f"lab_web_{number:02d}" for number in range(1, 7)]
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
