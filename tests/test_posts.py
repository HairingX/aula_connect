"""The news feed's posts, and the days and hours the institutions are open."""

from datetime import date, datetime, time, timezone

import pytest

from aula_connect import AulaClient
from aula_connect.api.models.aula_notification_parser import AulaNotificationParser
from aula_connect.api.responses.get_notifications_response import AulaNotificationData
from aula_connect.api.models.aula_post_parser import AulaPostParser
from aula_connect.api.responses.common_data import AulaStatusData
from aula_connect.api.responses.get_opening_hours_response import AulaGetClosedDaysResponse, AulaGetOpeningHoursResponse
from aula_connect.api.module import AulaClosedDay, AulaOpeningDay, AulaPost, AulaPosts, AulaProxyClient
from aula_connect.testing import SimulatedAulaApi

from test_capture import _client_run

MEDIA = {
    "id": 1,
    "name": "billede.jpg",
    "media": {"mediaType": "image", "largeThumbnailUrl": "https://files.example.org/stor.jpg", "file": {"url": "https://files.example.org/fil.jpg"}},
}
FILE = {"id": 2, "name": "", "file": {"name": "seddel.pdf", "url": "https://files.example.org/seddel.pdf"}}


def test_the_posts_are_read_with_the_guardian_s_and_the_children_s_ids_and_when_they_were_last_seen() -> None:
    async def act(client: AulaClient, aula: SimulatedAulaApi) -> tuple[AulaPosts, str]:
        aula.posts[0].update(isImportant=True, importantFrom="2026-11-23", importantTo="2026-11-27", attachments=[MEDIA, FILE])
        login = await client.login()
        return await client.get_posts(login.profiles, 5), client.api.recorder.exchanges()[-1].url

    posts, url = _client_run(act)
    assert "parent=profile" in url and "limit=5" in url
    assert "institutionProfileIds%5B%5D=21" in url or "institutionProfileIds[]=21" in url
    assert "institutionProfileIds[]=11" in url or "institutionProfileIds%5B%5D=11" in url
    assert posts.last_seen == datetime(2026, 11, 20, 8, tzinfo=timezone.utc)
    assert not posts.has_more
    [post] = posts.posts
    assert (post.id, post.title, post.html) == (501, "Juleklip fredag", "<p>Hele skolen klipper julepynt fredag.</p>")
    assert post.timestamp == datetime(2026, 11, 23, 8, tzinfo=timezone.utc)
    assert (post.is_important, post.important_from, post.important_to) == (True, date(2026, 11, 23), date(2026, 11, 27))
    assert (post.author, post.institution, post.groups) == ("Kontoret", "School", ["Hele skolen"])
    assert post.children == [11]
    assert [(a.name, a.url, a.thumbnail_url, a.is_media) for a in post.attachments] == [
        ("billede.jpg", "https://files.example.org/fil.jpg", "https://files.example.org/stor.jpg", True),
        ("seddel.pdf", "https://files.example.org/seddel.pdf", None, False),
    ]


def test_a_post_without_its_fields_is_read_with_none_and_nothing() -> None:
    post = AulaPostParser.parse_post({"id": 1})
    assert post == AulaPost(1, "", "", datetime.min, None, None, None, False, None, None, None, None, [], [], 0)
    assert AulaPostParser.parse_posts_response({"data": {}, "status": {"code": 0, "message": "OK"}, "version": 25}) == AulaPosts([], None, False)


def test_the_closed_days_and_the_hours_are_read_for_the_children_s_institutions() -> None:
    async def act(client: AulaClient, aula: SimulatedAulaApi) -> tuple[list[AulaClosedDay], list[AulaOpeningDay], list[str]]:
        children = AulaProxyClient.flatten_children((await client.login()).profiles)
        closed = await client.get_closed_days(children)
        hours = await client.get_opening_hours(children, date(2026, 12, 18), date(2026, 12, 21))
        return closed, hours, [exchange.url for exchange in client.api.recorder.exchanges()[-2:]]

    closed, hours, urls = _client_run(act)
    assert closed == [AulaClosedDay("S1", "Juleferie", date(2026, 12, 21), date(2027, 1, 1))]
    assert hours == [
        AulaOpeningDay("S1", date(2026, 12, 18), "general_opening_hours", time(6, 30), time(17)),
        AulaOpeningDay("S1", date(2026, 12, 21), "closed_day", None, None),
    ]
    assert [day.closed for day in hours] == [False, True]
    assert "institutionCodes%5B%5D=S1" in urls[0] or "institutionCodes[]=S1" in urls[0]
    assert "startDate=2026-12-18" in urls[1] and "endDate=2026-12-21" in urls[1]


def test_a_closed_day_without_a_start_or_an_end_and_no_children_read_nothing_or_the_one_day() -> None:
    status: AulaStatusData = {"code": 0, "message": "OK"}
    closed: AulaGetClosedDaysResponse = {
        "data": {
            "institutionClosedDays": [
                {"institutionCode": "S1", "closedDaysOverview": {"closedDays": [{"name": "Lukket", "startDate": "2026-12-24"}, {"name": "Uden dag"}]}}
            ]
        },
        "status": status,
    }
    assert AulaPostParser.parse_closed_days_response(closed) == [AulaClosedDay("S1", "Lukket", date(2026, 12, 24), date(2026, 12, 24))]
    hours: AulaGetOpeningHoursResponse = {"data": {"openingHoursOverviewDto": [{"openingHoursDto": [{"type": "x"}]}]}, "status": status}
    assert AulaPostParser.parse_opening_hours_response(hours) == []

    async def act(client: AulaClient, _aula: SimulatedAulaApi) -> tuple[list[AulaClosedDay], list[AulaOpeningDay]]:
        return await client.get_closed_days([]), await client.get_opening_hours([], date(2026, 1, 1), date(2026, 1, 2))

    assert _client_run(act) == ([], [])


def test_a_post_concerns_the_children_aula_relates_it_to_and_no_other_profile() -> None:
    post = AulaPostParser.parse_post({
        "id": 1,
        "relatedProfiles": [{"id": 11, "role": "child"}, {"id": 21, "role": "guardian"}, {"id": None, "role": "child"}, {"id": 12, "role": "child"}],
    })
    assert post.children == [11, 12]


def test_a_post_s_notification_names_the_post() -> None:
    base = AulaNotificationData(
        expires="2026-12-27T08:00:00+00:00",
        institutionCode="S1",
        institutionProfileId=21,
        notificationArea="Posts",
        notificationEventType="PostSharedWithMe",
        notificationId="PostSharedWithMe:501",
        notificationType="Badge",
        triggered="2026-11-27T08:00:00+00:00",
    )
    note = AulaNotificationParser.parse_post({**base, "postId": 501})
    assert note is not None and note.post_id == 501
    bare = AulaNotificationParser.parse_post(base)
    assert bare is not None and bare.post_id is None


def test_seen_notifications_are_deleted_in_aula_by_their_ids_and_the_guardian_s_profile() -> None:
    async def act(client: AulaClient, aula: SimulatedAulaApi) -> tuple[list[str], list[str]]:
        aula.notifications = [
            {"notificationId": "PostSharedWithMe:501", "institutionProfileId": 21, "notificationArea": "Posts", "postId": 501},
            {"notificationId": "NewMedia:9", "institutionProfileId": 21, "notificationArea": "Album", "albumId": 1, "mediaId": 9},
        ]
        children = AulaProxyClient.flatten_children((await client.login()).profiles)
        found = await client.get_notifications(children)
        await client.delete_notifications([note for note in found if note.notification_area == "Posts"])
        with pytest.raises(ValueError, match="No notification is given"):
            await client.delete_notifications([])
        return [str(note["notificationId"]) for note in aula.notifications], aula.requests

    left, requests = _client_run(act)
    assert left == ["NewMedia:9"]
    assert requests.count("Notifications.deleteNotifications") == 1
