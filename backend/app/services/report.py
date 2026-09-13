"""报告③分析与 SSE（D47/D48/D18）。

- 报告异步：②元信息行先出（确定性），③LLM 分析并行、受限流器；
- 仅 success+warn 走③分析；crit/error 走批次联动（Phase 3 接）；
  失败诊断（error 读 stderr）在此露地毯；
- 输出经敏感过滤（D48）；
- O4 校验应用到③内容。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.configs.settings import settings
from app.core.db import SessionLocal
from app.core.exceptions import OpsMindError
from app.core.limiter import limiter
from app.core.llm import get_default_llm
from app.core.logging import logger
from app.models import Report, Run
from app.services.validation import run_pipeline

# 敏感信息打码（D48 横切点：所有生成文本出口）
SENSITIVE_PATTERNS = [  # 简单实现：key/password 打码；生产扩展为规则引擎
    ("sk-[A-Za-z0-9]{8,}", "sk-****"),
    (r"password[\"\']?\s*[:=]\s*[\"\']?([^,\"'}\s]+)", r"password=****"),
    (r"token[\"\']?\s*[:=]\s*[\"\']?([^,\"'}\s]+)", r"token=****"),
]


def mask_sensitive(text: str) -> str:
    import re

    for pat, repl in SENSITIVE_PATTERNS:
        text = re.sub(pat, repl, text)
    return text


async def analyze_run(run_id: int, script_content: str, rule_text: str | None, raw_stdout: str, context: dict | None = None) -> None:
    """③ LLM 分析（仅 success+warn 或 error 失败诊断路径由调用方选择）。"""
    async with SessionLocal() as session:
        rep = (await session.execute(select(Report).where(Report.run_id == run_id))).scalars().first()
        run = await session.get(Run, run_id)
        if not rep or not run:
            return
        if rep.ai_status in ("done", "failed"):
            return

        rep.ai_status = "analyzing"
        await session.commit()
        prompt = f"你是运维分析器。脚本内容 + 规则文本 + 输出如下，产出简洁分析（现象→怀疑原因→证据→建议）。\n【脚本】{script_content}\n【规则】{rule_text or '无'}\n【背景】{context or {}}\n【输出】{raw_stdout[:4000]}\n"
        try:
            if not limiter.try_acquire_llm():
                raise OpsMindError("限流繁忙")
            llm = get_default_llm()
            resp = await llm.ainvoke(prompt)
            limiter.llm_success()
            ai = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as exc:
            limiter.llm_failure()
            logger.warning(f"③分析失败 run={run_id}: {exc}")
            ai = "（AI 分析暂不可用）"
            rep.ai_status = "failed"
        finally:
            limiter.release_llm()

        ai = mask_sensitive(str(ai))          # D48
        annotations = run_pipeline(ai, run.level, has_error_keyword="ERROR" in (raw_stdout or "").upper())
        rep.ai_content = ai
        rep.ai_source = "ai_analysis"
        rep.ai_status = "done"
        rep.annotations = annotations
        banner = next((a["message"] for a in annotations if a["rule"] == "banner"), None)
        rep.banner = banner
        await session.commit()
        logger.info(f"③分析完成 run={run_id}")


async def schedule_analysis(run_ids: list[int], sem: asyncio.Semaphore | None = None) -> None:
    """并行调度多个 run 的③分析（受限流器 + 可选信号量）。"""
    sem = sem or asyncio.Semaphore(settings.report_gen_concurrency)
    async def _one(rid: int):
        async with sem:
            async with SessionLocal() as s:
                run = await s.get(Run, rid)
                if not run:
                    return
                sc = None
                from app.models import Script
                sc = await s.get(Script, run.script_id)
                content = sc.content if sc else ""
            await analyze_run(rid, content, (sc.llm_rule_text if sc else None), run.stdout_preview or "")

    await asyncio.gather(*[_one(rid) for rid in run_ids])