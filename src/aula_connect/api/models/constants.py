"""The widgets, the kinds of calendar events and plan tasks, their icons, and the labels shown to users."""

from enum import StrEnum


class AulaWidgetId(StrEnum):
    """The widgets an institution can have, by Aula's id."""
    EASYIQ_WEEKPLAN = "0001"
    """0001 - Week plan posted on easyiqcloud.dk/api/aula."""
    WEEKPLAN_PARENTS = "0004"
    """0004 - Week plan for each student/child."""
    MY_EDUCATION_WEEKLETTER = "0029"
    """0029 - Weekletter posted on minuddannelse.net/aula."""
    MY_EDUCATION_ASSIGNMENTS = "0030"
    """0030 - Assignments posted on minuddannelse.net/aula."""
    REMINDERS = "0062"
    """0062 - Reminders posted on systematic-momo.dk/api/aula"""


class AulaCalendarEventType(StrEnum):
    """The kinds of calendar events."""
    EVENT = 'event'
    LESSON = 'lesson'
    HOLIDAY = 'holiday'
    PRESENCE_HOLIDAY = 'presence_holiday'
    BIRTHDAY = 'birthday'
    OTHER = 'other'
    EXCURSION = 'excursion'
    SCHOOL_HOME_MEETING = 'school_home_meeting'
    PARENTAL_MEETING = 'parental_meeting'
    PERFORMANCE_MEETING = 'performance_meeting'
    VACATION_REGISTRATION = 'vacation_registration'


CALENDAR_EVENT_ICON: dict[str, str] = {
    AulaCalendarEventType.BIRTHDAY: "🎁",
    AulaCalendarEventType.LESSON: "",
    AulaCalendarEventType.EVENT: "⭐",
    AulaCalendarEventType.HOLIDAY: "🏖️",
    AulaCalendarEventType.PRESENCE_HOLIDAY: "🏖️",
    AulaCalendarEventType.EXCURSION: "🚌",
    AulaCalendarEventType.SCHOOL_HOME_MEETING: "👥",
    AulaCalendarEventType.PARENTAL_MEETING: "👥",
    AulaCalendarEventType.PERFORMANCE_MEETING: "👥",
    AulaCalendarEventType.VACATION_REGISTRATION: "🏖️",
    AulaCalendarEventType.OTHER: "📌",
}


class AulaWeeklyPlanTaskType(StrEnum):
    """The kinds of tasks in a weekly plan."""
    TASK = "task"
    COMMENT = "comment"


WEEKLY_PLAN_TASK_ICON: dict[str, str] = {
    AulaWeeklyPlanTaskType.TASK: "🔴",
    AulaWeeklyPlanTaskType.COMMENT: "ℹ️",
}


# The labels shown to users, by language; Danish where a language has none.

_language = "da"

_LABELS: dict[str, dict[str, str]] = {
    "da": {
        "substitute": "Vikar",
        "bring_children": "Medbring",
        "status_prefix": "Status",
        "birthday_turns": "fylder",
        "response_waiting": "Afventer svar",
        "response_accepted": "Accepteret",
        "response_declined": "Afvist",
    },
    "en": {
        "substitute": "Substitute",
        "bring_children": "Bring",
        "status_prefix": "Status",
        "birthday_turns": "turns",
        "response_waiting": "Awaiting response",
        "response_accepted": "Accepted",
        "response_declined": "Declined",
    },
}


def set_language(language: str) -> None:
    """Set the UI language. Call from config flow / async_setup_entry."""
    global _language
    _language = language


def get_label(key: str) -> str:
    """Get a UI label for the current language, falling back to key name."""
    return _LABELS.get(_language, _LABELS["da"]).get(key, key)