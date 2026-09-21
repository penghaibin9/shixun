from app.teaching.catalog import COURSE_ID, LAB_LESSONS, THEORY_LESSONS


def lesson_rows() -> list[dict]:
    """Return stable legacy extension rows for migrations and content tooling.

    Course, chapter, lesson code, type and title are authoritative in A's
    ``course_lesson`` catalog. New production reads must not use these copied
    fields; migration 0013 retains them only for a safe expand/contract rollout.
    """
    rows = [
        {
            "lesson_resource_id": f"lr_theory_{code.replace('.', '_')}",
            "course_id": COURSE_ID,
            "lesson_id": f"lesson_theory_{code.replace('.', '_')}",
            "lesson_kind": "THEORY",
            "chapter_no": chapter,
            "lesson_code": code,
            "title": title,
            "purpose": None,
            "environment": None,
            "principle": None,
            "steps_summary": None,
            "core_experiment": None,
        }
        for chapter, code, title in THEORY_LESSONS
    ]
    rows.extend(
        {
            "lesson_resource_id": f"lr_lab_{code}",
            "course_id": COURSE_ID,
            "lesson_id": f"lesson_lab_{code}",
            "lesson_kind": "LAB",
            "chapter_no": None,
            "lesson_code": f"实验{code}",
            "title": title,
            "purpose": f"掌握{title}的核心操作与安全要点。",
            "environment": "由 C 线实验定义提供隔离环境；B 线仅维护教学资源说明。",
            "principle": f"理解{core}相关原理，并验证关键结果。",
            "steps_summary": "准备环境、执行关键步骤、验证结果、完成复盘。",
            "core_experiment": core,
        }
        for code, core, title in LAB_LESSONS
    )
    return rows
