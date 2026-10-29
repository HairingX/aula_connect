"""Meebook's answer to relatedweekplan/all."""

import datetime
from typing import List, NotRequired, TypedDict

class AulaGetWeeklyPlansDailyTask(TypedDict):
    """A task of a day."""
    id: int
    type: str
    author: str
    group: str
    pill: str
    content: str
    title: NotRequired[str|None]

class AulaGetWeeklyPlansDailyPlan(TypedDict):
    """A day of a weekly plan."""
    date: str
    tasks: List[AulaGetWeeklyPlansDailyTask]

class AulaGetWeeklyPlansResponse(TypedDict):
    """A child's weekly plan, with the week's dates once read."""
    id: int
    name: str
    unilogin: str
    from_date: datetime.date
    to_date: datetime.date
    weekPlan: List[AulaGetWeeklyPlansDailyPlan]