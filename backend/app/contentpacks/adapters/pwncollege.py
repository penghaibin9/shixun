from __future__ import annotations

import yaml

from app.contentpacks.schemas import DojoPreviewResponse


def parse_dojo_manifest(raw_yaml: bytes) -> DojoPreviewResponse:
    """Read dojo/module structure only; external challenge content is not copied."""
    payload = yaml.safe_load(raw_yaml.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dojo.yml 根节点必须是对象")
    dojo_id = str(payload.get("id") or "").strip()
    name = str(payload.get("name") or dojo_id).strip()
    if not dojo_id:
        raise ValueError("缺少 dojo id")
    modules = []
    for item in payload.get("modules") or []:
        if isinstance(item, str):
            modules.append({"id": item, "name": item})
        elif isinstance(item, dict) and item.get("id"):
            modules.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"])})
    return DojoPreviewResponse(
        dojo_id=dojo_id,
        name=name,
        module_count=len(modules),
        modules=modules,
        content_imported=False,
    )
