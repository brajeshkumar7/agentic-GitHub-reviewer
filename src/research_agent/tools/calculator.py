"""Safe decimal calculator for allowlisted operations and a tiny AST grammar."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from decimal import Decimal, DecimalException, localcontext

from pydantic import ValidationError

from research_agent.limits import CALCULATOR_MAX_AST_NODES
from research_agent.models import (
    Calculation,
    CalculatorInput,
    CalculatorOperation,
    FailureCategory,
    Retryability,
    ToolCall,
    ToolName,
    ToolResult,
    ToolResultStatus,
)
from research_agent.tools.base import failed_tool_result

_NUMBER_LITERAL = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


class InvalidExpression(ValueError):
    """An expression falls outside the supported arithmetic grammar."""


def evaluate_expression(expression: str) -> Decimal:
    """Evaluate decimal literals, parentheses, unary signs and + - * / only."""

    if not expression.strip() or len(expression) > 256:
        raise InvalidExpression("expression is empty or too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        raise InvalidExpression("expression syntax is invalid") from None
    if sum(1 for _ in ast.walk(tree)) > CALCULATOR_MAX_AST_NODES:
        raise InvalidExpression("expression exceeds the AST node limit")

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise InvalidExpression("only numeric decimal literals are allowed")
            literal = ast.get_source_segment(expression, node)
            if literal is None or not _NUMBER_LITERAL.fullmatch(literal):
                raise InvalidExpression("numeric literal is not supported")
            return Decimal(literal)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ZeroDivisionError("division by zero")
            return left / right
        raise InvalidExpression("expression contains an unsupported syntax node")

    try:
        with localcontext() as context:
            context.prec = 28
            result = visit(tree)
    except DecimalException:
        raise InvalidExpression("expression is outside supported decimal range") from None
    if not result.is_finite():
        raise InvalidExpression("expression result is not finite")
    return result


def _evaluate_operation(
    operation: CalculatorOperation, operands: list[Decimal]
) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        if operation == CalculatorOperation.ADD:
            result = operands[0] + operands[1]
        elif operation == CalculatorOperation.SUBTRACT:
            result = operands[0] - operands[1]
        elif operation == CalculatorOperation.MULTIPLY:
            result = operands[0] * operands[1]
        elif operation == CalculatorOperation.DIVIDE:
            result = operands[0] / operands[1]
        elif operation == CalculatorOperation.MEAN:
            result = sum(operands, Decimal("0")) / Decimal(len(operands))
        else:
            result = operands[0] / operands[1] * Decimal("100")
    if not result.is_finite():
        raise InvalidExpression("calculation result is not finite")
    return result


class CalculatorTool:
    name = ToolName.CALCULATOR
    description = "Calculate with decimal arithmetic using approved operations only."
    input_schema = CalculatorInput
    output_schema = Calculation
    timeout_seconds = 1.0

    def execute(self, call: ToolCall) -> ToolResult:
        started_at = datetime.now(timezone.utc)
        try:
            calculator_input = CalculatorInput.model_validate(call.arguments.model_dump())
            if calculator_input.expression is not None:
                result = evaluate_expression(calculator_input.expression)
                calculation = Calculation(
                    expression=calculator_input.expression,
                    result=result,
                )
            else:
                assert calculator_input.operation is not None
                assert calculator_input.operands is not None
                result = _evaluate_operation(
                    calculator_input.operation, calculator_input.operands
                )
                calculation = Calculation(
                    operation=calculator_input.operation,
                    operands=calculator_input.operands,
                    result=result,
                )
            return ToolResult(
                call_id=call.call_id,
                status=ToolResultStatus.SUCCEEDED,
                output=calculation,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        except ValidationError:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Calculator arguments failed validation.",
                started_at=started_at,
            )
        except (InvalidExpression, ZeroDivisionError, DecimalException):
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.CALCULATOR_ERROR,
                retryability=Retryability.NON_RETRYABLE,
                message="Calculator expression or arithmetic was invalid.",
                started_at=started_at,
            )
        except Exception:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.CALCULATOR_ERROR,
                retryability=Retryability.NON_RETRYABLE,
                message="Calculator failed unexpectedly; input details were omitted.",
                started_at=started_at,
            )
