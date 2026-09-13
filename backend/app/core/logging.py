"""日志与 trace_id（contextvars 跨协程传播）。"""
from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import loguru
from loguru import logger

_trace_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    return _trace_var.get()


def set_trace_id(tid: str) -> None:
    _trace_var.set(tid)


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:16]
    set_trace_id(tid)
    return tid


class InterceptHandler(logging.Handler):
    """把标准 logging 转发到 loguru，保持 trace 前缀一致。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(app_name: str = "OpsMind", remove: bool = True) -> None:
    if remove:
        logger.remove()
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | <cyan>{extra[trace]}</cyan> | "
            "{message}"
        ),
        colorize=True,
    )
    logger.configure(extra={"trace": "startup"})

    def _patched_log(record: "loguru.Record") -> None:
        record["extra"]["trace"] = get_trace_id() or "-"

    logger.configure(patcher=_patched_log)

    # 桥接标准 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    logger.debug(f"{app_name} 日志系统已初始化")