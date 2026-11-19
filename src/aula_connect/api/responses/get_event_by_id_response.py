"""Aula's answer to calendar.getEventById, as far as it is read."""

from typing import List, TypedDict

from typing_extensions import NotRequired

from .common_data import AulaStatusData


class AulaEventProfileData(TypedDict):
    """Someone an event concerns, by their institution profile."""
    id: int


class AulaEventDetailAnswerData(TypedDict):
    """A time chosen in a time slot, and whom for."""
    concerningProfile: AulaEventProfileData
    id: int
    instProfile: AulaEventProfileData
    selectedTimeSlotIndex: int


class AulaEventDetailTimeSlotIndexData(TypedDict):
    """A time to choose in a time slot."""
    endTime: str
    startTime: str


class AulaEventDetailResourceData(TypedDict):
    """A room or other resource."""
    name: str


class AulaEventDetailTimeSlotEntryData(TypedDict):
    """A time slot, with the times to choose and the times chosen."""
    answers: List[AulaEventDetailAnswerData]
    endDate: str
    id: int
    primaryResource: NotRequired[AulaEventDetailResourceData | None]
    primaryResourceText: NotRequired[str | None]
    startDate: str
    timeSlotIndexes: List[AulaEventDetailTimeSlotIndexData]


class AulaEventDetailTimeSlotData(TypedDict):
    """The time slots of an event."""
    timeSlots: List[AulaEventDetailTimeSlotEntryData]


class AulaEventDescriptionData(TypedDict):
    """An event's description."""
    html: str


class AulaEventCreatorData(TypedDict):
    """Who created an event."""
    institutionRole: str
    name: str


class AulaEventCoOrganizerProfileData(TypedDict):
    """An employee who organises an event too."""
    fullName: str


class AulaEventCoOrganizerData(TypedDict):
    """An employee who organises an event too."""
    instProfile: AulaEventCoOrganizerProfileData


class AulaEventInviteeData(TypedDict):
    """Someone invited to an event, and their answer."""
    instProfile: AulaEventProfileData
    responseDateTime: NotRequired[str | None]
    responseType: str


class AulaEventGroupData(TypedDict):
    """A group."""
    name: str


class AulaEventInviteeGroupData(TypedDict):
    """A group invited to an event."""
    group: AulaEventGroupData


class AulaEventDetailData(TypedDict):
    """An event, with what is known of it alone."""
    allDay: bool
    attachments: List[object]
    coOrganizers: List[AulaEventCoOrganizerData]
    creator: NotRequired[AulaEventCreatorData | None]
    description: NotRequired[AulaEventDescriptionData | None]
    endDateTime: str
    id: int
    institutionName: str
    inviteeGroups: List[AulaEventInviteeGroupData]
    invitees: List[AulaEventInviteeData]
    isDeadlineExceeded: bool
    isDeleted: bool
    primaryResource: NotRequired[AulaEventDetailResourceData | None]
    primaryResourceText: NotRequired[str | None]
    private: bool
    responseDeadline: NotRequired[str | None]
    responseRequired: bool
    startDateTime: str
    timeSlot: NotRequired[AulaEventDetailTimeSlotData | None]
    title: str
    type: str


class AulaGetEventByIdResponse(TypedDict):
    """The answer, with the event."""
    data: AulaEventDetailData
    status: AulaStatusData
    version: int
