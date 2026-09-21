"""Current shared evidence/capture contracts, extracted from the retired demo suite."""
import copy  # 导入运行所需模块。


import json  # 导入运行所需模块。


import time  # 导入运行所需模块。


from types import SimpleNamespace  # 导入本模块需要的接口。


import pytest  # 导入运行所需模块。


from focus_demo.common import digest  # 导入本模块需要的接口。


from focus_demo.collectors import intersection, subtract, mark_visibility  # 导入本模块需要的接口。


from focus_demo.prompts import timeline, apply_time_patch, inspect_evidence  # 导入本模块需要的接口。


@pytest.fixture  # 声明函数的测试参数或调用方式。
def raw():  # 定义当前功能的处理入口。
    return {"segments": [{"id": "s001", "real_duration_seconds": 1.0, "objects": [{"id": "tab:real-shape", "focused": True, "title": "只读身份"}]}, {"id": "s002", "real_duration_seconds": 2.0, "objects": []}], "evidence": {"e1": {"text": "历史证据"}}, "raw_sha256": "unchanged", "real_start": 10.0, "real_end": 13.0, "unobserved_gap_seconds": 0}  # 返回本步骤的结果。


def test_time_patch_keeps_raw_and_rebuilds_timeline(raw):  # 定义当前功能的处理入口。
    original = copy.deepcopy(raw)  # 保存下一步骤使用的计算结果。
    effective = apply_time_patch(raw, {"durations": {"s001": 600}, "reason": "真实一秒模拟十分钟"}, True)  # 保存改写后的时间摘要。
    assert raw == original  # 验证实际结果符合预期。
    assert effective["segments"][0]["real_duration_seconds"] == 1  # 验证实际结果符合预期。
    assert effective["segments"][1]["relative_start_seconds"] == 600  # 验证实际结果符合预期。
    assert effective["effective_observed_seconds"] == 602  # 验证实际结果符合预期。
    assert effective["test_time_override"] is True  # 验证实际结果符合预期。
    assert effective["segments"][0]["objects"] == original["segments"][0]["objects"]  # 验证实际结果符合预期。


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), 86401, True, "600"])  # 声明函数的测试参数或调用方式。
def test_bad_durations_are_rejected(raw, value):  # 定义当前功能的处理入口。
    with pytest.raises(ValueError):  # 在受控资源或锁范围内执行。
        apply_time_patch(raw, {"durations": {"s001": value}, "reason": "错误输入"}, True)  # 执行当前步骤并保留既定边界。


@pytest.mark.parametrize("patch", [{"title": "伪造"}, {"durations": {"missing": 1}, "reason": "错误编号"}, {"durations": {"s001": 3}}])  # 声明函数的测试参数或调用方式。
def test_identity_unknown_id_missing_reason_rejected(raw, patch):  # 定义当前功能的处理入口。
    with pytest.raises(ValueError):  # 在受控资源或锁范围内执行。
        apply_time_patch(raw, patch, True)  # 执行当前步骤并保留既定边界。


def test_production_rejects_any_patch(raw):  # 定义当前功能的处理入口。
    with pytest.raises(ValueError):  # 在受控资源或锁范围内执行。
        apply_time_patch(raw, {"durations": {"s001": 600}, "reason": "不得改"}, False)  # 执行当前步骤并保留既定边界。


def test_empty_patch_uses_real_time(raw):  # 定义当前功能的处理入口。
    value = apply_time_patch(raw, {}, False)  # 保存下一步骤使用的计算结果。
    assert value["effective_observed_seconds"] == 3  # 验证实际结果符合预期。
    assert value["test_time_override"] is False  # 验证实际结果符合预期。


def test_rectangle_intersection_and_subtraction():  # 定义当前功能的处理入口。
    assert intersection([0, 0, 100, 100], [50, 0, 100, 100]) == [50, 0, 50, 100]  # 验证实际结果符合预期。
    pieces = subtract([0, 0, 100, 100], [25, 25, 50, 50])  # 保存下一步骤使用的计算结果。
    assert sum(rect[2]*rect[3] for rect in pieces) == 7500  # 验证实际结果符合预期。


def test_occluded_and_minimized_windows_not_visible():  # 定义当前功能的处理入口。
    windows = [{"id": "bottom", "rect": [0, 0, 100, 100], "mapped": True}, {"id": "top", "rect": [0, 0, 100, 100], "mapped": True}, {"id": "minimized", "rect": [0, 0, 100, 100], "mapped": False}]  # 保存窗口集合。
    mark_visibility(windows, [0, 0, 200, 200])  # 执行当前步骤并保留既定边界。
    assert windows[0]["visible"] is False  # 验证实际结果符合预期。
    assert windows[1]["visible"] is True  # 验证实际结果符合预期。
    assert windows[2]["visible"] is False  # 验证实际结果符合预期。


def test_historical_tool_never_invents_missing_evidence(raw):  # 定义当前功能的处理入口。
    assert inspect_evidence(raw["evidence"], ["e1"])["e1"]["text"] == "历史证据"  # 验证实际结果符合预期。
    assert "error" in inspect_evidence(raw["evidence"], ["missing"])["missing"]  # 验证实际结果符合预期。


def test_sleep_gap_is_not_counted_as_activity():  # 定义当前功能的处理入口。
    def sample(number, mono):  # 定义当前功能的处理入口。
        return {"sample_id": number, "ts": mono+100, "mono": mono, "desktop": {"windows": [], "available": True}, "browser": {"pages": [], "available": True}}  # 返回本步骤的结果。
    value = timeline([sample(1, 1), sample(2, 2), sample(3, 102)], 0.5)  # 保存下一步骤使用的计算结果。
    assert sum(segment["real_duration_seconds"] for segment in value["segments"]) == 1  # 验证实际结果符合预期。
    assert value["unobserved_gap_seconds"] == 100  # 验证实际结果符合预期。


def test_gnome_stale_snapshot_is_not_live(tmp_path):  # 定义当前功能的处理入口。
    from focus_demo.collectors import GnomeDesktop  # 导入本模块需要的接口。
    path = tmp_path / "snapshot.json"  # 保存文件路径。
    path.write_text(json.dumps({"ts":time.time()-100, "windows":[], "backend":"gnome"}))  # 执行当前步骤并保留既定边界。
    assert GnomeDesktop(path).capture()["available"] is False  # 验证实际结果符合预期。
