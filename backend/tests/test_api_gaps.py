"""API 缺口回归：本轮补齐的端点直接调用路由函数（db_session 内存库，不触 PG）。

覆盖：eval 结果/详情聚合、chat sessions CRUD/消息分页/save-memory、settings、
templates CRUD+apply、tracking-metrics toggle/preview、scripts 趋势/preview-llm。
LLM 依赖统一 monkeypatch，保证纯内存、无外部调用。
"""
from __future__ import annotations

from app.models import EvalCase, EvalResult, Message, Run, Script


def _fail(data) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("error"), dict)
        and isinstance(data["error"].get("code"), str)
    )


async def test_eval_results_list_and_detail(db_session):
    from app.api.eval_ import list_results, result_detail

    c1 = EvalCase(title="t1", script_content="exit 1", expected_level="crit", expected_report_type="error")
    c2 = EvalCase(title="t2", script_content="echo ok", expected_level="ok", expected_report_type="success")
    db_session.add_all([c1, c2])
    await db_session.flush()
    ids = [c1.id, c2.id]
    db_session.add_all(
        [
            EvalResult(run_id="eval_1", case_id=ids[0], actual_level="warn", actual_report_type="error",
                       level_hit=False, report_type_hit=True, score=0.5),
            EvalResult(run_id="eval_1", case_id=ids[1], actual_level="ok", actual_report_type="success",
                       level_hit=True, report_type_hit=True, score=1.0),
        ]
    )
    await db_session.flush()

    data = await list_results(db_session, limit=10)
    assert isinstance(data, dict) and "data" in data
    rows = data["data"]
    assert len(rows) == 2
    assert {"id", "run_id", "case_id", "level_hit", "score"} <= set(rows[0])

    detail = await result_detail(rows[0]["id"], db_session)
    d = detail["data"]
    assert d["aggregate"]["total"] == 2
    assert d["aggregate"]["level_hit"] == 0.5
    assert d["aggregate"]["report_type_hit"] == 1.0
    assert d["radar"]["dimensions"] == ["命中率", "误报率", "报告质量"]
    assert d["radar"]["values"][0] == 0.5
    assert d["radar"]["values"][1] == 0.0


async def test_eval_result_detail_404(db_session):
    from app.api.eval_ import result_detail

    out = await result_detail(999999, db_session)
    assert _fail(out) and out["error"]["code"] == "NOT_FOUND"


async def test_chat_session_crud_and_soft_delete(db_session):
    from app.api.chat_sessions import (
        create_session,
        delete_session,
        list_sessions,
        update_session,
    )

    created = await create_session({"title": "磁盘排查", "model_snapshot": {"model": "qwen-max"}}, db_session)
    sid = created["data"]["session_id"]
    assert sid and created["data"]["title"] == "磁盘排查"

    listed = await list_sessions(db_session)
    assert [s["id"] for s in listed["data"]] == [sid]

    updated = await update_session(sid, {"title": "改名"}, db_session)
    assert updated["data"]["title"] == "改名"

    got = await list_sessions(db_session)
    assert got["data"][0]["title"] == "改名"

    deleted = await delete_session(sid, db_session)
    assert deleted["data"] is True
    # 软删后不在列表中
    assert [s["id"] for s in (await list_sessions(db_session))["data"]] == []


async def test_chat_session_messages_pagination(db_session):
    from app.api.chat_sessions import create_session, session_messages

    created = await create_session({}, db_session)
    sid = created["data"]["session_id"]
    for i in range(3):
        db_session.add(Message(session_id=sid, role="assistant" if i % 2 else "user", content=f"msg{i}"))
    await db_session.flush()

    page = await session_messages(sid, db_session, limit=2, before_id=None)
    assert page["data"]["total"] == 2
    ids = [m["id"] for m in page["data"]["items"]]
    assert ids == sorted(ids)
    assert ids == [2, 3]  # 最新 N 条，升序返回

    before = await session_messages(sid, db_session, limit=50, before_id=ids[-1])
    assert before["data"]["total"] == 2
    assert [m["id"] for m in before["data"]["items"]] == [1, 2]

    empty = await session_messages(sid, db_session, limit=50, before_id=1)
    assert empty["data"]["total"] == 0


async def test_chat_session_save_memory(db_session):
    from app.api.chat_sessions import create_session, save_session_memory

    created = await create_session({}, db_session)
    sid = created["data"]["session_id"]

    bad = await save_session_memory(sid, {"topic": "无摘要"}, db_session)
    assert _fail(bad) and bad["error"]["code"] == "BAD_REQUEST"

    good = await save_session_memory(sid, {"topic": "磁盘告警处置", "summary": "发现根因，已扩容"}, db_session)
    assert not _fail(good)
    assert good["data"]["topic"] == "磁盘告警处置"

    from fastapi import HTTPException

    try:
        await save_session_memory(999999, {"topic": "x", "summary": "y"}, db_session)
        raised = False
    except HTTPException as exc:
        raised = exc.status_code == 404
    assert raised


async def test_settings_get_put_roundtrip(db_session):
    from app.api import settings as api_settings

    before = await api_settings.get_settings(db_session)
    assert "llm_api_key" in before["data"]
    # GET 永不返回明文：未配置时为空串，已配置时为掩码（不依赖本地 .env 是否配 key）
    _key = before["data"]["llm_api_key"]
    assert _key == "" or _key.startswith("******")

    masked = await api_settings.update_settings({"llm_temperature": "0.3"}, db_session)
    assert masked["data"]["llm_temperature"] == "0.3"

    after = await api_settings.get_settings(db_session)
    assert after["data"]["llm_temperature"] == 0.3

    secret = await api_settings.update_settings({"llm_api_key": "sk-test-secret-1234"}, db_session)
    assert secret["data"]["llm_api_key"] == "******1234"
    after_key = await api_settings.get_settings(db_session)
    assert after_key["data"]["llm_api_key"] == "******1234"


async def test_template_crud_and_apply(db_session):
    from app.api.templates import (
        apply_template,
        create_template,
        delete_template,
        get_template,
        list_templates,
        update_template,
    )
    from app.models import Host, Task

    host = Host(name="h1", mcp_endpoint="http://h")
    db_session.add(host)
    script = Script(name="s", content="echo 1")
    db_session.add(script)
    await db_session.flush()

    created = await create_template(
        {"name": "通用巡检", "description": "d", "script_ids": [script.id]}, db_session
    )
    tid = created["data"]["template_id"]

    listed = await list_templates(db_session)
    assert [t["id"] for t in listed["data"]] == [tid]

    detail = await get_template(tid, db_session)
    assert detail["data"]["scripts"][0]["script_id"] == script.id

    replaced = await update_template(tid, {"script_ids": []}, db_session)
    assert replaced["data"] == tid
    assert (await get_template(tid, db_session))["data"]["scripts"] == []

    applied = await apply_template(tid, {"host_id": host.id, "task_name": "巡检A"}, db_session)
    task_id = applied["data"]["task_id"]
    task = await db_session.get(Task, task_id)
    assert task.host_id == host.id and task.name == "巡检A"

    # apply 到不存在的 host 不校验 FK（sqlite 不强制），但应仍能产出任务实例
    applied2 = await apply_template(tid, {"host_id": 1}, db_session)
    assert "data" in applied2 and applied2["data"]["task_id"]

    gone = await delete_template(tid, db_session)
    assert gone["data"] == tid
    assert [t["id"] for t in (await list_templates(db_session))["data"]] == []


async def test_tracking_metric_toggle_disable_preview(db_session):
    from app.api.scripts import create_script, create_tracking_metric, list_tracking_metrics
    from app.api.tracking_metrics import disable_metric, preview_metric, toggle_metric

    created = await create_script({"name": "磁盘", "content": "df -h"}, db_session)
    sid = created["data"]["script_id"]

    tm = await create_tracking_metric(sid, {"name": "used", "extraction_mode": "regex",
                                            "regex_pattern": r"(\d+)%"}, db_session)
    tm_id = tm["data"]["tracking_metric_id"]
    assert tm["data"]["is_enabled"] is True

    got = await list_tracking_metrics(sid, db_session)
    assert [m["id"] for m in got["data"]] == [tm_id]

    off = await toggle_metric(tm_id, db_session)
    assert off["data"]["is_enabled"] is False
    on = await toggle_metric(tm_id, db_session)
    assert on["data"]["is_enabled"] is True

    disabled = await disable_metric(tm_id, db_session)
    assert disabled["data"]["is_enabled"] is False

    # 无 run 时 preview 不应抛异常，返回结构包含 extracted 字段
    pv = await preview_metric(tm_id, db_session)
    assert "data" in pv


async def test_script_preview_llm_monkeypatched(db_session, monkeypatch):
    from app.api.scripts import create_script, preview_llm

    created = await create_script({"name": "s", "content": "df -h", "llm_rule_text": "超过80%警告"}, db_session)
    sid = created["data"]["script_id"]

    async def _fake_gate(script_content, rule_text, raw_result, context_bundle=None):
        return {"level": "warn", "reason": "使用率 92%", "metrics": {"used": 92}}

    monkeypatch.setattr("app.services.judgment.second_gate_llm", _fake_gate)
    out = await preview_llm(sid, {"sample_output": "Filesystem 92% used"}, db_session)
    assert out["data"]["level"] == "warn"
    assert out["data"]["metrics"]["used"] == 92
    assert out["data"]["sample_output"].startswith("Filesystem")


async def test_script_trend_and_trend_summary(db_session, monkeypatch):
    from app.api.scripts import create_script, script_trend, trend_summary
    from app.models import Host

    created = await create_script({"name": "s", "content": "echo 1"}, db_session)
    sid = created["data"]["script_id"]

    host = Host(name="h2", mcp_endpoint="http://h")
    db_session.add(host)
    await db_session.flush()
    db_session.add_all(
        [
            Run(script_id=sid, host_id=host.id, level="ok", report_type="success",
                metrics={"cpu": {"value": 30, "source": "regex"}}),
            Run(script_id=sid, host_id=host.id, level="warn", report_type="success",
                metrics={"cpu": {"value": 85, "source": "regex"}}),
        ]
    )
    await db_session.flush()

    trend = await script_trend(sid, tracking_metric=None, window=30, session=db_session)
    assert trend["data"]["window"] == 30
    assert [h["level"] for h in trend["data"]["history"]] == ["ok", "warn"]
    assert trend["data"]["series"]["cpu"][-1]["value"] == 85

    filtered = await script_trend(sid, tracking_metric="cpu", window=10, session=db_session)
    assert filtered["data"]["series"] == {"cpu": filtered["data"]["series"]["cpu"]}

    monkeypatch.setattr(
        "app.core.llm.get_default_llm",
        lambda: type("F", (), {"ainvoke": _async_mock_ainvoke})(),
    )
    monkeypatch.setattr("app.core.limiter.limiter.try_acquire_llm", lambda: True)
    monkeypatch.setattr("app.core.limiter.limiter.release_llm", lambda: None)
    monkeypatch.setattr("app.core.limiter.limiter.llm_success", lambda: None)
    monkeypatch.setattr("app.core.limiter.limiter.llm_failure", lambda: None)

    summ = await trend_summary(sid, {"window": 5, "tracking_metric": "cpu"}, db_session)
    assert "summary" in summ["data"] and "趋势" in summ["data"]["summary"]


async def _async_mock_ainvoke(self, prompt):
    class _R:
        content = "整体态势稳定，建议关注 cpu 峰值趋势。"
    return _R()


async def test_router_wiring_registered():
    """新端点确实挂载进 main app（OpenAPI 解析后取真实路由路径，不触 DB）。"""
    from app.main import app

    paths = set(app.openapi()["paths"])
    expected = {
        "/eval/results",
        "/eval/results/{result_id}",
        "/eval/run",
        "/chat/sessions",
        "/chat/sessions/{session_id}/messages",
        "/chat/sessions/{session_id}/save-memory",
        "/settings",
        "/templates",
        "/templates/{template_id}/apply",
        "/tracking-metrics/{tm_id}/toggle",
        "/tracking-metrics/{tm_id}/preview",
        "/scripts/{script_id}/trend",
        "/scripts/{script_id}/trend-summary",
        "/scripts/{script_id}/preview-llm",
        "/memory/{type}/{ep_id}",
        "/memory/query",
        "/documents/search",
        "/task-runs/{task_run_id}/cancel",
        "/runs",
        "/stats/overview",
    }
    assert not expected - paths, sorted(expected - paths)
