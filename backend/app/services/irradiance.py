"""辐照监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "irradiance"
REQUIRED_FIELDS = ["测点编号", "测点位置", "总辐照度"]

# ---- 测点判定规则：列表筛选、动作流转、补录登记三个入口共用这一份 ----
MISSING_STATUS = "数据缺测"
FAULT_STATUS = "传感器故障"
STATUS_ORDER = ["正常采集", MISSING_STATUS, FAULT_STATUS, "已校准"]
ACTION_RULES = {"确认采集": "正常采集", "登记缺测": MISSING_STATUS, "提交校准": "已校准"}
NEGATIVE_ACTIONS = []


def initial_status() -> str:
    """补录或新登记测点的起始状态。"""
    return STATUS_ORDER[0]


def is_known_status(status: str) -> bool:
    """状态是否在允许的序列里。"""
    return status in STATUS_ORDER


def is_terminal_status(status: str) -> bool:
    """序列末尾（已校准）是终态，到达后测点不再 pending。"""
    return status == STATUS_ORDER[-1]


def target_status_for(action: str) -> str | None:
    """动作对应的目标状态；动作不在可执行范围时返回 None。"""
    return ACTION_RULES.get(action)


def resolve_state(status: str, action: str | None = None) -> dict[str, Any]:
    """由状态推出 pending/abnormal，三个入口都从这里取判定结果。"""
    return {
        "status": status,
        "pending": not is_terminal_status(status),
        "abnormal": action in NEGATIVE_ACTIONS,
    }


def matches_status(row: dict[str, Any], status: str) -> bool:
    """列表筛选的判定口径：按测点当前状态精确匹配。"""
    return row.get("status") == status


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
            rows = [row for row in rows if matches_status(row, status)]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update(resolve_state(initial_status()))
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"辐照测点 {entry_id} 不存在或已归档"
        target = target_status_for(action)
        if target is None:
            return None, f"动作「{action}」不属于辐照监测可执行范围"
        if not is_known_status(target):
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry.update(resolve_state(target, action))
        return entry, f"辐照测点已{action}"
