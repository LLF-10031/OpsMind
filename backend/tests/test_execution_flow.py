"""执行引擎端到端测试（D13/D17/D36/D47）——用 fake EXEC_RUNNER 注入 + 内存库。

用例 test_execute_task_run_flow：触发执行 → 第一关/第二关判定 → Run+Report 落库 → 批次 DONE。
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base
from app.models import Host, Report, Run, Script, Task, TaskRun, TaskScript
from app.services import execution


async def fake_exec_runner(endpoint, tool, args, auth_key, timeout):
    content = args.get("content", "")
    if "fail_script" in content:
        return {"exit_code": 1, "stdout": "", "stderr": "connection refused", "duration_ms": 20, "timed_out": False}
    if "empty_script" in content:
        return {"exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 10, "timed_out": False}
    return {"exit_code": 0, "stdout": "cpu usage 5%\nhealthy", "stderr": "", "duration_ms": 15, "timed_out": False}


async def fake_second_gate(script_content, rule_text, raw_result, context_bundle=None):
    return {"level": "ok", "reason": "测试：输出正常", "metrics": {}}


def _fake_write_output(run_id, stdout, stderr, task_run_id, tmp_path: Path):
    d = tmp_path / str(task_run_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{run_id}.out"
    p.write_text("# stdout\n" + stdout + "\n# stderr\n" + stderr, encoding="utf-8")
    return str(p), p.stat().st_size


@pytest_asyncio.fixture
async def exec_env(tmp_path, monkeypatch) -> dict:
    db_file = tmp_path / "opsmind_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    def _factory():
        return TestSession()

    monkeypatch.setattr(execution, "SESSION_FACTORY", _factory)
    monkeypatch.setattr(execution, "EXEC_RUNNER", fake_exec_runner)
    monkeypatch.setattr(execution, "second_gate_llm", fake_second_gate)
    monkeypatch.setattr(
        execution,
        "_write_output",
        lambda run_id, stdout, stderr, tr_id: _fake_write_output(run_id, stdout, stderr, tr_id, tmp_path),
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as s:
        h = Host(name="h1", mcp_endpoint="http://localhost:8003")
        s1 = Script(name="s-normal", content="echo ok", interpreter="bash", llm_rule_text="正常即 ok")
        s2 = Script(name="s-fail", content="fail_script", interpreter="bash")
        s3 = Script(name="s-empty", content="empty_script", interpreter="bash")
        s.add_all([h, s1, s2, s3])
        await s.flush()
        task = Task(host_id=h.id, name="t1", is_enabled=True)
        s.add(task)
        await s.flush()
        s.add_all(
            [
                TaskScript(task_id=task.id, script_id=s1.id, params_override=None),
                TaskScript(task_id=task.id, script_id=s2.id, params_override=None),
                TaskScript(task_id=task.id, script_id=s3.id, params_override=None),
            ]
        )
        tr = TaskRun(
            task_id=task.id,
            trigger="manual",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        s.add(tr)
        await s.flush()
        tr_id = tr.id
        await s.commit()

    yield {"tr_id": tr_id, "factory": TestSession, "engine": engine}
    await engine.dispose()


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_execute_task_run_flow(exec_env):
    tr_id = exec_env["tr_id"]
    factory = exec_env["factory"]

    result = await execution.execute_task_run(tr_id)
    assert result["ok"] is True
    assert result["runs"] == 3
    assert result["summary"] == {"success": 1, "error": 1, "empty": 1}

    async with factory() as s:
        runs = (await s.execute(select(Run).where(Run.task_run_id == tr_id))).scalars().all()
        assert len(runs) == 3
        by_name: dict[str, Run] = {}
        for r in runs:
            sc = await s.get(Script, r.script_id)
            if sc:
                by_name[sc.name] = r
        assert by_name["s-normal"].report_type == "success"
        assert by_name["s-normal"].level == "ok"
        assert by_name["s-fail"].report_type == "error"
        assert by_name["s-empty"].report_type == "empty"

        reps = (await s.execute(select(Report))).scalars().all()
        assert len(reps) == 3

        tr = await s.get(TaskRun, tr_id)
        assert tr.status == "DONE"