from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.challenges.models import ChallengeDefinition
from app.common.context import UserContext
from app.common.outbox import enqueue_event

from .database import create_session_factory
from .models import LabDefinition, LabVersion
from .service import LabService
from .web_security_catalog import COURSE_ID, web_security_definition_records


SEED_USER_ID = "system_web_security_seed"


def seed_web_security_labs() -> dict[str, int]:
    """Install the four Yueke-original Web-security runtime specifications.

    Alembic owns all 12 course/lesson/definition shells. This installer creates
    versions only for labs 01/08/09/10, validates their fixed-image/fixed-grader
    contracts and binds the matching Challenge to that exact version/checkpoint.
    It does not claim Linux Node Agent or teacher-preview acceptance.
    """
    session = create_session_factory()()
    context = UserContext(
        user_id=SEED_USER_ID,
        role="teacher",
        teacher_id="teacher_web_security_seed",
        student_id=None,
        permissions=frozenset({"labs.read", "labs.write", "labs.publish"}),
        course_ids=frozenset({COURSE_ID}),
        class_ids=frozenset(),
    )
    service = LabService(session, context)
    created = 0
    published = 0
    bound = 0
    try:
        records = web_security_definition_records()
        for record in records:
            create = record["create"]
            spec = create.spec
            definition = session.get(LabDefinition, spec.lab_definition_id)
            if not definition:
                raise RuntimeError(f"Web 课程实验定义壳不存在：{spec.lab_definition_id}")
            if (
                definition.course_id != COURSE_ID
                or definition.code != create.code
                or definition.name != spec.name
                or definition.category != create.category
            ):
                raise RuntimeError(f"Web 实验定义与课程权威目录漂移：{spec.lab_definition_id}")

            version = session.scalar(
                select(LabVersion).where(
                    LabVersion.lab_definition_id == spec.lab_definition_id,
                    LabVersion.version == 1,
                )
            )
            expected = spec.model_dump(mode="json")
            if version:
                if version.spec_json != expected:
                    raise RuntimeError(f"已有 Web 实验 v1 与冻结定义冲突：{spec.lab_definition_id}")
            else:
                stamp = datetime.utcnow()
                version = LabVersion(
                    lab_version_id=f"labv_web_{record['number']:02d}_v1",
                    lab_definition_id=spec.lab_definition_id,
                    version=1,
                    status="DRAFT",
                    spec_json=expected,
                    validation_errors_json=[],
                    created_by=SEED_USER_ID,
                    created_at=stamp,
                    updated_at=stamp,
                    published_at=None,
                )
                session.add(version)
                session.flush()
                service.repo.replace_version_detail(version.lab_version_id, spec)
                enqueue_event(
                    session,
                    event_type="lab.version.seeded",
                    aggregate_type="lab_version",
                    aggregate_id=version.lab_version_id,
                    actor_user_id=SEED_USER_ID,
                    idempotency_key=f"web-security-v1-seed:{version.lab_version_id}",
                    payload={"course_id": COURSE_ID, "lab_definition_id": spec.lab_definition_id, "version": 1},
                )
                session.commit()
                created += 1

            if version.status != "PUBLISHED":
                service.validate_version(version.lab_version_id, f"web-security-v1-validate:{version.lab_version_id}")
                service.publish_version(version.lab_version_id, f"web-security-v1-publish:{version.lab_version_id}")
                version = session.get(LabVersion, version.lab_version_id)
                published += 1

            challenge = session.get(ChallengeDefinition, record["challenge_id"])
            if not challenge or challenge.course_id != COURSE_ID or challenge.lab_definition_id != spec.lab_definition_id:
                raise RuntimeError(f"Web Challenge 与实验定义不一致：{record['challenge_id']}")
            if challenge.lab_version_id not in (None, version.lab_version_id):
                raise RuntimeError(f"Web Challenge 已绑定其他实验版本：{record['challenge_id']}")
            if challenge.checkpoint_key not in (None, record["solution_checkpoint"]):
                raise RuntimeError(f"Web Challenge 已绑定其他 Checkpoint：{record['challenge_id']}")
            if challenge.lab_version_id is None or challenge.checkpoint_key is None:
                challenge.lab_version_id = version.lab_version_id
                challenge.checkpoint_key = record["solution_checkpoint"]
                enqueue_event(
                    session,
                    event_type="lab.challenge.runtime.bound",
                    aggregate_type="challenge",
                    aggregate_id=challenge.challenge_id,
                    actor_user_id=SEED_USER_ID,
                    idempotency_key=f"web-security-v1-bind:{challenge.challenge_id}",
                    payload={
                        "course_id": COURSE_ID,
                        "lab_definition_id": spec.lab_definition_id,
                        "lab_version_id": version.lab_version_id,
                        "checkpoint_key": record["solution_checkpoint"],
                    },
                )
                session.commit()
                bound += 1

        return {"definitions": len(records), "created_versions": created, "published_versions": published, "bound_challenges": bound}
    finally:
        session.close()


if __name__ == "__main__":
    print(seed_web_security_labs())
