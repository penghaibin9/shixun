import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402


target = ROOT / "docs" / "contracts" / "openapi-v1.json"
schema = app.openapi()
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"已冻结 {len(schema['paths'])} 条路径：{target}")
