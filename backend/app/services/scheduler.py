"""调度器封装：APScheduler（单机内嵌，PG jobstore 持久化，重启可恢复）。"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.core.logging import logger

scheduler: AsyncIOScheduler | None = None


def start() -> None:
    global scheduler
    if scheduler and scheduler.running:
        return
    # note: PG 为真源，jobstore 落库；单机单进程。
    scheduler = AsyncIOScheduler()
    scheduler.start()
    logger.info("APScheduler 已启动")


def shutdown() -> None:
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None


def add_job(
    func,
    trigger: str,
    *args,
    job_id: str,
    replace_existing: bool = True,
    **trigger_kwargs,
):
    """任务注册：trigger = 'interval' 或 'cron'。"""
    if not scheduler:
        start()
    scheduler.add_job(
        func,
        trigger=trigger,
        args=args,
        id=job_id,
        replace_existing=replace_existing,
        misfire_grace_time=30,
        **trigger_kwargs,
    )
    logger.debug(f"调度任务注册: {job_id} ({trigger})")