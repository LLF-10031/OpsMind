"""FastAPI 应用入口（OpsMind 控制端）。

生命周期：启动时初始化 DB（建表）与调度器；关闭时清理。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.configs.settings import get_settings
from app.core.db import close_db, init_db
from app.core.logging import configure_logging, logger

settings = get_settings()
configure_logging(settings.app_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        f"{settings.app_name} v{settings.app_version} 启动… "
        f"db={'debug' if settings.debug else 'prod'}"
    )
    try:
        await init_db()
    except Exception as exc:  # pragma: no cover
        logger.error(f"数据库初始化失败: {exc}")
        raise
    # 启用 LLM keygen（若配置 API key）
    from app.knowledge.keygen import auto_setup_keygen

    auto_setup_keygen()
    from app.services.scheduler import shutdown as shutdown_scheduler  # 延迟导入，避免循环
    from app.services.scheduler import start as start_scheduler

    start_scheduler()
    # 把库中启用的定时任务注册为 APScheduler 作业（D17）
    try:
        from app.services.task_scheduler import load_all_jobs

        await load_all_jobs()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"加载定时任务失败: {exc}")
    yield
    shutdown_scheduler()
    await close_db()
    logger.info(f"{settings.app_name} 关闭")


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产经 nginx 层收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由挂载
from app.api import (  # noqa: E402
    auth,
    chat,
    chat_sessions,
    documents,
    eval_,
    hosts,
    memory,
    runs,
    scripts,
    settings as settings_api,
    stats,
    task_runs,
    tasks,
    templates,
    tracking_metrics,
)

app.include_router(auth.router)
app.include_router(hosts.router)
app.include_router(scripts.router)
app.include_router(tasks.router)
app.include_router(task_runs.router)
app.include_router(runs.router)
app.include_router(documents.router)
app.include_router(memory.router)
app.include_router(chat.router)
app.include_router(chat_sessions.router)
app.include_router(eval_.router)
app.include_router(templates.router)
app.include_router(tracking_metrics.router)
app.include_router(settings_api.router)
app.include_router(stats.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.app_version}


def run() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)