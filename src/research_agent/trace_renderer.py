"""Render the public planning and execution trace; never render model reasoning."""

from __future__ import annotations

from research_agent.event_logger import redact_text, sanitize_event
from research_agent.models import EventType, ExecutionEvent, Plan


class TraceRenderer:
    """Format only the structured plan and concise action/outcome summaries."""

    def render_plan(self, plan: Plan) -> str:
        lines = ["[PLAN]"]
        for index, step in enumerate(plan.steps, start=1):
            objective = redact_text(step.objective)
            lines.append(f"{index}. {objective} ({step.id}; {step.tool_name.value})")
        return "\n".join(lines)

    def render_event(self, event: ExecutionEvent) -> str | None:
        event = sanitize_event(event)
        summary = event.summary
        if event.event_type is EventType.GOAL_RECEIVED:
            goal = event.metadata.get("goal")
            return f"[GOAL]\n{redact_text(goal)}" if isinstance(goal, str) else f"[GOAL]\n{summary}"
        if event.event_type is EventType.PLAN_CREATED:
            steps = event.metadata.get("steps")
            if isinstance(steps, list):
                lines = ["[PLAN]"]
                for index, item in enumerate(steps, start=1):
                    if not isinstance(item, dict):
                        continue
                    objective = redact_text(str(item.get("objective", "")))
                    step_id = redact_text(str(item.get("id", "")))
                    tool_name = redact_text(str(item.get("tool_name", "")))
                    lines.append(f"{index}. {objective} ({step_id}; {tool_name})")
                return "\n".join(lines)
            return f"[PLAN]\n{summary}"
        step = event.step_id or (event.tool_name.value if event.tool_name else None)
        label = f"{step}: {summary}" if step else summary
        if event.event_type in {EventType.TOOL_CALL_STARTED, EventType.STEP_STARTED}:
            return f"→ {label}"
        if event.event_type in {EventType.TOOL_CALL_SUCCEEDED, EventType.STEP_COMPLETED}:
            return f"✓ {label}"
        if event.event_type in {EventType.TOOL_CALL_FAILED, EventType.STEP_FAILED}:
            return f"⚠ {label}"
        if event.event_type in {EventType.RETRY_ATTEMPTED, EventType.RECOVERY_STARTED}:
            return f"↻ {label}"
        if event.event_type is EventType.REPLAN_STARTED:
            return f"↻ replanning: {summary}"
        if event.event_type in {
            EventType.PLAN_VALIDATED,
            EventType.SYNTHESIS_STARTED,
            EventType.FINAL_REPORT_CREATED,
            EventType.EXECUTION_COMPLETED,
        }:
            return f"• {summary}"
        return None

    def render(self, plan: Plan, events: list[ExecutionEvent]) -> str:
        goal_event = next(
            (event for event in events if event.event_type is EventType.GOAL_RECEIVED),
            None,
        )
        plan_event = next(
            (event for event in events if event.event_type is EventType.PLAN_CREATED),
            None,
        )
        lines: list[str] = []
        for event in (goal_event,):
            if event is not None:
                rendered = self.render_event(event)
                if rendered:
                    lines.extend([rendered, ""])
        if plan_event is not None:
            rendered = self.render_event(plan_event)
            lines.append(rendered or self.render_plan(plan))
        else:
            lines.append(self.render_plan(plan))
        lines.extend(["", "[EXECUTION]"])
        header_event_ids = {
            event.event_id
            for event in (goal_event, plan_event)
            if event is not None
        }
        lines.extend(
            rendered
            for event in events
            if event.event_id not in header_event_ids
            and (rendered := self.render_event(event)) is not None
        )
        return "\n".join(lines)
