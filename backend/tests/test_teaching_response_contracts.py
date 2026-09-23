from app.main import app


def _success_schema(contract: dict, path: str, method: str) -> dict:
    operation = contract["paths"][path][method]
    status = "201" if "201" in operation["responses"] else "200"
    return operation["responses"][status]["content"]["application/json"]["schema"]


def test_teaching_json_responses_are_explicit_named_models():
    """Teaching browser and mutation APIs must not fall back to object-v1."""

    expected = {
        ("/api/v1/courses", "post"): "CourseSummaryResponse",
        ("/api/v1/courses", "get"): "CourseListResponse",
        ("/api/v1/courses/{course_id}", "get"): "CourseResponse",
        ("/api/v1/courses/{course_id}", "patch"): "CourseResponse",
        ("/api/v1/courses/{course_id}/lessons", "get"): "CourseLessonListResponse",
        ("/api/v1/classes", "post"): "TeachingClassCreateResponse",
        ("/api/v1/classes", "get"): "TeachingClassListResponse",
        ("/api/v1/classes/{class_id}", "get"): "TeachingClassResponse",
        ("/api/v1/classes/{class_id}/members", "get"): "ClassMemberListResponse",
        ("/api/v1/classes/{class_id}/members", "post"): "ClassMemberResponse",
        ("/api/v1/classes/{class_id}/members/{membership_id}", "get"): "ClassMemberResponse",
        ("/api/v1/classes/{class_id}/members/{membership_id}", "delete"): "MemberRemovalResponse",
        ("/api/v1/classes/{class_id}/members/{membership_id}/learning-summary", "get"): "MemberLearningSummaryResponse",
        ("/api/v1/classes/{class_id}/students/{student_id}/learning-summary", "get"): "MemberLearningSummaryResponse",
        ("/api/v1/classes/{class_id}/members/import", "post"): "MemberImportJobResponse",
        ("/api/v1/import-jobs/{job_id}", "get"): "MemberImportJobResponse",
        ("/api/v1/classes/{class_id}/roster/freeze", "post"): "RosterFreezeResponse",
        ("/api/v1/attendance/tasks", "post"): "AttendanceTaskResponse",
        ("/api/v1/attendance/tasks", "get"): "AttendanceTaskListResponse",
        ("/api/v1/attendance/tasks/{task_id}", "get"): "AttendanceTaskResponse",
        ("/api/v1/attendance/tasks/{task_id}/publish", "post"): "AttendancePublishedResponse",
        ("/api/v1/attendance/tasks/{task_id}/close", "post"): "AttendanceTaskResponse",
        ("/api/v1/attendance/tasks/{task_id}/records", "get"): "AttendanceRecordListResponse",
        ("/api/v1/attendance/section-summary", "get"): "AttendanceSectionSummaryResponse",
        ("/api/v1/attendance/sign-links/{token}", "get"): "AttendanceLinkResponse",
        ("/api/v1/attendance/sign-links/{token}/sign", "post"): "AttendanceRecordResponse",
        ("/api/v1/attendance/{task_id}/sign", "post"): "AttendanceRecordResponse",
        ("/api/v1/polls", "post"): "PollCreatedResponse",
        ("/api/v1/polls/{poll_id}/publish", "post"): "PollResponse",
        ("/api/v1/polls/{poll_id}/answers", "post"): "PollAnswerResponse",
        ("/api/v1/polls/{poll_id}/results", "get"): "PollResultsResponse",
        ("/api/v1/assignments", "post"): "AssignmentResponse",
        ("/api/v1/assignments/{assignment_id}/publish", "post"): "AssignmentResponse",
        ("/api/v1/assignments/{assignment_id}/submit", "post"): "AssignmentSubmissionResponse",
        ("/api/v1/assignments/my", "get"): "StudentAssignmentListResponse",
        ("/api/v1/assignments/{assignment_id}/student-task", "get"): "StudentAssignmentTaskResponse",
        ("/api/v1/quizzes", "post"): "QuizResponse",
        ("/api/v1/quizzes/{quiz_id}/publish", "post"): "QuizResponse",
        ("/api/v1/quizzes/{quiz_id}/attempts", "post"): "QuizAttemptResponse",
        ("/api/v1/quizzes/{quiz_id}/attempts/{attempt_id}/submit", "post"): "QuizAttemptResponse",
        ("/api/v1/quizzes/my", "get"): "StudentQuizListResponse",
        ("/api/v1/quizzes/{quiz_id}/student-task", "get"): "StudentQuizTaskResponse",
        ("/api/v1/teaching/read-model", "get"): "TeacherReadModelResponse",
        ("/api/v1/teaching/student-read-model", "get"): "StudentReadModelResponse",
    }
    contract = app.openapi()
    for (path, method), model_name in expected.items():
        response = _success_schema(contract, path, method)
        assert response["$ref"].endswith(f"/{model_name}")


def test_teaching_xlsx_downloads_are_binary_contracts():
    contract = app.openapi()
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    for path in (
        "/api/v1/classes/{class_id}/members/import-template",
        "/api/v1/import-jobs/{job_id}/error-rows.xlsx",
        "/api/v1/classes/{class_id}/members/export.xlsx",
        "/api/v1/attendance/{task_id}/export.xlsx",
    ):
        content = contract["paths"][path]["get"]["responses"]["200"]["content"]
        assert content == {media_type: {"schema": {"type": "string", "format": "binary"}}}
