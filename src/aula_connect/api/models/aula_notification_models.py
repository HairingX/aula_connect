"""Aula's notifications, one model for each area of Aula they come from."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import List, Union

class NotificationEventType(StrEnum):
    """What happened, as a notification says."""
    CALENDAR_INVITED_TO_EVENT_RESPONSE_REQUIRED = "InvitedToEventResponseRequired"
    MEDIA_ADDED_TO_ALBUM = "MediaAddedToAlbum"
    MEDIA_NEW = "NewMedia"
    MESSAGE_NEW_PRIVATE_INBOX = "NewMessagePrivateInbox"
    POSTS_SHARED_WITH_ME = "PostSharedWithMe"

class NotificationType(StrEnum):
    """How Aula shows a notification."""
    ALERT = "Alert"
    BADGE = "Badge"

class NotificationArea(StrEnum):
    """The area of Aula a notification comes from."""
    ALBUM = "Album"
    CALENDAR = "Calendar"
    GALLERY = "Gallery"
    MESSAGES = "Messages"
    POSTS = "Posts"
    PRESENCE = "Presence"

@dataclass
class AulaNotificationBase:
    """What every notification has."""
    notification_area: str
    notification_event_type: str
    notification_id: str
    notification_type: str
    expires: datetime
    triggered: datetime

@dataclass
class AulaAlbumNotification(AulaNotificationBase):
    """A notification of media added to an album."""
    album_id: int
    institution_code: str
    institution_profile_id: int
    media_id: int
    related_institution: str
    NOTIFICATION_AREA:NotificationArea = NotificationArea.ALBUM

@dataclass
class AulaCalendarEventNotification(AulaNotificationBase):
    """A notification of a calendar event, such as an invitation to answer."""
    end_datetime: datetime
    event_id: int
    institution_code: str
    institution_profile_id: int
    is_all_day_event: bool
    start_datetime: datetime
    title: str
    NOTIFICATION_AREA:NotificationArea = NotificationArea.CALENDAR

@dataclass
class AulaGalleryNotification(AulaNotificationBase):
    """A notification of new media in the gallery."""
    album_id: int
    institution_code: str
    institution_profile_id: int
    media_ids: List[int]
    related_institution: str
    NOTIFICATION_AREA:NotificationArea = NotificationArea.GALLERY

@dataclass
class AulaMessageNotification(AulaNotificationBase):
    """A notification of a new message."""
    # NOTE (issue #10): best-guess mapping pending real-world verification.
    # The real Aula folder id is documented as Thread.folderId (int|null) on
    # message threads; it is NOT confirmed to exist on the notification payload
    # (the captured notifications response was empty). Sourced from "folderId"
    # and parsed nullable + crash-safe, so it is None when absent rather than
    # breaking the whole notification fetch.
    folder_id: int | None
    institution_code: str
    institution_profile_id: int
    message_text: str
    related_institution: str
    sender_name: str
    thread_id: int
    NOTIFICATION_AREA:NotificationArea = NotificationArea.MESSAGES

@dataclass
class AulaPostNotification(AulaNotificationBase):
    """A notification of a post shared with the user."""
    institution_code: str
    institution_profile_id: int
    title: str
    NOTIFICATION_AREA:NotificationArea = NotificationArea.POSTS


@dataclass
class AulaPresenceNotification(AulaNotificationBase):
    """A notification about presence, such as a vacation registration to answer."""
    end_datetime: datetime
    institution_code: str
    institution_profile_id: int
    is_presence_times_required: bool
    message_text: str
    related_child_institution_profile_id: int
    related_child_name: str
    response_deadline: datetime
    start_datetime: datetime
    vacation_registration_response_id: int
    vacation_request_name: str
    NOTIFICATION_AREA:NotificationArea = NotificationArea.PRESENCE


AULA_NOTIFICATION_TYPES = Union[AulaAlbumNotification, AulaCalendarEventNotification, AulaGalleryNotification, AulaMessageNotification, AulaPostNotification, AulaPresenceNotification]