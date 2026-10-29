"""Tests of reading Aula's answers into the models, with made-up answers."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from aula_connect.api.models import constants
from aula_connect.api.models.aula_calendar_parser import AulaCalendarParser
from aula_connect.api.models.aula_message_thread_parser import AulaMessageThreadParser
from aula_connect.api.models.aula_newsletter_parser import AulaNewsletterParser
from aula_connect.api.models.aula_notification_models import (
    AulaAlbumNotification,
    AulaCalendarEventNotification,
    AulaGalleryNotification,
    AulaMessageNotification,
    AulaPostNotification,
    AulaPresenceNotification,
)
from aula_connect.api.models.aula_notification_parser import AulaNotificationParser
from aula_connect.api.models.aula_profile_parser import AulaProfileParser

COMMON: dict[str, object] = {
    "expires": "2027-01-10T23:59:59+00:00",
    "notificationEventType": "Event",
    "notificationId": "Event:1:Badge",
    "notificationType": "Badge",
    "triggered": "2027-01-03T10:22:30+00:00",
    "institutionCode": "S1",
    "institutionProfileId": 11,
}


def _notification(area: str, **fields: object) -> Any:
    return {**COMMON, "notificationArea": area, **fields}


def test_each_area_of_notification_is_read_into_its_own_model() -> None:
    notifications = AulaNotificationParser.parse_notification_response(
        cast(
            Any,
            {
                "data": [
                    _notification("Calendar", eventId=7, title="Trip", isAllDayEvent=True, startTime="2027-01-05T08:00:00+00:00", endTime="2027-01-05T15:00:00+00:00"),
                    _notification("Messages", threadId=5, senderName="Teacher", messageText="Hello", relatedInstitution="School"),
                    _notification("Album", albumId=3, mediaId=4, relatedInstitution="School"),
                    _notification("Gallery", albumId=3, mediaIds=[4, 5], relatedInstitution="School"),
                    _notification("Posts", postTitle="News"),
                    _notification(
                        "Presence",
                        startDate="2027-04-14T00:00:00+00:00",
                        endDate="2027-04-16T23:59:00+00:00",
                        responseDeadline="2027-03-10T23:59:59+00:00",
                        isPresenceTimesRequired=True,
                        noteToGuardians="Before Easter",
                        relatedChildInstitutionProfileId=12,
                        relatedChildName="Alma",
                        vacationRegistrationResponseId=99,
                        vacationRequestName="Easter",
                    ),
                ]
            },
        )
    )
    calendar, message, album, gallery, post, presence = notifications
    assert isinstance(calendar, AulaCalendarEventNotification) and (calendar.event_id, calendar.title, calendar.is_all_day_event) == (7, "Trip", True)
    assert isinstance(message, AulaMessageNotification) and (message.thread_id, message.sender_name) == (5, "Teacher")
    assert isinstance(album, AulaAlbumNotification) and (album.album_id, album.media_id) == (3, 4)
    assert isinstance(gallery, AulaGalleryNotification) and gallery.media_ids == [4, 5]
    assert isinstance(post, AulaPostNotification) and post.title == "News"
    assert isinstance(presence, AulaPresenceNotification) and (presence.related_child_name, presence.vacation_request_name) == ("Alma", "Easter")
    assert presence.start_datetime.date() == date(2027, 4, 14)


def test_no_notifications_read_as_none() -> None:
    assert AulaNotificationParser.parse_notification_response(None) == []
    assert AulaNotificationParser.parse_notifications(None) == []
    assert AulaNotificationParser.parse_notification(None) is None
    for parse in (
        AulaNotificationParser.parse_calendar_event,
        AulaNotificationParser.parse_message,
        AulaNotificationParser.parse_post,
        AulaNotificationParser.parse_presence,
        AulaNotificationParser.parse_album,
        AulaNotificationParser.parse_gallery,
    ):
        assert parse(None) is None


def test_a_notification_not_known_or_not_readable_is_left_out_without_logging_it(caplog: pytest.LogCaptureFixture) -> None:
    notifications = [
        _notification("Vacation", messageText="Alma Example is ill"),
        _notification("Calendar", eventId="Alma Example"),
        _notification("Posts", postTitle="News"),
    ]
    with caplog.at_level(logging.WARNING):
        parsed = AulaNotificationParser.parse_notifications(cast(Any, notifications))
    assert "Alma Example" not in caplog.text
    assert [type(notification) for notification in parsed] == [AulaPostNotification]
    assert "'Vacation' (Event) is unknown" in caplog.text
    assert "Failed to parse a notification, skipping it: ValueError" in caplog.text


def test_a_calendar_event_is_read_with_its_lesson_resource_and_time_slots() -> None:
    event = {
        "allDay": False,
        "belongsToProfiles": ["11"],
        "createdDateTime": "2026-12-01T10:00:00+00:00",
        "endDateTime": "2027-01-05T09:00:00+00:00",
        "hasAttachments": False,
        "id": 7,
        "requiresNewAnswer": False,
        "responseRequired": True,
        "startDateTime": "2027-01-05T08:00:00+00:00",
        "title": "Parents' meeting",
        "type": "lesson",
        "lesson": {
            "lessonId": "L1",
            "lessonStatus": "normal",
            "participants": [{"participantRole": "primaryTeacher", "teacherId": 3, "teacherInitials": "TT", "teacherName": "Teacher"}],
        },
        "primaryResource": {"id": 2, "name": "Room 2"},
        "timeSlot": {
            "timeSlots": [
                {
                    "answers": [{"concerningProfileId": 11, "id": 1, "instProfileId": 21, "selectedTimeSlotIndex": 0}],
                    "endDate": "2027-01-05T09:00:00+00:00",
                    "id": 4,
                    "startDate": "2027-01-05T08:00:00+00:00",
                    "timeSlotIndexes": [{"startTime": "2027-01-05T08:00:00+00:00", "endTime": "2027-01-05T08:15:00+00:00"}],
                }
            ]
        },
    }
    [parsed] = AulaCalendarParser.parse_calendar_event_response(cast(Any, {"data": [event]}))
    assert parsed.belongs_to_profiles == [11]
    assert parsed.lesson is not None and [participant.teacher_name for participant in parsed.lesson.participants] == ["Teacher"]
    assert parsed.primary_resource is not None and parsed.primary_resource.name == "Room 2"
    assert parsed.time_slot is not None
    [slot] = parsed.time_slot.time_slots
    assert [answer.selected_time_slot_index for answer in slot.answers] == [0]
    assert [index.end_datetime - index.start_datetime for index in slot.time_slot_indexes] == [timedelta(minutes=15)]


def test_calendar_parts_aula_leaves_out_read_as_none() -> None:
    assert AulaCalendarParser.parse_calendar_event_response(None) == []
    for parse_list in (
        AulaCalendarParser.parse_calendar_events,
        AulaCalendarParser.parse_calendar_event_resources,
        AulaCalendarParser.parse_calendar_event_lesson_participants,
        AulaCalendarParser.parse_calendar_event_time_slot_entry_indexes,
        AulaCalendarParser.parse_calendar_event_time_slot_entry_answers,
        AulaCalendarParser.parse_calendar_event_time_slot_entries,
    ):
        assert parse_list(None) == []
    assert [resource.id for resource in AulaCalendarParser.parse_calendar_event_resources(cast(Any, [{"id": 2, "name": "Room"}, None]))] == [2]
    for parse in (
        AulaCalendarParser.parse_calendar_event_lesson_participant,
        AulaCalendarParser.parse_calendar_event_lesson,
        AulaCalendarParser.parse_calendar_event_time_slot,
        AulaCalendarParser.parse_calendar_event_time_slot_entry_index,
        AulaCalendarParser.parse_calendar_event_time_slot_entry_answer,
        AulaCalendarParser.parse_calendar_event_time_slot_entry,
    ):
        assert parse(None) is None


CONTACT = {"answerDirectlyName": "Teacher", "fullName": "Teacher Example", "metadata": "School"}


def test_a_message_is_read_with_its_sender_and_text() -> None:
    message = {
        "canReplyToMessage": True,
        "hasAttachments": False,
        "id": "m1",
        "messageType": "Message",
        "sendDateTime": "2027-01-05T08:00:00+00:00",
        "sender": CONTACT,
        "text": {"html": "<p>Hi</p>"},
    }
    [parsed] = AulaMessageThreadParser.parse_messages_response(cast(Any, {"data": {"messages": [message]}}))
    assert parsed.sender is not None
    assert (parsed.id, parsed.sender.full_name, parsed.can_reply_to_message) == ("m1", "Teacher Example", True)
    assert parsed.text is not None and parsed.text.html == "<p>Hi</p>"


def test_the_children_a_thread_regards_are_read() -> None:
    children = AulaMessageThreadParser.parse_message_thread_regarding_children(
        cast(Any, [{"displayName": "Alma Example", "profileId": 101, "shortName": "AE"}])
    )
    assert [(child.display_name, child.profile_id) for child in children] == [("Alma Example", 101)]


def test_messages_aula_leaves_out_read_as_none() -> None:
    assert AulaMessageThreadParser.parse_messages_response(None) == []
    assert AulaMessageThreadParser.parse_messages(None) == []
    assert AulaMessageThreadParser.parse_message_threads_response(None) == []
    assert AulaMessageThreadParser.parse_message_threads(None) == []
    assert AulaMessageThreadParser.parse_message_thread(None) is None
    assert AulaMessageThreadParser.parse_message_thread_regarding_children(None) == []
    assert AulaMessageThreadParser.parse_message_contacts(None) == []


@pytest.mark.parametrize(
    "parse",
    [
        AulaMessageThreadParser.parse_message_contact,
        AulaMessageThreadParser.parse_message_thread_regarding_child,
        AulaMessageThreadParser.parse_message,
        AulaMessageThreadParser.parse_message_preview,
    ],
)
def test_a_part_a_message_cannot_be_without_fails_to_read(parse: Any) -> None:
    with pytest.raises(ValueError):
        parse(None)


def test_a_profile_picture_is_read() -> None:
    picture = AulaProfileParser.parse_picture(
        cast(Any, {"bucket": "b", "id": 5, "isImageScalingPending": False, "key": "k", "url": "https://example.com/p.jpg"})
    )
    assert picture is not None and (picture.id, picture.url) == (5, "https://example.com/p.jpg")
    assert AulaProfileParser.parse_picture(None) is None


def test_a_childs_location_is_read_with_its_dates_and_times() -> None:
    [overview] = AulaProfileParser.parse_daily_overview_response(
        cast(
            Any,
            {
                "data": [
                    {
                        "id": 1,
                        "status": 3,
                        "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"},
                        "location": {
                            "id": 4,
                            "name": "Library",
                            "description": "Reading",
                            "symbol": "book",
                            "startDate": "2027-01-05",
                            "startTime": "08:30:00",
                            "endDate": "2027-01-05",
                            "endTime": "10:00:00",
                        },
                    }
                ]
            },
        )
    )
    assert overview.location is not None
    assert (overview.location.name, overview.location.start_datetime, overview.location.end_datetime) == (
        "Library",
        datetime(2027, 1, 5, 8, 30),
        datetime(2027, 1, 5, 10, 0),
    )


def test_a_location_without_times_is_read_from_its_dates_and_one_without_dates_has_none() -> None:
    whole_day = AulaProfileParser.parse_location(cast(Any, {"name": "Trip", "startDate": "2027-01-05", "endDate": "2027-01-06"}))
    undated = AulaProfileParser.parse_location(cast(Any, {"name": "Garden"}))
    assert whole_day is not None and (whole_day.start_datetime, whole_day.end_datetime) == (datetime(2027, 1, 5), datetime(2027, 1, 6))
    assert undated is not None and (undated.start_datetime, undated.end_datetime) == (None, None)
    assert AulaProfileParser.parse_location(None) is None


def test_a_newsletter_without_a_name_or_content_is_left_out() -> None:
    week = datetime(2026, 12, 28, tzinfo=timezone.utc).date()
    newsletters = AulaNewsletterParser.parse_response(
        cast(
            Any,
            {
                "personer": [
                    {"navn": "", "institutioner": [{"institution": "School", "ugebreve": [{"indhold": "<p>Lost</p>"}]}]},
                    {"navn": "Alma", "institutioner": [{"institution": "School", "ugebreve": [{"indhold": ""}, {"indhold": "<p>News</p>"}]}]},
                ]
            },
        ),
        week,
    )
    assert [(letter.child_name, [item.content_html for item in letter.newsletters]) for letter in newsletters] == [("Alma", ["<p>News</p>"])]


def test_the_labels_are_in_the_language_set_and_in_danish_for_one_not_known() -> None:
    try:
        constants.set_language("en")
        assert constants.get_label("substitute") == "Substitute"
        constants.set_language("xx")
        assert constants.get_label("substitute") == "Vikar"
        assert constants.get_label("no such label") == "no such label"
    finally:
        constants.set_language("da")
