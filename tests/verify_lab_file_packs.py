from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "outputs" / "01a0c33f-d483-7ac0-aa95-632194b582d5" / "lab-file-packs-v1"
index = json.loads((PACK_DIR / "index.json").read_text(encoding="utf-8"))
results = []

for entry in index["packs"]:
    archive_path = PACK_DIR / entry["filename"]
    with tempfile.TemporaryDirectory(prefix=f"{entry['slug']}-") as temp_dir:
        workdir = Path(temp_dir)
        with ZipFile(archive_path) as archive:
            for name in archive.namelist():
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError(f"不安全路径：{entry['filename']} {name}")
            archive.extractall(workdir)
        completed = subprocess.run(
            ["sh", "-c", entry["verify_command"]],
            cwd=workdir,
            text=True,
            capture_output=True,
            timeout=90,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{entry['lesson_code']} 验证失败\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        manifest = json.loads((workdir / "pack-manifest.json").read_text(encoding="utf-8"))
        missing = [name for name in manifest["expected_outputs"] if not (workdir / name).is_file()]
        if missing:
            raise RuntimeError(f"{entry['lesson_code']} 缺少预期产物：{missing}")
        results.append(
            {
                "lesson_code": entry["lesson_code"],
                "filename": entry["filename"],
                "status": "PASS",
                "stdout": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "",
            }
        )

print(json.dumps({"pack_count": len(results), "passed": len(results), "results": results}, ensure_ascii=False, indent=2))
