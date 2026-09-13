"""O4 校验管线单测（D23/D45/D47）：零 LLM、确定性标注。"""
from app.services.validation import (
    run_pipeline,
    check_evidence,
    check_out_of_bound,
    check_level_consistency,
)


def test_p1_structure_missing():
    notes = run_pipeline("### 结论\n服务可能挂了", "warn", False)
    rules = {n["rule"] for n in notes}
    assert "p1_structure" in rules


def test_p2_evidence_no_ref_suspicious():
    notes = check_evidence("根因：DB 连接失败")
    assert any(n["rule"] == "p2_evidence" and n["level"] == "suspicious" for n in notes)


def test_p2_evidence_has_ref_ok():
    assert check_evidence("根因：DB 连接失败 @run_12") == []


def test_p3_conflict():
    notes = run_pipeline("结论：可能 DB 挂了 @run_1", "crit", False, evidence_tags=["error", "ok"])
    assert any(n["rule"] == "p3_conflict" and n["level"] == "conflict" for n in notes)


def test_p4_out_of_bound():
    notes = check_out_of_bound("引用 run_99 数据 @run_99", available_run_ids={1, 2})
    assert any(n["rule"] == "p4_out_of_bound" for n in notes)


def test_p5_inconsistency():
    assert any(
        n["rule"] == "p5_level_consistency" and n["level"] == "note"
        for n in check_level_consistency("crit", has_error_keyword=False)
    )


def test_banner_when_suspicious():
    notes = run_pipeline("结论：可能有问题 但没引用", "crit", False, available_run_ids={1})
    assert any(n["rule"] == "banner" for n in notes)


def test_pipeline_disabled():
    notes = run_pipeline("结论：可能有问题 但没引用", "crit", False, enabled={"p2_evidence": False, "p5_level_consistency": False})
    assert not any(n["rule"] in ("p2_evidence", "p5_level_consistency") for n in notes)