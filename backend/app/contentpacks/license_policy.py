from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LicenseDecision(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class LicenseEvaluation:
    decision: LicenseDecision
    reason: str


_PERMISSIVE = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
}

_NONCOMMERCIAL_MARKERS = (
    "CC-BY-NC",
    "CC BY-NC",
    "NONCOMMERCIAL",
)


def evaluate_license(license_id: str | None) -> LicenseEvaluation:
    """Classify external content for Yueke's commercial distribution path.

    ALLOW means the known permissive license can enter automated intake while
    preserving notices. REVIEW means legal/attribution review is required.
    BLOCK means the asset must stay reference-only for the commercial bundle.
    """
    if not license_id:
        return LicenseEvaluation(LicenseDecision.REVIEW, "未声明许可证，必须人工复核")

    normalized = license_id.strip()
    upper = normalized.upper()
    if any(marker in upper for marker in _NONCOMMERCIAL_MARKERS):
        return LicenseEvaluation(
            LicenseDecision.BLOCK,
            "许可证包含非商业限制，不得进入跃科商业交付内容包",
        )
    if normalized in _PERMISSIVE:
        return LicenseEvaluation(
            LicenseDecision.ALLOW,
            "已知宽松许可证；导入时仍必须保留版权与许可证声明",
        )
    return LicenseEvaluation(
        LicenseDecision.REVIEW,
        "许可证不是自动放行白名单，需人工复核兼容性与履约义务",
    )
