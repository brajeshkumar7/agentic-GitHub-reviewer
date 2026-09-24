"""Resolve common natural-language research windows against one UTC run time."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from research_agent.models import DateWindow


_RELATIVE_DAYS = re.compile(r"\b(?:last|past)\s+(\d{1,4})\s+days?\b", re.I)
_RELATIVE_WEEKS = re.compile(r"\b(?:last|past)\s+(\d{1,3})\s+weeks?\b", re.I)
_RELATIVE_MONTHS = re.compile(r"\b(?:last|past)\s+(\d{1,3})\s+months?\b", re.I)
_DATE_RANGE = re.compile(
    r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+(?:to|through|until)\s+(\d{4}-\d{2}-\d{2})\b",
    re.I,
)


def resolve_goal_window(goal_text: str, run_started_at: datetime) -> tuple[DateWindow, bool]:
    """Return an explicit/simple relative window, or the documented seven-day default."""
    now = run_started_at.astimezone(timezone.utc)
    date_range = _DATE_RANGE.search(goal_text)
    if date_range:
        try:
            start_day = datetime.strptime(date_range.group(1), "%Y-%m-%d").date()
            end_day = datetime.strptime(date_range.group(2), "%Y-%m-%d").date()
            return (
                DateWindow(
                    start=datetime.combine(start_day, time.min, tzinfo=timezone.utc),
                    end=datetime.combine(end_day, time.max, tzinfo=timezone.utc),
                ),
                False,
            )
        except ValueError:
            pass

    relative_days = _RELATIVE_DAYS.search(goal_text)
    relative_weeks = _RELATIVE_WEEKS.search(goal_text)
    relative_months = _RELATIVE_MONTHS.search(goal_text)
    defaulted = False
    if relative_days:
        days = int(relative_days.group(1))
    elif relative_weeks:
        days = int(relative_weeks.group(1)) * 7
    elif relative_months:
        days = int(relative_months.group(1)) * 30
    elif re.search(r"\b(?:last|past)\s+week\b", goal_text, re.I):
        days = 7
    elif re.search(r"\b(?:last|past)\s+month\b", goal_text, re.I):
        days = 30
    elif re.search(r"\byesterday\b", goal_text, re.I):
        yesterday = (now - timedelta(days=1)).date()
        return (
            DateWindow(
                start=datetime.combine(yesterday, time.min, tzinfo=timezone.utc),
                end=datetime.combine(yesterday, time.max, tzinfo=timezone.utc),
            ),
            False,
        )
    elif re.search(r"\btoday\b", goal_text, re.I):
        today = now.date()
        return (
            DateWindow(
                start=datetime.combine(today, time.min, tzinfo=timezone.utc),
                end=now,
            ),
            False,
        )
    else:
        days = 7
        defaulted = True

    if days < 1:
        days = 7
        defaulted = True
    return DateWindow(start=now - timedelta(days=days), end=now), defaulted
