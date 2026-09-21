from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "app" / "resources" / "content" / "lab-packs-v1.json"
OUTPUT_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "lab-file-packs-v1"
FIXED_TIMESTAMP = (2026, 9, 22, 0, 0, 0)


def safe_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError(f"不安全的包内路径：{value}")
    return normalized


def zip_info(name: str, executable: bool = False) -> ZipInfo:
    info = ZipInfo(safe_path(name), FIXED_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
    return info


def readme(pack: dict) -> str:
    numbered_steps = "\n".join(f"{index}. {value}" for index, value in enumerate(pack["steps"], start=1))
    principles = "\n".join(f"- {value}" for value in pack["principles"])
    expected = "\n".join(f"- `{value}`" for value in pack["expected"])
    return f"""# {pack['lessonCode']} {pack['title']}

## 实验目标

{pack['objective']}

## 环境

{pack['environment']}

## 原理

{principles}

## 操作步骤

{numbered_steps}

## 验证命令

```sh
{pack['verifyCommand']}
```

## 预期产物

{expected}

## 安全边界

本文件包只用于平台隔离实验环境；示例口令、密钥、账号和数据均为教学数据，不得用于生产系统。
"""


def build_pack(source_version: str, pack: dict) -> dict:
    payload: dict[str, bytes] = {
        "README.md": readme(pack).encode("utf-8"),
        "NOTICE.txt": "跃科网络空间安全实训平台原创教学文件包。仅含合成数据，不含生产凭据或真实个人信息。\n".encode("utf-8"),
    }
    for item in pack["files"]:
        name = safe_path(item["path"])
        if name in payload:
            raise ValueError(f"重复文件：{pack['lessonCode']} {name}")
        payload[name] = item["content"].encode("utf-8")

    manifest = {
        "schema_version": "1.0",
        "content_version": source_version,
        "course_id": "course_data_security",
        "lesson_id": pack["lessonId"],
        "lesson_code": pack["lessonCode"],
        "slug": pack["slug"],
        "title": pack["title"],
        "verify_command": pack["verifyCommand"],
        "expected_outputs": pack["expected"],
        "files": [
            {"path": name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(payload.items())
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payload["pack-manifest.json"] = manifest_bytes

    output_path = OUTPUT_DIR / f"{pack['slug']}-v1.zip"
    with ZipFile(output_path, "w") as archive:
        for name, content in sorted(payload.items()):
            executable = name.endswith(".sh") or name.endswith(".py")
            archive.writestr(zip_info(name, executable), content)
    archive_bytes = output_path.read_bytes()
    return {
        "lesson_id": pack["lessonId"],
        "lesson_code": pack["lessonCode"],
        "slug": pack["slug"],
        "title": pack["title"],
        "filename": output_path.name,
        "file_count": len(payload),
        "size_bytes": len(archive_bytes),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "verify_command": pack["verifyCommand"],
    }


data = json.loads(SOURCE.read_text(encoding="utf-8"))
packs = data["packs"]
if data["courseId"] != "course_data_security" or len(packs) != 12:
    raise ValueError("实验文件包必须属于固定课程并正好包含12个实验")
if len({pack["lessonId"] for pack in packs}) != 12 or len({pack["lessonCode"] for pack in packs}) != 12:
    raise ValueError("实验文件包课时标识或编号重复")
if [pack["lessonCode"] for pack in packs] != [f"实验{index:02d}" for index in range(1, 13)]:
    raise ValueError("实验文件包必须按实验01至实验12排序")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
expected_names = {f"{pack['slug']}-v1.zip" for pack in packs} | {"index.json"}
for existing in OUTPUT_DIR.iterdir():
    if existing.is_file() and existing.name not in expected_names:
        raise ValueError(f"输出目录包含未知文件，拒绝覆盖：{existing.name}")

index = {
    "schema_version": "1.0",
    "content_version": data["version"],
    "course_id": data["courseId"],
    "pack_count": 12,
    "packs": [build_pack(data["version"], pack) for pack in packs],
}
(OUTPUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(index, ensure_ascii=False, indent=2))
