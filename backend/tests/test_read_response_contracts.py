"""关键读取 API 必须在 OpenAPI 中直接引用具名响应模型。"""

from app.main import app


def response_ref(openapi: dict, path: str, method: str, status_code: str = "200") -> str:
    return openapi["paths"][path][method]["responses"][status_code]["content"]["application/json"]["schema"]["$ref"]


def test_grading_read_routes_reference_frozen_named_responses():
    openapi = app.openapi()
    expected = {
        ("/api/v1/grading/courses/{course_id}/recalculate", "post"): "GradebookStateResponse",
        ("/api/v1/grading/courses/{course_id}/post", "post"): "GradebookStateResponse",
        ("/api/v1/gradebook/courses/{course_id}", "get"): "GradebookResponse",
        ("/api/v1/gradebook/courses/{course_id}/students/{student_id}", "get"): "GradebookResponse",
        ("/api/v1/gradebook/courses/{course_id}/trace/{student_id}", "get"): "GradebookTraceResponse",
        ("/api/v1/analytics/courses/{course_id}/overview", "get"): "AnalyticsOverviewResponse",
        ("/api/v1/analytics/courses/{course_id}/sections/{lesson_id}", "get"): "AnalyticsSectionResponse",
        ("/api/v1/analytics/courses/{course_id}/labs/by-student", "get"): "AnalyticsStudentLabListResponse",
        ("/api/v1/analytics/courses/{course_id}/labs/by-lab", "get"): "AnalyticsLabListResponse",
        ("/api/v1/analytics/courses/{course_id}/risks", "get"): "StudentRiskListResponse",
        ("/api/v1/analytics/courses/{course_id}/learning-summary", "get"): "LearningSummaryResponse",
        ("/api/v1/archives/courses/{course_id}/precheck", "post"): "ArchivePrecheckResponse",
        ("/api/v1/archives/courses/{course_id}/freeze", "post"): "ArchiveManifestPayloadResponse",
        ("/api/v1/archives/courses/{course_id}", "get"): "ArchiveResponse",
        ("/api/v1/archives/courses/{course_id}/manifest", "get"): "ArchiveManifestReadResponse",
        ("/api/v1/audit/events", "get"): "AuditEventListResponse",
    }
    for (path, method), model_name in expected.items():
        assert response_ref(openapi, path, method).endswith(f"/{model_name}")
        assert openapi["components"]["schemas"][model_name]["additionalProperties"] is False


def test_classroom_read_routes_reference_frozen_named_responses():
    openapi = app.openapi()
    expected = {
        ("/api/v1/classroom/lab-releases/{release_id}/summary", "get"): "ClassroomReleaseSummaryResponse",
        ("/api/v1/classroom/lab-releases/{release_id}/students", "get"): "ClassroomReleaseStudentListResponse",
        ("/api/v1/classroom/lab-releases/{release_id}/students/{student_id}", "get"): "ClassroomStudentRuntimeResponse",
        ("/api/v1/classroom/my/lab-releases/{release_id}", "get"): "ClassroomStudentRuntimeResponse",
        ("/api/v1/teaching-logs/audit", "get"): "TeachingAuditLogListResponse",
        ("/api/v1/teaching-logs/traffic", "get"): "TrafficLogListResponse",
        ("/api/v1/teaching-logs/traffic/{artifact_id}/download", "get"): "LogDownloadResponse",
        ("/api/v1/teaching-logs/distributions", "get"): "TeachingLogDistributionListResponse",
        ("/api/v1/teaching-logs/distributions", "post"): "TeachingLogDistributionResponse",
        ("/api/v1/teaching-logs/distributions/{distribution_id}", "get"): "TeachingLogDistributionResponse",
        ("/api/v1/teaching-logs/my-assignments", "get"): "StudentLogAssignmentListResponse",
        ("/api/v1/teaching-logs/my-assignments/{assignment_id}/download", "get"): "LogDownloadResponse",
        ("/api/v1/classroom/read-model/students/{student_id}/learning-summary", "get"): "ClassroomLearningSummaryResponse",
    }
    for (path, method), model_name in expected.items():
        status_code = "201" if (path, method) == ("/api/v1/teaching-logs/distributions", "post") else "200"
        assert response_ref(openapi, path, method, status_code).endswith(f"/{model_name}")
        assert openapi["components"]["schemas"][model_name]["additionalProperties"] is False
