"""Reading Meebook's weekly plans into the models."""

from datetime import timedelta, date
from typing import List

from ..responses.get_weekly_plans_response import AulaGetWeeklyPlansDailyPlan, AulaGetWeeklyPlansDailyTask, AulaGetWeeklyPlansResponse
from ..utils.list_utils import list_without_none

from .aula_weekly_plan_models import AulaWeeklyPlan, AulaDailyPlan, AulaDailyPlanTask
from .aula_parser import AulaParser

class AulaWeeklyPlanParser(AulaParser):
    """Reads Meebook's weekly plans."""
    @staticmethod
    def parse_daily_plan_task(data: AulaGetWeeklyPlansDailyTask | None) -> AulaDailyPlanTask:
        """A task of a day; raises ValueError for no data."""
        if not data: raise ValueError()
        result = AulaDailyPlanTask(
            id = AulaWeeklyPlanParser._parse_int(data.get("id")),
            type = AulaWeeklyPlanParser._parse_str(data.get("type")),
            author = AulaWeeklyPlanParser._parse_str(data.get("author")),
            group = AulaWeeklyPlanParser._parse_str(data.get("group")),
            pill = AulaWeeklyPlanParser._parse_str(data.get("pill")),
            content = AulaWeeklyPlanParser._parse_str(data.get("content")),
            editUrl = AulaWeeklyPlanParser._parse_nullable_str(data.get("editUrl")),
            title = AulaWeeklyPlanParser._parse_nullable_str(data.get("title")),
        )
        return result

    @staticmethod
    def parse_daily_plan_tasks(data: List[AulaGetWeeklyPlansDailyTask] | None) -> List[AulaDailyPlanTask]:
        """The tasks of a day."""
        if data is None: return []
        return list_without_none(map(AulaWeeklyPlanParser.parse_daily_plan_task, data))

    @staticmethod
    def parse_daily_plan(data: AulaGetWeeklyPlansDailyPlan | None, date: date) -> AulaDailyPlan:
        """The plan of the day `date`; raises ValueError for no data."""
        if not data: raise ValueError()
        result = AulaDailyPlan(
            date = date,
            tasks = AulaWeeklyPlanParser.parse_daily_plan_tasks(data.get("tasks")),
        )
        return result

    @staticmethod
    def parse_daily_plans(data: List[AulaGetWeeklyPlansDailyPlan] | None, from_date: date) -> List[AulaDailyPlan]:
        """The plans of the days from `from_date` on, one a day."""
        if data is None: return []
        result = list[AulaDailyPlan]()
        for i, dayplan in enumerate(data):
            plan_date = from_date + timedelta(days=i)
            plan = AulaWeeklyPlanParser.parse_daily_plan(dayplan, plan_date)
            if plan: result.append(plan)
        return result

    @staticmethod
    def parse_weekly_plan(data: AulaGetWeeklyPlansResponse | None) -> AulaWeeklyPlan:
        """A child's weekly plan; raises ValueError for no data."""
        if not data: raise ValueError()
        result = AulaWeeklyPlan(
            name = AulaWeeklyPlanParser._parse_str(data.get("name")),
            unilogin = AulaWeeklyPlanParser._parse_str(data.get("unilogin")),
            from_date = AulaWeeklyPlanParser._parse_date(data.get("from_date")),
            to_date = AulaWeeklyPlanParser._parse_date(data.get("to_date")),
            daily_plans = []
        )
        result.daily_plans = AulaWeeklyPlanParser.parse_daily_plans(data.get("weekPlan"), result.from_date)
        return result

    @staticmethod
    def parse_weekly_plans(data: List[AulaGetWeeklyPlansResponse] | None) -> List[AulaWeeklyPlan]:
        """The children's weekly plans."""
        if data is None: return []
        return list_without_none(map(AulaWeeklyPlanParser.parse_weekly_plan, data))
