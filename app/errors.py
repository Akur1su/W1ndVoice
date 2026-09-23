from __future__ import annotations

from typing import Any

FIELD_LABELS = {
    "base_url": "AI Base URL",
    "model": "模型名称",
    "ai_prompt": "信息源分析提示词",
    "api_key": "API Key",
    "name": "名称",
    "url": "网址",
    "category": "分类",
    "fetch_interval_hours": "抓取间隔",
    "max_pages": "主页最大抓取页数",
}


def format_validation_errors(errors: list[dict[str, Any]]) -> str:
    messages: list[str] = []
    for error in errors:
        location = error.get("loc", [])
        field = str(location[-1]) if location else "请求内容"
        label = FIELD_LABELS.get(field, field)
        error_type = error.get("type", "")
        context = error.get("ctx") or {}
        if error_type == "missing":
            message = f"请填写{label}"
        elif error_type == "string_too_short":
            message = f"{label}至少需要 {context.get('min_length', 1)} 个字符"
        elif error_type == "string_too_long":
            message = f"{label}不能超过 {context.get('max_length')} 个字符"
        elif error_type == "greater_than_equal":
            message = f"{label}不能小于 {context.get('ge')}"
        elif error_type == "less_than_equal":
            message = f"{label}不能大于 {context.get('le')}"
        else:
            message = f"{label}格式不正确：{error.get('msg', '请检查输入')}"
        messages.append(message)
    return "；".join(messages) or "请求内容格式不正确"
