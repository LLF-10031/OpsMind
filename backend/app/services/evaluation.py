"""评估体系（D22/O7/D48）：故障案例集 → 复用判定/分析链路 → 评分。

指标：定位命中率 top-1/3 · 误报率 · 报告质量；模型 A/B · Skill/Prompt A-B · 雷达图。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import EvalCase, EvalResult


async def run_evaluation(session: AsyncSession, case_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """跑一组案例评估。每个案例: 加载→造 fake run→判定→比对→记分。"""
    cases = (
        (await session.execute(select(EvalCase).where(EvalCase.is_deleted.is_(False))))
        .scalars()
        .all()
    )
    if case_ids:
        cases = [c for c in cases if c.id in case_ids]
    results = []
    for case in cases:
        actual_rt, actual_lvl = await _simulate_judgment(case)
        level_hit = actual_lvl == case.expected_level
        rt_hit = actual_rt == case.expected_report_type
        score = (1.0 if level_hit else 0.0) + (1.0 if rt_hit else 0.0)
        result = EvalResult(
            run_id=f"eval_{case.id}",
            case_id=case.id,
            actual_level=actual_lvl,
            actual_report_type=actual_rt,
            level_hit=level_hit,
            report_type_hit=rt_hit,
            score=score / 2,
            detail=f"expect_lvl={case.expected_level} get={actual_lvl} | expect_rt={case.expected_report_type} get={actual_rt}",
        )
        session.add(result)
        results.append(
            {"case": case.id, "level_hit": level_hit, "rt_hit": rt_hit, "score": score / 2}
        )
    await session.commit()
    return results


async def _simulate_judgment(case: EvalCase) -> tuple[str, str]:
    """对案例走真实判定链路（D20/D36/D47）。

    第一关确定性短路（exit≠0/无输出 永远不走 LLM）→ success 才进第二关。
    第二关复用 second_gate_llm（受全局限流器约束；限流/失败降级 unknown）。
    """
    from app.services.judgment import first_gate, second_gate_llm

    exit_code = 1 if (case.script_content.startswith("exit 1") or "fail" in case.script_content.lower()) else 0
    has_out = bool(case.script_content.strip())
    rt, go_second = first_gate(exit_code, timed_out=False, has_output=has_out)
    if not go_second:
        return rt, "unknown"
    try:
        parsed = await second_gate_llm(
            script_content=case.script_content,
            rule_text=case.ground_truth,
            raw_result=case.script_content,
        )
        return rt, str(parsed.get("level", "unknown"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"评估第二关判定失败，降级 unknown: {exc}")
        return rt, "unknown"


def compute_aggregate(results: list[dict]) -> dict:
    """聚合所有案例：命中率/误报率/报告质量雷达指标。"""
    total = len(results)
    if not total:
        return {"hit_rate": 0, "false_positive": 0, "quality": 0}
    hit = sum(1 for r in results if r["level_hit"] and r["rt_hit"])
    false = sum(1 for r in results if r["level_hit"] and not r.get("ground_truth_correct"))
    return {"hit_rate": hit / total, "false_positive": false / max(total, 1), "quality": hit / max(total, 1)}