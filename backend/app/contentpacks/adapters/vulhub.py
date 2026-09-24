from __future__ import annotations

import tomllib

from app.contentpacks.schemas import ExternalLabCandidate


VULHUB_REPOSITORY = "https://github.com/vulhub/vulhub"


def parse_environment_index(raw_toml: bytes) -> list[ExternalLabCandidate]:
    """Parse Vulhub's environments.toml into review-only candidates.

    This adapter intentionally imports metadata only. It does not run compose,
    clone repositories, pull images, or create Yueke runtime instances.
    """
    parsed = tomllib.loads(raw_toml.decode("utf-8"))
    rows = parsed.get("environment") or []
    candidates: list[ExternalLabCandidate] = []
    for row in rows:
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        dockerfile = row.get("dockerfile") or {}
        images = sorted(str(key) for key in dockerfile.keys()) if isinstance(dockerfile, dict) else []
        candidates.append(
            ExternalLabCandidate(
                source="Vulhub",
                source_path=path,
                source_url=f"{VULHUB_REPOSITORY}/tree/master/{path}",
                name=str(row.get("name") or path),
                app=str(row.get("app") or "Unknown"),
                cves=[str(item) for item in row.get("cve") or []],
                tags=[str(item) for item in row.get("tags") or []],
                images=images,
                license_id="MIT",
                import_status="REVIEW_REQUIRED",
            )
        )
    return candidates
