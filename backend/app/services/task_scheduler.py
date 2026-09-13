"""任务定时调度接线（D17）：把 Task.schedule_json 注册为 APScheduler 作业。

- interval: {"type":"interval","value":<分钟>}
- cron:     {"type":"cron","value":"分 时 日 月 周"}
触发时建 TaskRun 并后台执行（与"立即执行"同链路）。

此前 scheduler.add_job 从未被调用（定时执行未接线），本模块补齐：
- 启动时 load_all_jobs()
- 任务 create/update/toggle/delete 时 sync/remove
"""
from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from app.core.logging import logger
from app.services import scheduler as sched


def _job_id(task_id: int) -> str:
    return f"task:{task_id}"


async def _run_task_job(task_id: int) -> None:
    from app.core.db import session_scope
    from app.services import task as task_svc

    try:
        async with session_scope() as session:
            tr_id = await task_svc.trigger_run(session, task_id)
            await session.flush()
        logger.info(f"定时触发任务 {task_id} → task_run={tr_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"定时触发任务 {task_id} 失败: {exc}")


def remove_task_job(task_id: int) -> None:
    s = sched.scheduler
    if not s:
        return
    try:
        s.remove_job(_job_id(task_id))
    except Exception:  # noqa: BLE001 不存在即忽略
        pass


def sync_task_job(task_id: int, schedule_json, is_enabled: bool) -> None:
    """按任务当前调度配置，注册（或移除）定时作业。"""
    remove_task_job(task_id)
    if not is_enabled or not schedule_json:
        return
    stype = schedule_json.get("type")
    value = schedule_json.get("value")
    try:
        if stype == "interval":
            sched.add_job(
                _run_task_job, "interval", task_id, job_id=_job_id(task_id), minutes=int(value)
            )
        elif stype == "cron":
            if not sched.scheduler:
                sched.start()
            sched.scheduler.add_job(
                _run_task_job,
                trigger=CronTrigger.from_crontab(str(value)),
                args=[task_id],
                id=_job_id(task_id),
                replace_existing=True,
                misfire_grace_time=30,
            )
        else:
            return
        logger.info(f"已注册定时任务 {task_id} ({stype}={value})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"注册定时任务 {task_id} 失败: {exc}")


async def load_all_jobs() -> None:
    """启动时把库中启用的定时任务全部注册。"""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models import Task

    try:
        async with session_scope() as session:
            rows = (
                await session.execute(select(Task).where(Task.is_deleted.is_(False)))
            ).scalars().all()
        count = 0
        for t in rows:
            if t.schedule_json and t.is_enabled:
                sync_task_job(t.id, t.schedule_json, t.is_enabled)
                count += 1
        logger.info(f"已加载 {count} 个定时任务")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"加载定时任务失败: {exc}")
