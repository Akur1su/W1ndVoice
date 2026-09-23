from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.database import Database
from app.security import SecretStore

DEFAULT_PROMPT = """你是一名严谨的技术情报分析员。请根据原文：
1. 用中文写 120-250 字摘要，不添加原文没有的事实；
2. 给出重要度 0-100；
3. 提取最多 6 个关键词；
4. 若是安全漏洞，判断风险级别 critical/high/medium/low；其他内容填 none。
只返回 JSON：{"summary":"...","importance":80,"tags":["..."],"risk_level":"none"}"""


class AIAnalyzer:
    def __init__(self, db: Database, secrets: SecretStore) -> None:
        self.db = db
        self.secrets = secrets

    def public_settings(self) -> dict[str, Any]:
        settings = self.db.get_settings()
        encrypted = settings.get("ai_api_key", "")
        return {
            "base_url": settings.get("ai_base_url", "https://api.openai.com/v1"),
            "model": settings.get("ai_model", "gpt-4.1-mini"),
            "has_api_key": bool(self.secrets.decrypt(encrypted)),
        }

    def configure(self, base_url: str, model: str, api_key: str = "") -> None:
        base_url = validate_endpoint_url(base_url)
        values = {
            "ai_base_url": base_url,
            "ai_model": model.strip(),
        }
        if api_key:
            values["ai_api_key"] = self.secrets.encrypt(api_key.strip())
        self.db.set_settings(values)

    async def analyze(self, article_id: int) -> dict[str, Any]:
        article = self.db.get_article(article_id)
        settings = self.db.get_settings()
        api_key = self.secrets.decrypt(settings.get("ai_api_key", ""))
        if not api_key:
            raise ValueError("请先在 AI 设置中填写 API Key")

        base_url = validate_endpoint_url(
            settings.get("ai_base_url", "https://api.openai.com/v1")
        )
        model = settings.get("ai_model", "gpt-4.1-mini")
        source = self.db.get_source(article["source_id"])
        prompt = build_system_prompt(source.get("ai_prompt", "") or DEFAULT_PROMPT)
        content = article["content"][:20_000]
        self.db.mark_ai_running(article_id)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": prompt},
                            {
                                "role": "user",
                                "content": f"标题：{article['title']}\n来源正文：\n{content}",
                            },
                        ],
                    },
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
            analysis = normalize_analysis(parse_json(raw))
            self.db.save_analysis(article_id, analysis)
            return analysis
        except httpx.HTTPStatusError as exc:
            message = extract_provider_error(exc.response)
            self.db.save_ai_error(article_id, f"HTTP {exc.response.status_code}: {message}")
            raise
        except Exception as exc:
            self.db.save_ai_error(article_id, str(exc))
            raise


def parse_json(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return json.loads(cleaned)


def validate_endpoint_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("AI Base URL 必须是完整的 http/https 地址")
    if parsed.username or parsed.password:
        raise ValueError("AI Base URL 不能包含用户名或密码")
    return parsed.geturl().rstrip("/")


def build_system_prompt(prompt: str) -> str:
    base = prompt.strip() or DEFAULT_PROMPT
    return (
        f"{base}\n\n"
        "输出格式要求：必须只返回一个有效的 json 对象，不要使用 Markdown 代码块。"
        "对象必须包含 summary、importance、tags、risk_level 四个字段。"
    )


def extract_provider_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:500] or "供应商未返回错误详情"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:500]
    if isinstance(error, str):
        return error[:500]
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])[:500]
    return "供应商未返回错误详情"


def normalize_analysis(value: dict[str, Any]) -> dict[str, Any]:
    summary = str(value.get("summary", "")).strip()
    if not summary:
        raise ValueError("AI 返回结果缺少 summary")
    try:
        importance = min(100, max(0, int(value.get("importance", 50))))
    except (TypeError, ValueError):
        importance = 50
    tags = [str(tag).strip()[:40] for tag in value.get("tags", []) if str(tag).strip()][:6]
    risk = str(value.get("risk_level", "none")).lower()
    if risk not in {"critical", "high", "medium", "low", "none"}:
        risk = "none"
    return {"summary": summary[:2000], "importance": importance, "tags": tags, "risk_level": risk}
