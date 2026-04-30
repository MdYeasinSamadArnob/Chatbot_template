"""
Calculator tool — safe arithmetic expression evaluator.

Pattern demonstration:
  - Pydantic input schema (auto-generates JSON schema for LLM)
  - @register_tool decorator
  - async function signature with (args, memory=None)
  - Returns a plain string (the LLM sees this as the tool output)

To add a new tool, copy this pattern.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import register_tool

# ── Safe arithmetic evaluator ──────────────────────────────────────────────

_SAFE_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expression: str) -> float:
    """
    Evaluate a pure arithmetic expression without using eval().
    Raises ValueError for anything that isn't a number or arithmetic op.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError(f"Unsupported literal: {node.value!r}")
            return float(node.value)
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return _SAFE_OPS[op_type](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            return _SAFE_OPS[op_type](_eval(node.operand))
        raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    return _eval(tree.body)


# ── Tool definition ────────────────────────────────────────────────────────


class CalculateInput(BaseModel):
    expression: str = Field(
        ...,
        description="A mathematical expression to evaluate, e.g. '(100 + 50) * 2 / 3'",
    )


@register_tool(
    "calculate",
    "Evaluate a mathematical expression. Use this for any arithmetic calculation.",
    CalculateInput,
)
async def calculate(args: CalculateInput, memory=None) -> str:
    try:
        result = _safe_eval(args.expression)
        # Format cleanly: int if no fractional part
        if result == int(result):
            formatted = str(int(result))
        else:
            formatted = f"{result:.10g}"
        return f"{args.expression} = {formatted}"
    except ValueError as exc:
        return f"Error: {exc}"
