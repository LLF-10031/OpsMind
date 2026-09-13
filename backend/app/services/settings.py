"""系统设置中心（03 2.16 / 05 十二）：持久化 SettingsKV + 运行时覆盖单例。

- GET：DB 覆盖值 merged 进单例默认值视图；所有 *_api_key 掩码不回传明文。
- PUT：upsert SettingsKV + apply_overrides 立即生效（无需重启）；掩码占位不覆盖。
- lifespan 启动时 load_from_db 应用一次持久化覆盖。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import SettingsKV

# 设置键 → 单例 Settings 字段名（仅这些运行时生效）
FIELD_MAP: dict[str, str] = {
    # 对话/分析
    "llm_api_key": "openai_api_key",
    "llm_base_url": "openai_base_url",
    "llm_model": "openai_model",
    "llm_temperature": "llm_temperature",
    # 轻任务/文档处理（压缩/摘要/记忆提炼/图片解析）
    "light_model": "light_model",
    "docproc_api_key": "docproc_api_key",
    "docproc_base_url": "docproc_base_url",
    "docproc_model": "docproc_model",
    # 向量 embedding
    "embedding_api_key": "embedding_api_key",
    "embedding_base_url": "embedding_base_url",
    "embedding_model": "embedding_model",
}
# 仅存 DB、不回写单例的键（无对应字段，安全起见原样保留）
DB_ONLY_KEYS = {
    "llm_provider",
    "default_document_ids",
    "default_analysis_model",
    "pipeline_config",
    "injection_detection_enabled",
}


def _secret_mask(value: str) -> str:
    if not value:
        return ""
    return "******" + value[-4:] if len(value) > 4 else "******"


def _coerce(value: Any, current: Any) -> Any:
    if value is None:
        return None
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int):
        return int(float(value))
    if isinstance(current, float):
        return float(value)
    if isinstance(current, (list, dict)):
        return value
    return value


def apply_overrides(payload: dict[str, Any]) -> None:
    """将设置覆盖到运行时单例（立即生效）。"""
    from app.configs.settings import get_settings

    s = get_settings()
    for key, value in payload.items():
        fname = FIELD_MAP.get(key)
        if not fname or not hasattr(s, fname):
            continue
        try:
            setattr(s, fname, _coerce(value, getattr(s, fname)))
        except (TypeError, ValueError) as exc:
            logger.warning(f"设置 {key} 覆盖失败: {exc}")


def _encode(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


def _decode(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


async def get_all_settings(session: AsyncSession) -> dict[str, Any]:
    """返回当前生效设置视图（单例默认 + DB 覆盖合并）。"""
    from app.configs.settings import get_settings

    s = get_settings()
    out: dict[str, Any] = {}
    for key, fname in FIELD_MAP.items():
        if hasattr(s, fname):
            out[key] = getattr(s, fname)
        else:
            out[key] = None
    rows = (
        (await session.execute(select(SettingsKV)))
        .scalars()
        .all()
    )
    for row in rows:
        out.setdefault(row.key, _decode(row.value))
    for key in list(out.keys()):
        if _is_secret_field(key):
            val = out[key] or ""
            out[key] = _secret_mask(val) if isinstance(val, str) else "******"
    return out


def _looks_masked(value: Any) -> bool:
    """前端回传的掩码占位（******xxxx）不落库、不覆盖。"""
    return isinstance(value, str) and value.startswith("******")


async def update_settings(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """批量 upsert 设置并使其运行时生效（含密钥；即时生效无需重启）。"""
    from datetime import datetime, timezone

    applied: dict[str, Any] = {}
    for key, value in payload.items():
        if _looks_masked(value):
            continue  # 掩码占位：保留库中原值
        row = await session.get(SettingsKV, key)
        if row is None:
            row = SettingsKV(key=key, value=_encode(value))
            session.add(row)
        else:
            row.value = _encode(value)
            row.updated_at = datetime.now(timezone.utc)
        applied[key] = value
    await session.flush()
    apply_overrides(applied)
    masked = {k: (_secret_mask(v) if _is_secret_field(k) else v) for k, v in applied.items()}
    return masked


def _is_secret_field(key: str) -> bool:
    return key.endswith("_api_key") or key == "llm_api_key"


async def load_from_db(session: AsyncSession) -> None:
    """启动时应用持久化设置（幂等，失败不阻塞启动）。"""
    try:
        rows = (await session.execute(select(SettingsKV))).scalars().all()
        payload = {r.key: _decode(r.value) for r in rows}
        apply_overrides(payload)
        logger.info(f"已加载 {len(payload)} 条持久化设置")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"加载持久化设置失败: {exc}")
