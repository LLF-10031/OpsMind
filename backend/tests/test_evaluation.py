"""评估体系（O7）：第一关短路 + 第二关真实 LLM（monkeypatch 换 fake，避免真实调用）。"""
from __future__ import annotations

import pytest_asyncio

from app.models import EvalCase
from app.services.evaluation import run_evaluation

FAKE_LEVEL = {"level": "crit", "reason": "df 数值超阈值", "metrics": {"df_used": 92}}


async def _fake_second_gate(script_content, rule_text, raw_result, context_bundle=None):
    return FAKE_LEVEL


@pytest_asyncio.fixture
async def seeded_cases(db_session, monkeypatch):
    def _mk(**kw):
        c = EvalCase(
            title=kw.get("title", "t"),
            description=kw.get("description"),
            script_content=kw.get("script_content", "echo 1"),
            expected_level=kw.get("expected_level", "warn"),
            expected_report_type=kw.get("expected_report_type", "success"),
            ground_truth=kw.get("ground_truth"),
            tags=kw.get("tags"),
        )
        db_session.add(c)
        return c

    c_fail = _mk(title="磁盘高", script_content="exit 1", expected_level="crit", expected_report_type="error")
    c_ok = _mk(title="空输出", script_content="", expected_level="ok", expected_report_type="empty")
    c_success = _mk(title="负载高", script_content="echo load 90", expected_level="crit", expected_report_type="success")
    await db_session.flush()
    ids = [c_fail.id, c_ok.id, c_success.id]
    monkeypatch.setattr("app.services.judgment.second_gate_llm", _fake_second_gate)
    return ids


async def test_eval_first_gate_short_circuit(seeded_cases, db_session):
    """exit≠0/空输出 永远不走 LLM；success 才走（fake 返回 crit）。"""
    results = await run_evaluation(db_session)
    by_case = {r["case"]: r for r in results}
    assert by_case[seeded_cases[0]]["rt_hit"] is True  # error 命中
    assert by_case[seeded_cases[0]]["level_hit"] is False  # 短路→unknown，不等于 crit
    assert by_case[seeded_cases[1]]["rt_hit"] is True  # empty 命中
    assert by_case[seeded_cases[1]]["level_hit"] is False
    assert by_case[seeded_cases[2]]["level_hit"] is True  # success→fake crit 命中
