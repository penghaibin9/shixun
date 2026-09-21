import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from app.resources.catalog import LAB_LESSONS
from app.resources.storage import archive_file_count
from app.teaching.catalog import curriculum_rows


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "backend" / "app" / "resources" / "content" / "lab-packs-v1.json"
PACK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "lab-file-packs-v1"


def test_lab_file_pack_catalog_and_archives_are_complete():
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    index = json.loads((PACK_DIR / "index.json").read_text(encoding="utf-8"))

    assert source["courseId"] == index["course_id"] == "course_data_security"
    assert source["version"] == index["content_version"]
    assert len(source["packs"]) == index["pack_count"] == len(LAB_LESSONS) == 12
    assert [pack["lessonCode"] for pack in source["packs"]] == [f"实验{code}" for code, _, _ in LAB_LESSONS]
    authority_ids = {
        lesson["lesson_code"]: lesson["lesson_id"]
        for lesson in curriculum_rows()["lessons"]
        if lesson["lesson_type"] == "LAB"
    }

    for entry in index["packs"]:
        archive_path = PACK_DIR / entry["filename"]
        assert archive_path.is_file()
        content = archive_path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert archive_file_count(str(archive_path), "application/zip") == entry["file_count"]

        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names)) == entry["file_count"]
            assert {"README.md", "NOTICE.txt", "pack-manifest.json"} <= set(names)
            assert all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names)
            manifest = json.loads(archive.read("pack-manifest.json"))
            assert manifest["lesson_code"] == entry["lesson_code"]
            assert manifest["lesson_id"] == authority_ids[manifest["lesson_code"]]
            assert manifest["verify_command"] == entry["verify_command"]
            assert manifest["expected_outputs"]
            for item in manifest["files"]:
                payload = archive.read(item["path"])
                assert len(payload) == item["size_bytes"]
                assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            readme = archive.read("README.md").decode("utf-8")
            assert entry["title"] in readme
            assert "安全边界" in readme


def test_lab_file_packs_contain_no_placeholder_or_production_secret_language():
    forbidden = ("TODO", "待补充", "示例密码请替换为生产密码", "真实身份证", "BEGIN OPENSSH PRIVATE KEY")
    for archive_path in sorted(PACK_DIR.glob("*.zip")):
        with ZipFile(archive_path) as archive:
            text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if not name.endswith("/")
            )
        assert not any(value in text for value in forbidden)
