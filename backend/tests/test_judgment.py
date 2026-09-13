"""判定两关模型单测（D20/D36/D47）。

不依赖 MCP/LLM，覆盖第一关确定性短路 + report_type×level 正交语义。
"""
import pytest

from app.services.judgment import LEVELS, REPORT_TYPES, first_gate


@pytest.mark.parametrize(
    "exit_code,timed_out,has_output,expected,go_llm",
    [
        (0, False, True, "success", True),     # 成功且有效 → 第二关
        (0, False, False, "empty", False),     # 空输出 → 不调 LLM
        (1, False, True, "error", False),      # exit≠0 → error
        (0, True, True, "timeout", False),     # 超时 → timeout
        (None, False, True, "host_unreachable", False),  # 主机不可达
    ],
)
def test_first_gate(exit_code, timed_out, has_output, expected, go_llm):
    rt, llm = first_gate(exit_code, timed_out, has_output)
    assert rt == expected
    assert llm is go_llm


def test_report_type_level_orthogonal():
    """report_type∈确定集、level∈ok/warn/crit+unknown，二者正交。"""
    assert "success" in REPORT_TYPES
    assert {"ok", "warn", "crit"} <= set(LEVELS)
    # success 时 level 只来自 LLM（MOCK 语义）
    rt, go = first_gate(0, False, True)
    assert rt == "success" and go is True