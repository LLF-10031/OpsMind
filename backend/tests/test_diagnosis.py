"""多 Agent 诊断测试（D38）：黑板契约 + 图并行写入 + 幂等落库 + 异常判定。

全程离线：注入 fake Planner/Reviewer/Collect，不调真实 LLM / 目标机。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.diagnosis import graph as diag_graph
from app.diagnosis.blackboard import (
    DiagnosticState,
    all_evidence_empty,
    slot_for,
    validate_contract,
)
from app.diagnosis.service import diagnose_task_run, is_anomalous
from app.models import Host, Task, TaskRun
from app.services import execution


# --- fake 依赖 ---
async def fake_plan(state: DiagnosticState) -> list[dict]:
    return [
        {"text": "日志有报错", "kind": "log"},
        {"text": "内存偏高", "kind": "metric"},
        {"text": "近期变更", "kind": "change"},
    ]


async def fake_review(state: DiagnosticState) -> list[dict]:
    return [{"text": "疑似服务启动失败", "confidence": 0.7, "evidence_refs": ["logs", "metrics"]}]


async def fake_collect(executor: str, endpoint: str, auth_key: str, timeout: float) -> dict:
    return {"executor": executor, "exit_code": 0, "stdout": f"{executor} probe ok", "duration_ms": 5}


async def fake_collect_error(executor: str, endpoint: str, auth_key: str, timeout: float) -> dict:
    return {"executor": executor, "error": "host unreachable"}


@pytest.fixture
def stub_agents(monkeypatch):
    monkeypatch.setattr(diag_graph, "PLANNER_FN", fake_plan)
    monkeypatch.setattr(diag_graph, "REVIEWER_FN", fake_review)
    monkeypatch.setattr(diag_graph, "COLLECT_FN", fake_collect)


# --- 契约 ---
def test_contract_slot_mapping():
    assert slot_for("log") == "evidence_logs"
    assert slot_for("metric") == "evidence_metrics"
    assert slot_for("change") == "evidence_changes"


def test_contract_conclusion_requires_evidence():
    st = DiagnosticState(conclusions=[{"text": "x", "confidence": 0.9}])
    assert all_evidence_empty(st)
    problems = validate_contract(st)
    assert any("无任何证据" in p for p in problems)


def test_contract_rejects_bad_kind():
    st = DiagnosticState(hypothesis=[{"text": "x", "kind": "network"}])
    assert any("非法" in p for p in validate_contract(st))


# --- 图：并行各写各格子 ---
@pytest.mark.asyncio
async def test_graph_parallel_blackboard(stub_agents):
    state = DiagnosticState(task_run_id=1, host_id=1, endpoint="http://x", auth_key="")
    raw = await diag_graph.get_graph().ainvoke(state)
    final = DiagnosticState(**raw)
    assert len(final.hypothesis) == 3
    # 三个 executor 各写一格，互不覆盖
    assert final.evidence_logs and final.evidence_logs[0]["executor"] == "log"
    assert final.evidence_metrics and final.evidence_metrics[0]["executor"] == "metric"
    assert final.evidence_changes and final.evidence_changes[0]["executor"] == "change"
    assert final.conclusions and final.conclusions[0]["confidence"] == 0.7
    assert validate_contract(final) == []


@pytest.mark.asyncio
async def test_graph_no_evidence_no_conclusion(stub_agents, monkeypatch):
    monkeypatch.setattr(diag_graph, "COLLECT_FN", fake_collect_error)
    state = DiagnosticState(task_run_id=2, host_id=1, endpoint="http://x", auth_key="")
    raw = await diag_graph.get_graph().ainvoke(state)
    final = DiagnosticState(**raw)
    assert all_evidence_empty(final)
    assert final.conclusions == []
    assert "证据不足" in final.flags


# --- 异常判定 ---
def test_is_anomalous():
    assert is_anomalous([("success", "crit")]) is True
    assert is_anomalous([("error", "unknown")]) is True
    assert is_anomalous([("timeout", "ok")]) is True
    assert is_anomalous([("host_unreachable", "unknown")]) is True
    assert is_anomalous([("success", "ok"), ("empty", "warn")]) is False


# --- 服务：幂等落库 ---
@pytest_asyncio.fixture
async def diag_env(tmp_path, monkeypatch, stub_agents) -> dict:
    db_file = tmp_path / "diag_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    TestSession = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(execution, "SESSION_FACTORY", lambda: TestSession())

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as s:
        h = Host(name="h1", mcp_endpoint="http://localhost:8003")
        s.add(h)
        await s.flush()
        task = Task(host_id=h.id, name="t1", is_enabled=True)
        s.add(task)
        await s.flush()
        tr = TaskRun(task_id=task.id, trigger="manual", status="DONE")
        s.add(tr)
        await s.flush()
        tr_id, host_id = tr.id, h.id
        await s.commit()

    yield {"tr_id": tr_id, "host_id": host_id, "factory": TestSession}
    await engine.dispose()


@pytest.mark.asyncio
async def test_diagnose_persist_and_idempotent(diag_env):
    tr_id, host_id = diag_env["tr_id"], diag_env["host_id"]
    payload = await diagnose_task_run(tr_id, host_id)
    assert payload is not None
    assert payload["status"] == "done"
    assert payload["conclusions"]

    async with diag_env["factory"]() as s:
        tr = await s.get(TaskRun, tr_id)
        assert tr.diagnosis_json is not None
        assert tr.diagnosis_json["task_run_id"] == tr_id

    # 第二次：已落库 → 跳过
    assert await diagnose_task_run(tr_id, host_id) is None


@pytest.mark.asyncio
async def test_diagnose_failure_no_persist(diag_env, monkeypatch):
    tr_id, host_id = diag_env["tr_id"], diag_env["host_id"]

    async def boom(state):
        raise RuntimeError("boom")

    monkeypatch.setattr(diag_graph, "PLANNER_FN", boom)
    assert await diagnose_task_run(tr_id, host_id) is None
    async with diag_env["factory"]() as s:
        tr = await s.get(TaskRun, tr_id)
        assert tr.diagnosis_json is None  # 失败不落库，允许重试
