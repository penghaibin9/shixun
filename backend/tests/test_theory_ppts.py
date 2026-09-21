from __future__ import annotations

import hashlib
import json
import re
from xml.etree import ElementTree
from pathlib import Path
from zipfile import ZipFile

from app.teaching.catalog import THEORY_LESSONS, curriculum_rows


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "backend" / "app" / "resources" / "content" / "theory-ppts-v1.json"
DECK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "theory-ppts-v1"


def text_from_xml(content: bytes) -> str:
    root = ElementTree.fromstring(content)
    return " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))


def localized_visible_text(value: str) -> str:
    replacements = [
        (r"\bSHA-256\b(?!（)", "SHA-256（256位安全散列算法）"),
        (r"\bAES\b(?![-\w]|（)", "AES（高级加密标准）"),
        (r"\bDES\b(?![-\w]|（)", "DES（数据加密标准）"),
        (r"\bRSA\b(?![-\w]|（)", "RSA（非对称加密算法）"),
        (r"\bMD5\b(?![-\w]|（)", "MD5（消息摘要算法第5版）"),
        (r"\bSHA\b(?![-\w]|（)", "SHA（安全散列算法）"),
        (r"\bSM2\b(?![-\w]|（)", "SM2（国密公钥算法）"),
        (r"\bSM3\b(?![-\w]|（)", "SM3（国密杂凑算法）"),
        (r"\bSM4\b(?![-\w]|（)", "SM4（国密分组密码算法）"),
        (r"\bBase64\b(?![-\w]|（)", "Base64（基础64编码）"),
        (r"\bRBAC\b(?![-\w]|（)", "RBAC（基于角色的访问控制）"),
        (r"\bECB\b(?![-\w]|（)", "ECB（电子密码本模式）"),
        (r"\bCBC\b(?![-\w]|（)", "CBC（密码分组链接模式）"),
        (r"\bTLS\b(?![-\w]|（)", "TLS（传输层安全协议）"),
        (r"\bHTTPS\b(?![-\w]|（)", "HTTPS（超文本传输安全协议）"),
        (r"\bIoT\b(?![-\w]|（)", "IoT（物联网）"),
        (r"\bMFA\b(?![-\w]|（)", "MFA（多因素认证）"),
        (r"\bMPC\b(?![-\w]|（)", "MPC（安全多方计算）"),
        (r"\bPoC\b(?![-\w]|（)", "PoC（概念验证）"),
        (r"\bRPO\b(?![-\w]|（)", "RPO（恢复点目标）"),
        (r"\bRTO\b(?![-\w]|（)", "RTO（恢复时间目标）"),
        (r"\bUTF-8\b(?![-\w]|（)", "UTF-8（8位统一字符编码格式）"),
        (r"\bIETF\b(?![-\w]|（)", "IETF（互联网工程任务组）"),
        (r"\bRFC\b(?![-\w]|（)", "RFC（征求意见稿标准）"),
        (r"\bNIST\b(?![-\w]|（)", "NIST（美国国家标准与技术研究院）"),
        (r"\bFIPS\b(?![-\w]|（)", "FIPS（联邦信息处理标准）"),
        (r"\bSP\b(?![-\w]|（)", "SP（特别出版物）"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return value


def test_theory_ppt_source_matches_the_37_lesson_contract():
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    authority = curriculum_rows(source["courseId"])
    assert len(authority["chapters"]) == 8
    assert len(authority["lessons"]) == 49
    assert len({row["lesson_id"] for row in authority["lessons"]}) == 49
    theory_authority = {
        row["lesson_code"]: (row["lesson_type"], row["title"])
        for row in authority["lessons"]
        if row["lesson_type"] == "THEORY"
    }
    assert len(theory_authority) == 37
    expected = [
        (chapter, code, title)
        for chapter, code, title in THEORY_LESSONS
    ]
    actual = [
        (int(item["lessonCode"].split(".")[0]), item["lessonCode"], item["title"])
        for item in source["lessons"]
    ]
    assert source["courseId"] == "course_data_security"
    assert source["version"] == "1.0.0"
    assert actual == expected
    assert len({item["lessonCode"] for item in source["lessons"]}) == 37
    assert {
        item["lessonCode"]: ("THEORY", item["title"])
        for item in source["lessons"]
    } == theory_authority
    for item in source["lessons"]:
        assert len(item["learningObjectives"]) == 2
        assert 3 <= len(item["conceptSlides"]) <= 5
        assert item["caseExample"].strip()
        assert item["knowledgeCheck"]["question"].strip()
        assert item["knowledgeCheck"]["answer"].strip()
        assert item["references"]
        assert all(
            reference["title"].strip()
            and (
                reference["url"].startswith("https://")
                or reference["url"].startswith("backend/app/resources/content/question-bank-v1.json#")
            )
            for reference in item["references"]
        )
        assert all(
            concept["title"].strip()
            and concept["explanation"].strip()
            and 2 <= len(concept["points"]) <= 4
            and all(point.strip() for point in concept["points"])
            for concept in item["conceptSlides"]
        )

    lessons = {item["lessonCode"]: json.dumps(item, ensure_ascii=False) for item in source["lessons"]}
    for term in ["内容加密", "磁盘加密", "信源加密", "通道加密"]:
        assert term in lessons["3.6"]
    for term in ["替换", "仿真", "加密", "遮掩", "混淆", "偏移", "取整"]:
        assert term in lessons["4.2"]
    for term in ["医疗", "政务", "工业"]:
        assert term in lessons["7.3"]
    for term in ["加密类", "脱敏类", "审计类", "管控类", "备份类"]:
        assert term in lessons["7.4"]


def test_theory_ppt_files_are_complete_traceable_and_animation_free():
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    index = json.loads((DECK_DIR / "index.json").read_text(encoding="utf-8"))
    source_by_code = {item["lessonCode"]: item for item in source["lessons"]}
    assert index["deck_count"] == len(index["decks"]) == 37
    assert {entry["lesson_code"] for entry in index["decks"]} == set(source_by_code)
    assert index["slide_total"] == sum(item["slide_count"] for item in index["decks"])
    assert index["font"] == "Microsoft YaHei"

    for entry in index["decks"]:
        lesson = source_by_code[entry["lesson_code"]]
        deck_path = DECK_DIR / entry["filename"]
        deck_bytes = deck_path.read_bytes()
        assert hashlib.sha256(deck_bytes).hexdigest() == entry["sha256"]
        assert len(deck_bytes) == entry["size_bytes"]
        assert entry["slide_count"] == len(lesson["conceptSlides"]) + 4
        assert 7 <= entry["slide_count"] <= 9
        assert entry["quality_design"] == {
            "knowledge_complete": True,
            "layout_overflow_validated": True,
            "animation_count": 0,
            "copyright_noted": True,
        }

        with ZipFile(deck_path) as archive:
            names = archive.namelist()
            slide_names = sorted(
                name
                for name in names
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            )
            note_names = sorted(
                name
                for name in names
                if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
            )
            assert len(slide_names) == entry["slide_count"]
            assert len(note_names) == entry["slide_count"]
            presentation_xml = archive.read("ppt/presentation.xml")
            assert b'cx="12192000"' in presentation_xml and b'cy="6858000"' in presentation_xml
            slide_xml = [archive.read(name) for name in slide_names]
            all_text = " ".join(text_from_xml(content) for content in slide_xml)
            notes_text = " ".join(text_from_xml(archive.read(name)) for name in note_names)
            assert lesson["lessonCode"] in all_text
            assert entry["display_title"] in all_text
            assert localized_visible_text(lesson["knowledgeCheck"]["question"]) in all_text
            assert all(reference["url"] in notes_text for reference in lesson["references"])
            assert all(b"<p:timing" not in content for content in slide_xml)
            assert "来源与版权信息见演讲者备注" in all_text


def test_theory_ppt_content_has_no_placeholders_or_customer_visible_raw_fields():
    source_text = SOURCE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "TODO",
        "待补充",
        "lorem ipsum",
        "lesson_id",
        "raw_json",
        "示例内容",
        "用于支撑本课目标",
        "场景中，需要把原理落实",
        "案例落点",
        "检查结论",
        "关系及组合使用方式",
    )
    assert not any(value.lower() in source_text.lower() for value in forbidden)
