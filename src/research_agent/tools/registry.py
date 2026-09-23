"""Fixed-allowlist registry that validates all arguments and tool outcomes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from research_agent.models import (
    CalculatorInput,
    FailureCategory,
    Retryability,
    ToolCall,
    ToolName,
    ToolResult,
    ToolResultStatus,
    URLFetchInput,
    WebSearchInput,
)
from research_agent.tools.base import Tool, ToolMetadata, failed_tool_result


class UnknownToolError(LookupError):
    """Raised by registry lookup when a name is not in the fixed allowlist."""


class DuplicateToolError(ValueError):
    """Raised when registration would replace an existing tool implementation."""


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[ToolName, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not isinstance(tool.name, ToolName):
            raise UnknownToolError("tool name is not in the approved allowlist")
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {tool.name.value}")
        if not tool.description.strip() or tool.timeout_seconds <= 0:
            raise ValueError("tool metadata must include a description and positive timeout")
        if not issubclass(tool.input_schema, BaseModel) or not issubclass(
            tool.output_schema, BaseModel
        ):
            raise TypeError("tool schemas must be Pydantic model classes")
        expected_schema = {
            ToolName.WEB_SEARCH: WebSearchInput,
            ToolName.URL_FETCH: URLFetchInput,
            ToolName.CALCULATOR: CalculatorInput,
        }[tool.name]
        if tool.input_schema is not expected_schema:
            raise TypeError("tool input schema does not match its approved name")
        self._tools[tool.name] = tool

    def get(self, name: ToolName | str) -> Tool:
        try:
            normalized_name = name if isinstance(name, ToolName) else ToolName(name)
        except ValueError:
            raise UnknownToolError("unknown tool name") from None
        try:
            return self._tools[normalized_name]
        except KeyError:
            raise UnknownToolError(f"tool is not registered: {normalized_name.value}") from None

    def metadata(self) -> list[ToolMetadata]:
        ordered_names = [name for name in ToolName if name in self._tools]
        return [
            ToolMetadata(
                name=name,
                description=self._tools[name].description,
                input_schema=self._tools[name].input_schema.model_json_schema(by_alias=False),
                output_schema=self._tools[name].output_schema.model_json_schema(by_alias=False),
                timeout_seconds=self._tools[name].timeout_seconds,
            )
            for name in ordered_names
        ]

    def validate_arguments(
        self, name: ToolName | str, arguments: BaseModel | Mapping[str, Any]
    ) -> BaseModel:
        tool = self.get(name)
        raw_arguments = (
            arguments.model_dump() if isinstance(arguments, BaseModel) else arguments
        )
        validated = tool.input_schema.model_validate(raw_arguments)
        expected_schema = {
            ToolName.WEB_SEARCH: WebSearchInput,
            ToolName.URL_FETCH: URLFetchInput,
            ToolName.CALCULATOR: CalculatorInput,
        }[tool.name]
        if not isinstance(validated, expected_schema):
            raise ValueError("registered schema does not match its approved tool name")
        return validated

    def dispatch(self, call: ToolCall) -> ToolResult:
        started_at = datetime.now(timezone.utc)
        try:
            validated_call = ToolCall.model_validate(dict(call.__dict__))
        except (ValidationError, ValueError, TypeError):
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Tool call arguments or metadata failed validation.",
                started_at=started_at,
            )
        try:
            tool = self.get(validated_call.tool_name)
        except UnknownToolError:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Tool is not in the approved registry.",
                started_at=started_at,
            )
        try:
            validated_arguments = self.validate_arguments(
                validated_call.tool_name, validated_call.arguments
            )
            validated_call = validated_call.model_copy(
                update={"arguments": validated_arguments}
            )
        except (ValidationError, ValueError, TypeError):
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Tool arguments failed the registered input schema.",
                started_at=started_at,
            )
        try:
            raw_result = tool.execute(validated_call)
        except Exception:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Tool failed unexpectedly; response details were omitted.",
                started_at=started_at,
            )
        try:
            result = ToolResult.model_validate(raw_result.model_dump())
            if result.call_id != validated_call.call_id:
                raise ValueError("tool result call ID does not match request")
            if result.status == ToolResultStatus.SUCCEEDED:
                if result.output is None:
                    raise ValueError("successful tool response has no output")
                validated_output = tool.output_schema.model_validate(
                    result.output.model_dump()
                )
                result = result.model_copy(update={"output": validated_output})
            elif result.failure is None or result.failure.run_id != validated_call.run_id:
                raise ValueError("failed tool response has invalid failure provenance")
            return result
        except Exception:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Tool response failed output validation; response details were omitted.",
                started_at=started_at,
            )
