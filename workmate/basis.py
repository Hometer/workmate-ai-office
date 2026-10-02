"""analysis_basis.json 组装（PRD v0.5 F4）：保存本次口径、范围、排除与核对结果。"""
from __future__ import annotations


def build_basis(
    field_mapping: dict,
    amount_mode: str,
    report_week: str | None,
    compare_week: str | None,
    completeness: dict,
    exclusions: list[dict],
    metric_formula_version: str,
    verify_result: dict,
    source_fingerprint: str,
    unit: str = "元",
    compare_empty: bool = False,
    compare_unavailable_reason: str | None = None,
    context: dict | None = None,
    confirmation: dict | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "field_mapping": field_mapping,
        "amount_mode": amount_mode,
        "report_week": report_week,
        "compare_week": compare_week,
        "completeness": completeness,
        "exclusions": exclusions,
        "metric_formula_version": metric_formula_version,
        "verify": verify_result,
        "source_fingerprint": source_fingerprint,
        "unit": unit,
        "compare_empty": compare_empty,
        "compare_unavailable_reason": compare_unavailable_reason,
        **(context or {}),
        "confirmation_mode": (confirmation or {}).get("mode"),
        "inspected_at": (confirmation or {}).get("inspected_at"),
        "confirmed_at": (confirmation or {}).get("confirmed_at"),
    }
