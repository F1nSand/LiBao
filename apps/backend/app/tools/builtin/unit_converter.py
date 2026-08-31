"""内置工具 tl_unit_converter：单位换算（纯本地，无需外网）。

category: length / weight / temperature / speed；value + from_unit + to_unit。
温度用公式（非线性），其余用换算因子。异常兜底 error。
"""

from __future__ import annotations

from typing import Any

# 各量纲换算因子（基准单位：m / kg / m/s；temperature 走公式）
_FACTORS: dict[str, dict[str, float]] = {
    "length": {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "ft": 0.3048, "in": 0.0254},
    "weight": {"kg": 1.0, "g": 0.001, "t": 1000.0, "lb": 0.45359237, "oz": 0.028349523},
    "speed": {"m/s": 1.0, "km/h": 1.0 / 3.6, "mph": 0.44704, "kn": 0.514444},
}
_TEMP_UNITS = {"C", "F", "K"}


def _convert_temperature(value: float, frm: str, to: str) -> float:
    """摄氏/华氏/开尔文互转。"""
    if frm == "C":
        c = value
    elif frm == "F":
        c = (value - 32) * 5 / 9
    else:  # K
        c = value - 273.15
    if to == "C":
        return c
    if to == "F":
        return c * 9 / 5 + 32
    return c + 273.15


async def unit_converter_handler(
    value: float, from_unit: str, to_unit: str, category: str = "length"
) -> dict[str, Any]:
    """单位换算：{category, value, from_unit, to_unit} → {result, unit} 或 error。"""
    frm, to = (from_unit or "").lower(), (to_unit or "").lower()
    try:
        if category == "temperature":
            frm_u, to_u = frm.upper(), to.upper()  # 温度单位 C/F/K 不区分大小写
            if frm_u not in _TEMP_UNITS or to_u not in _TEMP_UNITS:
                return {"error": "温度单位仅支持 C/F/K"}
            result = _convert_temperature(value, frm_u, to_u)
            return {"category": category, "value": value, "from": frm_u, "to": to_u, "result": result, "unit": to_u}
        table = _FACTORS.get(category)
        if table is None:
            return {"error": f"未知量纲: {category}（可选 length/weight/temperature/speed）"}
        if frm not in table or to not in table:
            return {"error": f"单位不支持: {frm}→{to}（{category} 支持 {sorted(table)}）"}
        result = value * table[frm] / table[to]
        return {"category": category, "value": value, "from": frm, "to": to, "result": result, "unit": to}
    except (TypeError, ValueError) as exc:
        return {"error": f"换算失败: {exc}"}
