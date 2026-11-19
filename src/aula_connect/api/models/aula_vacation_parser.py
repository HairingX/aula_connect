"""Reading Aula's vacations and vacation requests into the models."""

from datetime import date, time
from typing import Any, List

from ..responses.get_vacation_announcements_by_children_response import AulaGetVacationAnnouncementsByChildrenResponse
from ..responses.get_vacation_registration_response_response import AulaGetVacationRegistrationResponseResponse
from ..responses.get_vacation_registrations_by_children_response import AulaGetVacationRegistrationsByChildrenResponse
from .aula_parser import AulaParser
from .aula_vacation_models import AulaVacation, AulaVacationDay, AulaVacationRequest, AulaVacationRequestDetail


class AulaVacationParser(AulaParser):
    """Reads a child's vacations and the requests to say whether a child comes."""

    @staticmethod
    def parse_vacations_response(data: AulaGetVacationAnnouncementsByChildrenResponse) -> List[AulaVacation]:
        """The vacations of every child in Aula's answer, a child's in Aula's order."""
        parse = AulaVacationParser
        return [
            AulaVacation(
                id=parse._parse_int(vacation.get("vacationId")),
                child_id=parse._parse_int((group.get("child") or {}).get("id")),
                start_date=parse._parse_date(vacation.get("startDate")),
                end_date=parse._parse_date(vacation.get("endDate")),
                description=vacation.get("description") or None,
                is_editable=parse._parse_bool(vacation.get("isEditable")),
            )
            for group in data["data"]
            for vacation in group.get("vacationAnnouncements") or []
        ]

    @staticmethod
    def parse_requests_response(data: AulaGetVacationRegistrationsByChildrenResponse) -> List[AulaVacationRequest]:
        """The vacation requests about every child in Aula's answer, a child's in Aula's order."""
        parse = AulaVacationParser
        return [
            AulaVacationRequest(
                id=parse._parse_nullable_int(request.get("vacationRegistrationId")),
                response_id=parse._parse_int(request.get("responseId")),
                child_id=parse._parse_int((group.get("child") or {}).get("id")),
                title=parse._parse_str(request.get("title")),
                start_date=parse._parse_date(request.get("startDate")),
                end_date=parse._parse_date(request.get("endDate")),
                response_deadline=parse._day(request.get("responseDeadline")),
                note_to_guardian=request.get("noteToGuardian") or None,
                missing_answer=parse._parse_bool(request.get("isMissingAnswer")),
                is_editable=parse._parse_bool(request.get("isEditable")),
                is_presence_times_required=parse._parse_nullable_bool(request.get("isPresenceTimesRequired")),
            )
            for group in data["data"]
            for request in group.get("vacationRegistrations") or []
        ]

    @staticmethod
    def parse_request_response(data: AulaGetVacationRegistrationResponseResponse) -> AulaVacationRequestDetail:
        """The vacation request and its answer in Aula's answer."""
        parse = AulaVacationParser
        answer = data["data"].get("vacationRegistrationResponse") or {}
        request = data["data"].get("vacationRegistration") or {}
        return AulaVacationRequestDetail(
            response_id=parse._parse_int(answer.get("vacationRegistrationResponseId")),
            child_id=parse._parse_int(answer.get("childId")),
            start_date=parse._parse_date(request.get("startDate")),
            end_date=parse._parse_date(request.get("endDate")),
            response_deadline=parse._day(request.get("responseDeadline")),
            is_presence_times_required=parse._parse_bool(request.get("isPresenceTimesRequired")),
            missing_answer=parse._parse_bool(request.get("isMissingAnswer")),
            comment=answer.get("comment") or None,
            days=[
                AulaVacationDay(
                    day=parse._parse_date(day.get("date")),
                    is_coming=parse._parse_nullable_bool(day.get("isComing")),
                    entry_time=parse._clock(day.get("entryTime")),
                    exit_time=parse._clock(day.get("exitTime")),
                )
                for day in answer.get("days") or []
            ],
        )

    @staticmethod
    def _day(value: Any) -> date | None:
        """A date, None for none or an empty text."""
        return AulaVacationParser._parse_nullable_date(value or None)

    @staticmethod
    def _clock(value: Any) -> time | None:
        """A time of day, None for none or an empty text, as Aula sends a time not given."""
        return AulaVacationParser._parse_nullable_time(value or None, fix_timezone=False)
