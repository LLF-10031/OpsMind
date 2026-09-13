"""ORM 模型（SQLAlchemy + pgvector）。对齐 03-数据库设计。

Phase 0 先落地执行链路核心表；知识库/记忆/评估表在 Phase 3/4 扩展。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.db import Base

# 主键：PG 用 BIGINT，SQLite（测试/本地降级）用 Integer，保证自增可用
BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


def _dt() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class Host(Base):
    __tablename__ = "host"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    mcp_endpoint: Mapped[str] = mapped_column(String(255))  # http://localhost:8003
    auth_key: Mapped[str | None] = mapped_column(String(255))  # 加密
    host_info: Mapped[dict | None] = mapped_column(JSON)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Script(Base):
    __tablename__ = "script"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    shell: Mapped[str] = mapped_column(String(20), default="bash")
    interpreter: Mapped[str] = mapped_column(String(20), default="bash")  # bash|python3 白名单
    timeout: Mapped[int] = mapped_column(Integer, default=30)
    params_json: Mapped[dict | None] = mapped_column(JSON)
    llm_rule_text: Mapped[str | None] = mapped_column(Text)  # 判定规则文本
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class Template(Base):
    __tablename__ = "template"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_json: Mapped[dict | None] = mapped_column(JSON)  # {type: interval|cron, value}
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base):
    __tablename__ = "task"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("host.id"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_json: Mapped[dict | None] = mapped_column(JSON)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskScript(Base):
    __tablename__ = "task_script"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("task.id"), nullable=False)
    script_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("script.id"), nullable=False)
    script_version_at_bind: Mapped[int] = mapped_column(Integer, default=1)
    params_override: Mapped[dict | None] = mapped_column(JSON)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("task_id", "script_id", name="uq_task_script"),)


class TemplateScript(Base):
    """模板→脚本关联（03 2.6）：模板 apply 时生成 Task+TaskScript。"""
    __tablename__ = "template_script"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id"), nullable=False)
    script_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("script.id"), nullable=False)
    script_version_at_bind: Mapped[int] = mapped_column(Integer, default=1)
    params_override: Mapped[dict | None] = mapped_column(JSON)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("template_id", "script_id", name="uq_template_script"),)


class TaskRun(Base):
    __tablename__ = "task_run"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("task.id"))  # 试跑(test)可空
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # scheduled|manual|test
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON)  # 背景包快照（D47）
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_task_run_task_start", "task_id", "started_at"),)


class Run(Base):
    """脚本×主机快照；报告 1:1 挂靠。"""
    __tablename__ = "run"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    task_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("task_run.id"))
    script_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("script.id"))
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("host.id"))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    output_path: Mapped[str | None] = mapped_column(String(500))   # R-1 磁盘存档
    output_size: Mapped[int] = mapped_column(Integer, default=0)
    stdout_preview: Mapped[str | None] = mapped_column(Text)        # 首 N 行
    report_type: Mapped[str] = mapped_column(String(20), default="success")
    level: Mapped[str] = mapped_column(String(20), default="unknown")
    llm_judgment: Mapped[dict | None] = mapped_column(JSON)         # {level, reason, metrics?}
    metrics: Mapped[dict | None] = mapped_column(JSON)              # 跟踪指标 {cpu: {value, source: llm|regex}}（03 2.10）
    degradation_notes: Mapped[list | None] = mapped_column(JSON)    # D38 透明
    attempts: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)
    __table_args__ = (
        Index("ix_run_tr", "task_run_id"),
        Index("ix_run_script_host_time", "script_id", "host_id", "created_at"),
    )


class Report(Base):
    __tablename__ = "report"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("run.id"), unique=True, nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(20), default="success")
    meta: Mapped[dict | None] = mapped_column(JSON)          # 头部元信息行
    ai_content: Mapped[str | None] = mapped_column(Text)     # ③分析/失败诊断/固定文案
    ai_source: Mapped[str] = mapped_column(String(20), default="none")
    ai_status: Mapped[str] = mapped_column(String(20), default="none")
    annotations: Mapped[list | None] = mapped_column(JSON)   # O4 标注清单
    banner: Mapped[str | None] = mapped_column(String(200))


class TrackingMetric(Base):
    __tablename__ = "tracking_metric"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("script.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100))
    extraction_mode: Mapped[str] = mapped_column(String(20), default="llm_regex")
    regex_pattern: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(50))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SettingsKV(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class Session(Base):
    """chat 会话（03 2.17，D50：chat 落库）。"""
    __tablename__ = "session"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    model_snapshot: Mapped[dict | None] = mapped_column(JSON)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)
    __table_args__ = (Index("ix_session_active", "last_active_at"),)


class Message(Base):
    """会话消息（03 2.18）：user/assistant/tool。"""
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("session.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    citations: Mapped[list | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)
    __table_args__ = (Index("ix_message_session_time", "session_id", "created_at"),)


class User(Base):
    """admin 单账号（D48 极简）。"""
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # bcrypt


class Document(Base):
    """知识库文档（D40）。"""
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    file_type: Mapped[str] = mapped_column(String(10), default="md")
    raw_content: Mapped[str | None] = mapped_column(Text)
    normalized_md: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class Unit(Base):
    """知识单元（规范化产物，原文保真）。"""
    __tablename__ = "unit"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BIGINT_PK, ForeignKey("document.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="manual")
    value: Mapped[str] = mapped_column(Text)
    parent_context: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list | None] = mapped_column(JSON)
    step_no: Mapped[int | None] = mapped_column(Integer)
    original_range: Mapped[dict | None] = mapped_column(JSON)
    section_id: Mapped[str | None] = mapped_column(String(50))


class KeyIndex(Base):
    """检索索引行（key 打平行，向量+BM25）。"""
    __tablename__ = "key_index"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(BIGINT_PK, ForeignKey("unit.id"), nullable=False)
    key_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class Episodic(Base):
    """片段记忆（D44）：历史事件。"""
    __tablename__ = "episodic"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list | None] = mapped_column(JSON)
    key_params: Mapped[dict | None] = mapped_column(JSON)
    manually_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class SemanticItemModel(Base):
    """语义记忆（D44）：长期经验规律。"""
    __tablename__ = "semantic"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(Text)
    trigger_condition: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class EvalCase(Base):
    """评估案例（O7）：注入故障场景，含 ground truth。"""
    __tablename__ = "eval_case"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    script_content: Mapped[str] = mapped_column(Text)
    expected_level: Mapped[str] = mapped_column(String(20))
    expected_report_type: Mapped[str] = mapped_column(String(20))
    ground_truth: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


class EvalResult(Base):
    """评估运行结果（O7）。"""
    __tablename__ = "eval_result"
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(50))
    case_id: Mapped[int] = mapped_column(BIGINT_PK, ForeignKey("eval_case.id"), nullable=False)
    actual_level: Mapped[str] = mapped_column(String(20))
    actual_report_type: Mapped[str] = mapped_column(String(20))
    level_hit: Mapped[bool] = mapped_column(Boolean)
    report_type_hit: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_dt)


def register_models() -> None:
    _ = [
        Host, Script, Template, TemplateScript, Task, TaskScript, TaskRun, Run, Report,
        TrackingMetric, SettingsKV, User, Document, Unit, KeyIndex,
        Episodic, SemanticItemModel, EvalCase, EvalResult, Session, Message,
    ]
