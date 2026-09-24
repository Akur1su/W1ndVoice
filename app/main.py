from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.ai import AIAnalyzer, extract_provider_error
from app.config import AppConfig
from app.crawler import Crawler
from app.database import Database
from app.errors import format_validation_errors
from app.security import SecretStore, validate_public_url
from app.service import NewsService

BASE_DIR = Path(__file__).resolve().parent
config = AppConfig.from_env()
logging.basicConfig(level=config.log_level)
logger = logging.getLogger("w1ndvoice")

db = Database(config.data_dir / "w1ndvoice.db")
secrets = SecretStore(config.data_dir / "secret.key")
analyzer = AIAnalyzer(db, secrets)
service = NewsService(db, Crawler(), analyzer)
scheduler = AsyncIOScheduler(timezone="UTC")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
asset_version = str(max((BASE_DIR / "static" / name).stat().st_mtime_ns for name in ("app.css", "app.js")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.add_job(
        service.fetch_due,
        "interval",
        minutes=1,
        id="fetch-due",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="W1ndVoice", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class SourceCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    url: Annotated[str, Field(min_length=8, max_length=2000)]
    category: Annotated[str, Field(min_length=1, max_length=50)] = "技术"
    kind: Literal["auto", "rss", "web", "json"] = "auto"
    item_selector: Annotated[str, Field(max_length=300)] = ""
    fetch_interval_hours: Annotated[int, Field(ge=1, le=168)] = 1
    max_pages: Annotated[int, Field(ge=1, le=100)] = 5
    auto_fetch_enabled: bool = True
    auto_analyze: bool = False
    ai_prompt: Annotated[str, Field(max_length=20000)] = ""
    enabled: bool = True


class AISettings(BaseModel):
    base_url: Annotated[str, Field(min_length=8, max_length=2000)]
    model: Annotated[str, Field(min_length=1, max_length=500)]
    api_key: Annotated[str, Field(max_length=10000)] = ""


class ServerSettings(BaseModel):
    port: Annotated[int, Field(ge=1024, le=65535)]


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": format_validation_errors(exc.errors())},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return render_dashboard(request, "home")


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    return render_dashboard(request, "sources")


@app.get("/settings/ai", response_class=HTMLResponse)
async def ai_settings_page(request: Request):
    return render_dashboard(request, "ai")


@app.get("/settings/server", response_class=HTMLResponse)
async def server_settings_page(request: Request):
    return render_dashboard(request, "server")


@app.get("/stream", response_class=HTMLResponse)
async def stream_page(request: Request):
    return render_dashboard(request, "stream")


def render_dashboard(
    request: Request, active_view: Literal["home", "sources", "ai", "server", "stream"]
):
    articles = db.list_articles(limit=100)
    grouped: dict[str, dict] = {}
    for article in articles:
        category = article["category"] or "未分类"
        if category not in grouped:
            grouped[category] = {"name": category, "articles": []}
        grouped[category]["articles"].append(article)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sources": db.list_sources(),
            "articles": articles,
            "article_groups": list(grouped.values()),
            "stats": db.stats(),
            "ai_settings": analyzer.public_settings(),
            "server_settings": public_server_settings(),
            "asset_version": asset_version,
            "active_view": active_view,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", **db.stats()}


@app.get("/api/sources")
async def list_sources():
    return db.list_sources()


@app.post("/api/sources", status_code=201)
async def create_source(payload: SourceCreate):
    try:
        source = payload.model_dump()
        source["url"] = validate_public_url(source["url"])
        return db.add_source(source)
    except (ValueError, sqlite3.IntegrityError) as exc:
        message = "该网址已存在" if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        raise HTTPException(status_code=400, detail=message) from exc


@app.put("/api/sources/{source_id}")
async def update_source(source_id: int, payload: SourceCreate):
    try:
        source = payload.model_dump()
        source["url"] = validate_public_url(source["url"])
        return db.update_source(source_id, source)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="信息源不存在") from exc
    except (ValueError, sqlite3.IntegrityError) as exc:
        message = "该网址已被其他信息源使用" if isinstance(exc, sqlite3.IntegrityError) else str(exc)
        raise HTTPException(status_code=400, detail=message) from exc


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: int):
    if not db.delete_source(source_id):
        raise HTTPException(status_code=404, detail="信息源不存在")
    return {"status": "deleted"}


@app.post("/api/sources/{source_id}/fetch")
async def fetch_source(source_id: int):
    try:
        return await service.fetch_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="信息源不存在") from exc
    except Exception as exc:
        logger.exception("Fetch failed for source %s", source_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/fetch-all")
async def fetch_all():
    return {"results": await service.fetch_all()}


@app.get("/api/articles")
async def list_articles(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    category: str = "",
    q: str = "",
):
    return db.list_articles(limit=limit, category=category, query=q)


@app.get("/api/articles/{article_id}/analysis")
async def get_article_analysis(article_id: int):
    try:
        article = db.get_article(article_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文章不存在") from exc
    return {
        "id": article["id"],
        "title": article["title"],
        "url": article["url"],
        "summary": article["summary"],
        "importance": article["importance"],
        "tags": article["tags"],
        "risk_level": article["risk_level"],
        "ai_status": article["ai_status"],
        "ai_error": article["ai_error"],
        "analyzed_at": article["analyzed_at"],
    }


@app.delete("/api/articles/{article_id}")
async def delete_article(article_id: int):
    if not db.delete_article(article_id):
        raise HTTPException(status_code=404, detail="文章不存在")
    return {"status": "deleted"}


@app.post("/api/articles/{article_id}/analyze")
async def analyze_article(article_id: int):
    try:
        return await analyzer.analyze(article_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文章不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detail = extract_provider_error(exc.response)
        raise HTTPException(
            status_code=502,
            detail=f"AI 接口返回 {exc.response.status_code}：{detail}",
        ) from exc
    except Exception as exc:
        logger.exception("AI analysis failed for article %s", article_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/settings/ai")
async def get_ai_settings():
    return analyzer.public_settings()


@app.put("/api/settings/ai")
async def save_ai_settings(payload: AISettings):
    try:
        analyzer.configure(payload.base_url, payload.model, payload.api_key)
        return analyzer.public_settings()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def public_server_settings() -> dict[str, int | bool]:
    stored_value = db.get_settings().get("server_port")
    try:
        stored_port = int(stored_value) if stored_value is not None else None
    except ValueError:
        stored_port = None
    configured_port = stored_port if stored_port and 1024 <= stored_port <= 65535 else config.port
    environment_override = os.getenv("W1NDVOICE_PORT") is not None
    return {
        "current_port": config.port,
        "configured_port": configured_port,
        "restart_required": configured_port != config.port and not environment_override,
        "environment_override": environment_override,
    }


@app.get("/api/settings/server")
async def get_server_settings():
    return public_server_settings()


@app.put("/api/settings/server")
async def save_server_settings(payload: ServerSettings):
    db.set_settings({"server_port": str(payload.port)})
    return public_server_settings()


def run() -> None:
    uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level.lower())


if __name__ == "__main__":
    run()
