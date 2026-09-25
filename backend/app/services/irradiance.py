"""辐照监测业务规则：状态流转、字段校验、筛选与判定口径都收在这里。"""
from __future__ import annotations

from typing import Any, Mapping

from app.store import store

MODULE = "irradiance"
REQUIRED_FIELDS = ["测点编号", "测点位置", "总辐照度"]
STATUS_ORDER = ["正常采集", "数据缺测", "传感器故障", "已校准"]
ACTION_RULES = {"确认采集": "正常采集", "登记缺测": "数据缺测", "提交校准": "已校准"}
NEGATIVE_ACTIONS = []

# 判定结果取值：与 STATUS_ORDER 里的采集类状态一一对应；
# 已校准只属于人工流转，不由数值判定产生。
JUDGE_NORMAL = "正常采集"
JUDGE_MISSING = "数据缺测"
JUDGE_FAULT = "传感器故障"


def parse_measurement(value: Any) -> float | None:
    """把测点数值字段解析成浮点数；空值或无法解析时返回 None。

    列表、校准、补数据三个入口对"数值有没有采上来"的口径都以此为准，
    后续要调整（比如限定量程、允许缺省单位）只改这一处。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def judge_point(values: Mapping[str, Any]) -> str:
    """辐照测点状态判定：列表、校准、补数据三个入口共用的唯一口径。

    - 总辐照度缺失或不是数值 → 数据缺测（核心量没采上来）
    - 组件温度缺失或不是数值 → 传感器故障（辐照有数但温度通道异常）
    - 其余 → 正常采集

    缺测优先于故障：两个字段都异常时按数据缺测处理。
    判定只看当前数值，不读取也不修改记录的 status，
    已校准等人工流转状态不受判定影响。
    """
    if parse_measurement(values.get("总辐照度")) is None:
        return JUDGE_MISSING
    if parse_measurement(values.get("组件温度")) is None:
        return JUDGE_FAULT
    return JUDGE_NORMAL


def with_judgment(entry: Mapping[str, Any]) -> dict[str, Any]:
    """给返回的记录附上「判定结果」；复制一份再附，内存库里的原记录不动。"""
    return {**entry, "判定结果": judge_point(entry)}


class IrradianceService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("测点编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [with_judgment(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return with_judgment(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return with_judgment(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"辐照测点 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于辐照监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return with_judgment(entry), f"辐照测点已{action}"
