"""Reading Aula's birthday events into the models."""

from typing import List

from ..responses.get_birthday_events_for_institutions import *
from ..utils.list_utils import list_without_none
from .aula_birthday_models import *
from .aula_parser import AulaParser

class AulaBirthdayParser(AulaParser):

    """Reads Aula's birthday events."""
    @staticmethod
    def parse_birthday_event(data: AulaBirthdayEventData | None) -> AulaBirthdayEvent | None:
        """A birthday, None for no data."""
        if not data: return None
        result = AulaBirthdayEvent(
            institution_profile_id = AulaBirthdayParser._parse_int(data.get("institutionProfileId")),
            birthday_date = AulaBirthdayParser._parse_date(data.get("birthday")),
            institution_code = AulaBirthdayParser._parse_str(data.get("institutionCode")),
            full_name = AulaBirthdayParser._parse_str(data.get("name")),
            main_group_name = AulaBirthdayParser._parse_str(data.get("mainGroupName")),
        )

        return result

    @staticmethod
    def parse_birthday_events(data: List[AulaBirthdayEventData] | None) -> List[AulaBirthdayEvent]:
        """The birthdays, leaving out those with no data."""
        if data is None: return []
        return list_without_none(map(AulaBirthdayParser.parse_birthday_event, data))


    @staticmethod
    def parse_birthday_event_response(data: AulaGetBirthdayEventsForInstitutionsResponse | None) -> List[AulaBirthdayEvent]:
        """The birthdays of Aula's answer to calendar.getBirthdayEventsForInstitutions."""
        if data is None: return []
        return AulaBirthdayParser.parse_birthday_events(data["data"])
