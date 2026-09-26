from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.challenges.models import ChallengeAttempt, ChallengeDefinition, ChallengeHint
from app.challenges.schemas import ChallengeCreate, FlagConfigure, FlagSubmit
from app.challenges.service import ChallengeService
from app.common.context import UserContext
from app.common.errors import ApiError
from app.common.models import Base
from app.main import app as _loaded_app  # noqa: F401 - loads all model metadata
from app.teaching.models import Course, CourseChapter, CourseLesson, TeachingClass


def test_flag_hash_does_not_store_plaintext_contract():
    salt = "1234567890abcdef"
    value = "YK{demo-only}"
    digest = ChallengeService._flag_hash(salt, value)
    assert value not in digest
    assert len(digest) == 64


def test_flag_normalization_can_be_case_sensitive_or_insensitive():
    assert ChallengeService._normalize("  YK{AbC}  ", True) == "YK{AbC}"
    assert ChallengeService._normalize("  YK{AbC}  ", False) == "yk{abc}"


def test_challenge_contract_requires_lab_course_scope_fields():
    body = ChallengeCreate(
        course_id="course_web_security",
        lesson_id="lesson-web-01",
        title="HTTP 安全基线",
        description="授权隔离实验",
        difficulty="BEGINNER",
    )
    assert body.max_attempts == 10
    assert FlagConfigure(flag="YK{demo}").case_sensitive is True



def test_flag_submission_requires_authoritative_runtime_lineage():
    body = FlagSubmit(
        submission="YK{runtime-bound}",
        class_id="class-a",
        lab_release_id="release-a",
        runtime_instance_id="runtime-a",
    )
    assert body.lab_release_id == "release-a"
    assert body.runtime_instance_id == "runtime-a"

    with pytest.raises(ValidationError):
        FlagSubmit(submission="YK{bypass}", class_id="class-a")



def _challenge_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _teacher_context() -> UserContext:
    return UserContext(
        user_id="teacher-challenge",
        role="teacher",
        teacher_id="teacher-challenge",
        student_id=None,
        permissions=frozenset({"labs.read", "labs.write"}),
        course_ids=frozenset({"course_web_security"}),
        class_ids=frozenset({"class-web"}),
    )


def _student_context() -> UserContext:
    return UserContext(
        user_id="student-challenge",
        role="student",
        teacher_id=None,
        student_id="student-challenge",
        permissions=frozenset({"classroom.lab.read"}),
        course_ids=frozenset({"course_web_security"}),
        class_ids=frozenset({"class-web"}),
    )


def _seed_challenge_course(session) -> None:
    stamp = datetime.utcnow()
    session.add(
        Course(
            course_id="course_web_security",
            name="Web 应用安全实训",
            term="2026 秋季",
            catalog_key="web_security_v1",
            owner_teacher_id="teacher-challenge",
            major="网络空间安全",
            description="测试课程",
            status="ACTIVE",
            created_at=stamp,
        )
    )
    session.add(
        CourseChapter(
            chapter_id="chapter-web-lab",
            course_id="course_web_security",
            title="Web 安全实验",
            sequence=1,
        )
    )
    session.add(
        CourseLesson(
            lesson_id="lesson-web-01",
            course_id="course_web_security",
            chapter_id="chapter-web-lab",
            lesson_code="实验01",
            title="HTTP 请求观察与安全基线",
            sequence=1,
            lesson_type="LAB",
        )
    )
    session.add(
        TeachingClass(
            class_id="class-web",
            name="Web 安全 1 班",
            term="2026 秋季",
            owner_teacher_id="teacher-challenge",
            created_at=stamp,
        )
    )
    session.commit()


def test_create_persists_checkpoint_only_validation_mode_and_returns_it():
    session = _challenge_session()
    try:
        _seed_challenge_course(session)
        service = ChallengeService(session, _teacher_context())
        result = service.create_challenge(
            ChallengeCreate(
                course_id="course_web_security",
                lesson_id="lesson-web-01",
                title="HTTP 安全基线",
                description="只由权威 Checkpoint 决定挑战完成事实。",
                validation_mode="CHECKPOINT_ONLY",
            )
        )
        stored = session.get(ChallengeDefinition, result["challenge_id"])
        assert result["validation_mode"] == "CHECKPOINT_ONLY"
        assert stored is not None and stored.validation_mode == "CHECKPOINT_ONLY"
    finally:
        session.close()


def test_student_list_hides_locked_challenge_but_teacher_sees_full_sequence():
    session = _challenge_session()
    try:
        _seed_challenge_course(session)
        stamp = datetime.utcnow()
        first = ChallengeDefinition(
            challenge_id="challenge-first",
            course_id="course_web_security",
            lesson_id="lesson-web-01",
            lab_definition_id=None,
            lab_version_id=None,
            checkpoint_key=None,
            prerequisite_challenge_id=None,
            title="第一关",
            description="第一关",
            difficulty="BEGINNER",
            max_attempts=10,
            validation_mode="CHECKPOINT_ONLY",
            status="PUBLISHED",
            created_by="teacher-challenge",
            created_at=stamp,
            published_at=stamp,
        )
        second = ChallengeDefinition(
            challenge_id="challenge-second",
            course_id="course_web_security",
            lesson_id="lesson-web-01",
            lab_definition_id=None,
            lab_version_id=None,
            checkpoint_key=None,
            prerequisite_challenge_id="challenge-first",
            title="第二关",
            description="第二关",
            difficulty="BEGINNER",
            max_attempts=10,
            validation_mode="CHECKPOINT_ONLY",
            status="PUBLISHED",
            created_by="teacher-challenge",
            created_at=stamp,
            published_at=stamp,
        )
        session.add_all([first, second])
        session.commit()

        student_items = ChallengeService(session, _student_context()).list_challenges(
            "course_web_security",
            "class-web",
        )["items"]
        assert [item["challenge_id"] for item in student_items] == ["challenge-first"]

        teacher_items = ChallengeService(session, _teacher_context()).list_challenges(
            "course_web_security",
            "class-web",
        )["items"]
        assert {item["challenge_id"] for item in teacher_items} == {"challenge-first", "challenge-second"}

        student = ChallengeService(session, _student_context())
        with pytest.raises(ApiError) as locked:
            student.get_challenge("challenge-second", "class-web")
        assert locked.value.code == "CHALLENGE.LOCKED"
        with pytest.raises(ApiError) as locked_hints:
            student.hints("challenge-second", "class-web")
        assert locked_hints.value.code == "CHALLENGE.LOCKED"
        with pytest.raises(ApiError) as locked_submit:
            student.submit("challenge-second", FlagSubmit(class_id="class-web", lab_release_id="release-a", runtime_instance_id="runtime-a"))
        assert locked_submit.value.code == "CHALLENGE.LOCKED"

        session.add(ChallengeAttempt(
            attempt_id="attempt-first", challenge_id="challenge-first", student_id="student-challenge",
            class_id="class-web", lab_release_id=None, runtime_instance_id=None,
            checkpoint_result_id=None, attempt_no=1, accepted=True, created_at=stamp,
        ))
        session.commit()
        assert student.get_challenge("challenge-second", "class-web")["unlocked"] is True
        assert [item["challenge_id"] for item in student.list_challenges("course_web_security", "class-web")["items"]] == ["challenge-first", "challenge-second"]
    finally:
        session.close()


def test_student_cannot_read_unpublished_challenge_or_its_hints_by_id():
    session = _challenge_session()
    try:
        _seed_challenge_course(session)
        stamp = datetime.utcnow()
        session.add(ChallengeDefinition(
            challenge_id="draft-challenge", course_id="course_web_security", lesson_id="lesson-web-01",
            lab_definition_id=None, lab_version_id=None, checkpoint_key=None,
            prerequisite_challenge_id=None, title="未发布挑战", description="教师草稿",
            difficulty="BEGINNER", max_attempts=10, validation_mode="CHECKPOINT_ONLY",
            status="DRAFT", created_by="teacher-challenge", created_at=stamp, published_at=None,
        ))
        session.add(ChallengeHint(
            hint_id="draft-hint", challenge_id="draft-challenge", sequence=1,
            title="草稿提示", content="仅供教师", unlock_after_attempts=0,
            created_by="teacher-challenge", created_at=stamp,
        ))
        session.commit()
        student = ChallengeService(session, _student_context())
        for read in (student.get_challenge, student.hints):
            with pytest.raises(ApiError) as error:
                read("draft-challenge", "class-web")
            assert error.value.code == "CHALLENGE.NOT_FOUND"
        assert ChallengeService(session, _teacher_context()).get_challenge("draft-challenge")["status"] == "DRAFT"
    finally:
        session.close()
