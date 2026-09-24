from app.challenges.schemas import ChallengeCreate, FlagConfigure
from app.challenges.service import ChallengeService


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
