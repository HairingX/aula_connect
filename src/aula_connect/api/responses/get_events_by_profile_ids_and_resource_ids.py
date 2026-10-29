"""Aula's answer to calendar.getEventsByProfileIdsAndResourceIds."""

import datetime
from typing import List, TypedDict
from typing import List
from datetime import datetime
from typing_extensions import NotRequired

from .common_data import AulaStatusData

class AulaAnswerData(TypedDict):
    """A time chosen in a time slot."""
    concerningProfileId: int
    id: int
    instProfileId: int
    selectedTimeSlotIndex: int

class AulaTimeSlotIndexData(TypedDict):
    """A time to choose in a time slot."""
    endTime: datetime
    startTime: datetime

class AulaTimeSlotDetailData(TypedDict):
    """A time slot."""
    answers: List[AulaAnswerData]
    endDate: datetime
    id: int
    startDate: datetime
    timeSlotIndexes: List[AulaTimeSlotIndexData]

class AulaTimeSlotData(TypedDict):
    """The time slots of an event."""
    # childRequired is left out: Aula's website reads the time slots instead.
    timeSlots: List[AulaTimeSlotDetailData]

class AulaLessonParticipantData(TypedDict):
    """A teacher of a lesson."""
    participantRole: str
    teacherId: int
    teacherInitials: str
    teacherName: str

class AulaLessonData(TypedDict):
    """The lesson an event is."""
    lessonId: str
    lessonStatus: str
    participants: List[AulaLessonParticipantData]

class AulaPrimaryResourceData(TypedDict):
    """The resource an event uses, such as a room."""
    id: int
    name: str

class AulaEventData(TypedDict):
    """A calendar event."""
    allDay: bool
    belongsToProfiles: List[int]
    createdDateTime: datetime
    endDateTime: datetime
    hasAttachments: bool
    id: int
    lesson: NotRequired[AulaLessonData | None]
    primaryResource: NotRequired[AulaPrimaryResourceData | None]
    repeating: NotRequired[str | None]
    requiresNewAnswer: bool
    responseDeadline: NotRequired[datetime | None]
    responseRequired: bool
    responseStatus: NotRequired[str | None]
    startDateTime: datetime
    timeSlot: NotRequired[AulaTimeSlotData | None]
    title: str
    type: str

class AulaGetEventsByProfileIdsAndResourceIdsResponse(TypedDict):
    """The answer, with the events."""
    data: List[AulaEventData]
    status: AulaStatusData
    version: int