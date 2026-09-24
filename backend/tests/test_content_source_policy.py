from pathlib import Path

from app.contentpacks.license_policy import LicenseDecision, evaluate_license


def test_seed_labs_is_reference_only_for_commercial_bundle():
    result = evaluate_license("CC-BY-NC-SA-4.0")
    assert result.decision == LicenseDecision.BLOCK


def test_web_candidate_registry_covers_all_12_labs():
    import json
    path = Path(__file__).resolve().parents[1] / "app" / "contentpacks" / "content" / "web-security-lab-candidates-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["labs"]) == 12
    assert [item["lesson_code"] for item in payload["labs"]] == [f"实验{n:02d}" for n in range(1, 13)]
    assert all(item["runtime_status"] for item in payload["labs"])
