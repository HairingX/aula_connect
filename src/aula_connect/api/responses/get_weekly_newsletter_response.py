"""MinUddannelse's answer to ugebrev."""

from datetime import date
from typing import List, NotRequired, TypedDict

class AulaWeeklyNewsletterData(TypedDict):
    """A newsletter."""
    indhold: str

class AulaWeeklyNewsletterInstitutionData(TypedDict):
    """An institution, with its newsletters."""
    institution: str
    ugebreve: NotRequired[List[AulaWeeklyNewsletterData]|None]

class AulaWeeklyNewsletterPersonData(TypedDict):
    """A child, with the institutions' newsletters."""
    navn: str
    institutioner: NotRequired[List[AulaWeeklyNewsletterInstitutionData]|None]

class AulaGetWeeklyNewsletterResponse(TypedDict):
    """The answer, with the children."""
    from_date: date
    to_date: date
    personer: List[AulaWeeklyNewsletterPersonData]
