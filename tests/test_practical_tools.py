"""实用工具包测试：calculator（安全算术）/ datetime_calc / unit_converter / weather（allowlist + mock）。"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.tools.builtin import calculator, datetime_calc, unit_converter, weather

# ---- calculator ----

@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("1+1", 2.0),
        ("(3+4)*2-1", 13.0),
        ("10/4", 2.5),
        ("-3+5", 2.0),
        ("7%3", 1.0),
        ("2.5*2", 5.0),
    ],
)
def test_calculator_arithmetic(expr, expected):
    assert calculator.calculate(expr) == expected


@pytest.mark.parametrize("expr", ["1/0", "(1+2", "1+abc", "__import__('os')", "1;2", ""])
def test_calculator_rejects_invalid(expr):
    from app.tools.builtin.calculator import CalcError

    with pytest.raises(CalcError):
        calculator.calculate(expr)


async def test_calculator_handler_error_shape():
    out = await calculator.calculator_handler(expression="1/0")
    assert "error" in out and "除以零" in out["error"]


# ---- datetime_calc ----

async def test_datetime_calc_ops():
    out = await datetime_calc.datetime_calc_handler(op="add_days", date="2026-08-17", days=3)
    assert out["result"] == "2026-08-20"
    out2 = await datetime_calc.datetime_calc_handler(op="days_between", date="2026-08-17", other="2026-09-01")
    assert out2["days"] == 15
    out3 = await datetime_calc.datetime_calc_handler(op="weekday", date="2026-08-17")
    assert out3["weekday"] == "周一"
    out4 = await datetime_calc.datetime_calc_handler(op="now")
    assert "now" in out4 and out4["date"]


async def test_datetime_calc_invalid():
    out = await datetime_calc.datetime_calc_handler(op="bogus")
    assert "error" in out
    out2 = await datetime_calc.datetime_calc_handler(op="add_days", date="not-a-date", days=1)
    assert "error" in out2


# ---- unit_converter ----

async def test_unit_converter():
    assert (await unit_converter.unit_converter_handler(5, "km", "m", "length"))["result"] == 5000.0
    assert (await unit_converter.unit_converter_handler(1, "kg", "g", "weight"))["result"] == 1000.0
    assert (await unit_converter.unit_converter_handler(100, "C", "F", "temperature"))["result"] == 212.0
    assert (await unit_converter.unit_converter_handler(36, "km/h", "m/s", "speed"))["result"] == pytest.approx(10.0)


async def test_unit_converter_invalid():
    assert "error" in await unit_converter.unit_converter_handler(1, "kg", "m", "length")
    assert "error" in await unit_converter.unit_converter_handler(1, "kg", "g", "bogus")


# ---- weather ----

def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_weather_gated_by_allowlist():
    settings = get_settings()
    orig = settings.fetch_url_allowlist
    settings.fetch_url_allowlist = []
    try:
        out = _run(weather.weather_handler("Beijing"))
        assert "error" in out and "授权" in out["error"]
    finally:
        settings.fetch_url_allowlist = orig


def test_weather_parses_mock_response(monkeypatch):
    settings = get_settings()
    orig = settings.fetch_url_allowlist
    settings.fetch_url_allowlist = ["wttr.in"]
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "current_condition": [
                        {
                            "temp_C": "28",
                            "temp_F": "82",
                            "humidity": "60",
                            "windspeedKmph": "12",
                            "FeelsLikeC": "30",
                            "weatherDesc": [{"value": "晴"}],
                        }
                    ],
                    "nearest_area": [{"areaName": [{"value": "Beijing"}]}],
                },
            )

        weather._transport = httpx.MockTransport(handler)
        out = _run(weather.weather_handler("Beijing"))
        assert out["location"] == "Beijing"
        assert out["temp_c"] == "28"
        assert out["weather"] == "晴"
    finally:
        weather._transport = None
        settings.fetch_url_allowlist = orig
