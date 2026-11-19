"""Reading Aula's answer to calendar.getEventById into the model."""

from typing import List

from ..responses.get_event_by_id_response import (
    AulaEventDetailData,
    AulaEventDetailResourceData,
    AulaEventDetailTimeSlotData,
    AulaGetEventByIdResponse,
)
from .aula_calendar_models import AulaCalendarEventTimeSlotEntryIndex
from .aula_event_detail_models import AulaEventBooking, AulaEventDetail, AulaEventInvitation
from .aula_parser import AulaParser


class AulaEventDetailParser(AulaParser):
    """Reads an event as Aula tells it alone."""

    @staticmethod
    def parse_response(data: AulaGetEventByIdResponse) -> AulaEventDetail:
        """The event in Aula's answer."""
        return AulaEventDetailParser.parse_event(data["data"])

    @staticmethod
    def parse_event(data: AulaEventDetailData) -> AulaEventDetail:
        """An event as Aula tells it alone."""
        parse = AulaEventDetailParser
        creator = data.get("creator") or {}
        return AulaEventDetail(
            id=parse._parse_int(data.get("id")),
            title=parse._parse_str(data.get("title")),
            type=parse._parse_str(data.get("type")),
            all_day=parse._parse_bool(data.get("allDay")),
            start_datetime=parse._parse_datetime(data.get("startDateTime"), fix_timezone=False),
            end_datetime=parse._parse_datetime(data.get("endDateTime"), fix_timezone=False),
            description_html=parse._parse_str((data.get("description") or {}).get("html")),
            institution_name=parse._parse_str(data.get("institutionName")),
            location=parse._location(data.get("primaryResource"), data.get("primaryResourceText")),
            creator_name=parse._parse_str(creator.get("name")),
            creator_role=parse._parse_str(creator.get("institutionRole")),
            co_organizer_names=[parse._parse_str(organizer["instProfile"].get("fullName")) for organizer in data.get("coOrganizers", [])],
            invited_group_names=[parse._parse_str(invited["group"].get("name")) for invited in data.get("inviteeGroups", [])],
            invitations=[
                AulaEventInvitation(
                    institution_profile_id=parse._parse_int(invitee["instProfile"].get("id")),
                    response=parse._parse_str(invitee.get("responseType")),
                    answered_at=parse._parse_nullable_datetime(invitee.get("responseDateTime"), fix_timezone=False),
                )
                for invitee in data.get("invitees", [])
            ],
            response_required=parse._parse_bool(data.get("responseRequired")),
            response_deadline=parse._parse_nullable_datetime(data.get("responseDeadline"), fix_timezone=False),
            deadline_exceeded=parse._parse_bool(data.get("isDeadlineExceeded")),
            attachment_count=len(data.get("attachments", [])),
            private=parse._parse_bool(data.get("private")),
            deleted=parse._parse_bool(data.get("isDeleted")),
            bookings=parse._bookings(data.get("timeSlot")),
        )

    @staticmethod
    def _location(resource: AulaEventDetailResourceData | None, text: str | None) -> str | None:
        if resource:
            return AulaEventDetailParser._parse_str(resource.get("name"))
        return text or None

    @staticmethod
    def _bookings(data: AulaEventDetailTimeSlotData | None) -> List[AulaEventBooking]:
        parse = AulaEventDetailParser
        bookings: List[AulaEventBooking] = []
        for slot in (data or {}).get("timeSlots", []):
            times = [
                AulaCalendarEventTimeSlotEntryIndex(
                    start_datetime=parse._parse_datetime(index.get("startTime"), fix_timezone=False),
                    end_datetime=parse._parse_datetime(index.get("endTime"), fix_timezone=False),
                )
                for index in slot.get("timeSlotIndexes", [])
            ]
            location = parse._location(slot.get("primaryResource"), slot.get("primaryResourceText"))
            for answer in slot.get("answers", []):
                index = parse._parse_int(answer.get("selectedTimeSlotIndex"))
                if 0 <= index < len(times):
                    bookings.append(
                        AulaEventBooking(
                            concerning_profile_id=parse._parse_int(answer["concerningProfile"].get("id")),
                            institution_profile_id=parse._parse_int(answer["instProfile"].get("id")),
                            time=times[index],
                            location=location,
                        )
                    )
        return bookings
