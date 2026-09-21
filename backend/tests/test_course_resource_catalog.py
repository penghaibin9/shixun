from app.resources.catalog import LAB_LESSONS, THEORY_LESSONS, lesson_rows
from app.resources.media import parse_ffprobe_payload


def test_theory_catalog_is_exactly_37_with_required_chapter_shape_and_text():
    assert len(THEORY_LESSONS) == 37
    counts = {chapter: sum(row[0] == chapter for row in THEORY_LESSONS) for chapter in range(1, 8)}
    assert counts == {1: 5, 2: 3, 3: 6, 4: 7, 5: 7, 6: 5, 7: 4}
    text = "\n".join(title for _, _, title in THEORY_LESSONS)
    assert "数据存储加密（内容加密/磁盘加密）与传输加密（信源加密/通道加密）" in text
    assert "经典脱敏算法（替换/仿真/加密/遮掩/混淆/偏移/取整）" in text
    assert "行业数据安全治理实践（医疗/政务/工业领域案例）" in text
    assert "典型数据安全产品选型指南（加密类/脱敏类/审计类/管控类/备份类）" in text


def test_lab_catalog_has_12_structured_introductions_and_core_mapping():
    assert len(LAB_LESSONS) == 12
    lab_rows = [row for row in lesson_rows() if row["lesson_kind"] == "LAB"]
    assert len(lab_rows) == 12
    assert all(row["purpose"] and row["environment"] and row["principle"] and row["steps_summary"] for row in lab_rows)
    mapped = {row["core_experiment"] for row in lab_rows}
    assert {"AES/DES", "RSA", "MD5/SHA", "Base64/隐写", "数据库权限", "数据脱敏", "备份与灾难恢复", "日志审计与溯源"} <= mapped


def test_video_duration_is_parsed_from_ffprobe_payload():
    duration, width, height = parse_ffprobe_payload('{"format":{"duration":"2416.4"},"streams":[{"codec_type":"video","width":1920,"height":1080}]}')
    assert (duration, width, height) == (2416, 1920, 1080)
