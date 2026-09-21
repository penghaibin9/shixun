import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_openapi_is_valid_and_has_v1_contracts():
    contract = json.loads((ROOT / "docs/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    assert contract["openapi"].startswith("3.1")
    assert "/api/v1/auth/context" in contract["paths"]
    assert "Error" in contract["components"]["schemas"]


def test_context_requires_identity_and_returns_frozen_shape():
    client = TestClient(app)
    assert client.get("/api/v1/auth/context").json()["code"] == "AUTH.UNAUTHENTICATED"
    response = client.get("/api/v1/auth/context", headers={"X-User-Id": "usr_1", "X-Role": "teacher", "X-Course-Ids": "course_1", "X-Class-Ids": "class_1"})
    assert response.status_code == 200
    assert response.json()["course_ids"] == ["course_1"]
    assert response.headers["X-Request-Id"].startswith("req_")
