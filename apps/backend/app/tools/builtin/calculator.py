"""内置工具 tl_calculator：安全算术计算器（受限解析器，不用 eval）。

支持 + - * / % ( ) 与一元正负；浮点；除以零 → 结构化错误。拒绝任何非法字符（防注入）。
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"\s*(\d+\.?\d*|\.\d+|[+\-*/%()])")


class CalcError(ValueError):
    pass


def _tokenize(expr: str) -> list[Any]:
    tokens: list[Any] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise CalcError(f"无法解析: {expr[pos:pos + 8]!r}")
        tok = m.group(1)
        if tok in "+-*/%()":
            tokens.append(tok)
        else:
            tokens.append(float(tok))
        pos = m.end()
    return tokens


def _eval_tokens(tokens: list[Any]) -> float:
    pos = 0

    def peek() -> Any:
        return tokens[pos] if pos < len(tokens) else None

    def advance() -> Any:
        nonlocal pos
        t = tokens[pos]
        pos += 1
        return t

    def parse_expr() -> float:
        v = parse_term()
        while peek() in ("+", "-"):
            op = advance()
            r = parse_term()
            v = v + r if op == "+" else v - r
        return v

    def parse_term() -> float:
        v = parse_factor()
        while peek() in ("*", "/", "%"):
            op = advance()
            r = parse_factor()
            if op == "*":
                v = v * r
            elif op == "/":
                if r == 0:
                    raise CalcError("除以零")
                v = v / r
            else:
                v = v % r
        return v

    def parse_factor() -> float:
        t = peek()
        if t in ("+", "-"):
            advance()
            v = parse_factor()
            return v if t == "+" else -v
        return parse_primary()

    def parse_primary() -> float:
        t = peek()
        if t == "(":
            advance()
            v = parse_expr()
            if peek() != ")":
                raise CalcError("括号不匹配")
            advance()
            return v
        if isinstance(t, (int, float)):
            advance()
            return float(t)
        raise CalcError(f"无法解析: {t}")

    result = parse_expr()
    if pos != len(tokens):
        raise CalcError(f"多余内容: {tokens[pos:]}")
    return result


def calculate(expr: str) -> float:
    """安全求值（无 eval/内置函数/导入）；异常抛 CalcError。"""
    if not expr or len(expr) > 200:
        raise CalcError("表达式为空或过长")
    return _eval_tokens(_tokenize(expr))


async def calculator_handler(expression: str) -> dict[str, Any]:
    """计算算术表达式 → {expression, result} 或 {error}。"""
    try:
        result = calculate(expression)
        return {"expression": expression, "result": result}
    except CalcError as exc:
        return {"error": f"无法计算: {exc}"}
