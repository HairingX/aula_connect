"""The birthdays at an institution."""

from dataclasses import dataclass
from datetime import date

@dataclass
class AulaBirthdayEvent:
    """A child's birthday at one of the children's institutions."""
    institution_profile_id: int
    birthday_date: date
    institution_code: str
    full_name: str
    main_group_name: str
    """Group this child mainly belongs to. E.g. "0A"."""
