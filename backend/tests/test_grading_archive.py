from hashlib import sha256

import pytest

from app.common.errors import ApiError
from app.grading.service import validate_freeze_contract


def test_freeze_contract_accepts_identified_roster_and_resource_manifest():
    roster = {
        "course_id": "course_1",
        "class_id": "class_1",
        "member_count": 43,
        "snapshot_hash": sha256(b"frozen-roster").hexdigest(),
        "frozen_at": "2026-09-21T10:00:00Z",
    }
    resource = {"course_id": "course_1", "manifest_id": "manifest_1", "version_no": 3}

    assert validate_freeze_contract("course.roster.frozen", "class_1", roster) == roster
    assert validate_freeze_contract("resource.delivery.frozen", "course_1", resource) == resource


@pytest.mark.parametrize(
    ("event_type", "aggregate_id", "payload", "code"),
    [
        ("course.roster.frozen", "class_1", {"course_id": "course_1", "class_id": "class_1"}, "GRADING.UPSTREAM_FREEZE_PAYLOAD_INVALID"),
        ("course.roster.frozen", "class_1", {"course_id": "course_1", "class_id": "class_1", "member_count": 0, "snapshot_hash": "0" * 64, "frozen_at": "2026-09-21T10:00:00Z"}, "GRADING.ROSTER_SNAPSHOT_INVALID"),
        ("course.roster.frozen", "class_other", {"course_id": "course_1", "class_id": "class_1", "member_count": 43, "snapshot_hash": "0" * 64, "frozen_at": "2026-09-21T10:00:00Z"}, "GRADING.ROSTER_SNAPSHOT_INVALID"),
        ("resource.delivery.frozen", "course_1", {"course_id": "course_1", "manifest_id": "", "version_no": 1}, "GRADING.UPSTREAM_FREEZE_PAYLOAD_INVALID"),
        ("resource.delivery.frozen", "course_1", {"course_id": "course_1", "manifest_id": "manifest_1", "version_no": 0}, "GRADING.RESOURCE_MANIFEST_INVALID"),
        ("resource.delivery.frozen", "course_other", {"course_id": "course_1", "manifest_id": "manifest_1", "version_no": 1}, "GRADING.RESOURCE_MANIFEST_INVALID"),
    ],
)
def test_freeze_contract_rejects_empty_or_inconsistent_shells(event_type, aggregate_id, payload, code):
    with pytest.raises(ApiError) as error:
        validate_freeze_contract(event_type, aggregate_id, payload)

    assert error.value.code == code
