from __future__ import annotations

import yaml

from app.contentpacks.schemas import AtomicTechniquePreviewResponse


def parse_atomic_technique(raw_yaml: bytes) -> AtomicTechniquePreviewResponse:
    """Read ATT&CK/test metadata only; never import or execute Atomic commands."""
    payload = yaml.safe_load(raw_yaml.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Atomic YAML 根节点必须是对象")
    technique = str(payload.get("attack_technique") or "").strip()
    display_name = str(payload.get("display_name") or technique).strip()
    if not technique:
        raise ValueError("缺少 attack_technique")
    tests = []
    for item in payload.get("atomic_tests") or []:
        if not isinstance(item, dict):
            continue
        executor = item.get("executor") if isinstance(item.get("executor"), dict) else {}
        dependencies = item.get("dependencies") if isinstance(item.get("dependencies"), list) else []
        tests.append({
            "name": str(item.get("name") or "未命名 Atomic Test"),
            "guid": str(item.get("auto_generated_guid") or "") or None,
            "supported_platforms": [str(value) for value in item.get("supported_platforms") or []],
            "executor_name": str(executor.get("name") or "unknown"),
            "dependency_count": len(dependencies),
        })
    return AtomicTechniquePreviewResponse(
        attack_technique=technique,
        display_name=display_name,
        test_count=len(tests),
        tests=tests,
        execution_imported=False,
    )
