"""Tests of reading Aula through its API and its widgets, against the simulated Aula."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timezone
from typing import Any

import aiohttp
import pytest

from aula_connect.api.aula_errors import AulaCredentialError
from aula_connect.api.aula_proxy_client import AulaProxyClient
from aula_connect.api.models.constants import AulaWidgetId
from aula_connect.testing import SimulatedAulaApi

START = datetime(2026, 12, 28, tzinfo=timezone.utc)
END = datetime(2027, 1, 4, tzinfo=timezone.utc)


def _read[T](arrange: Callable[[SimulatedAulaApi], None], act: Callable[[AulaProxyClient], Awaitable[T]]) -> tuple[T, SimulatedAulaApi]:
    async def run() -> tuple[T, SimulatedAulaApi]:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            arrange(aula)
            client = aula.point(AulaProxyClient(session, aula.access_token))
            await client.login()
            return await act(client), aula

    return asyncio.run(run())


def _nothing(aula: SimulatedAulaApi) -> None:
    return None


def test_login_reads_the_profiles_children_widgets_and_main_groups() -> None:
    async def login(client: AulaProxyClient) -> Any:
        return client._login_result

    result, aula = _read(_nothing, login)
    [profile] = result.profiles
    [child] = profile.children
    assert (profile.user_id, child.first_name, child.user_id, child.main_group.name) == ("pat", "Alma", "alma", "3A")
    assert [widget.widget_id for widget in result.widgets] == ["0001", "0004", "0029"]
    assert aula.requests[:3] == ["profiles.getProfilesByLogin", "profiles.getProfileContext", "profiles.getProfileMasterData"]


def test_a_token_aula_refuses_asks_for_a_new_login() -> None:
    async def run() -> None:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession() as session:
            await aula.point(AulaProxyClient(session, "not-the-token")).login()

    with pytest.raises((AulaCredentialError, ConnectionRefusedError)):
        asyncio.run(run())


def test_the_daily_overview_says_who_is_checked_in(caplog: pytest.LogCaptureFixture) -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.daily_overviews = [
            {
                "id": 1,
                "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"},
                "status": 3,
                "checkInTime": "08:05:00",
                "exitWith": "Grandma",
            }
        ]

    async def act(client: AulaProxyClient) -> Any:
        assert client._login_result is not None
        return await client.get_daily_overviews(client._login_result.profiles)

    [overview], _ = _read(arrange, act)
    assert (overview.status, overview.check_in_time, overview.exit_with) == (3, time(8, 5), "Grandma")
    assert "Unable to retrieve presence" not in caplog.text


def test_a_child_with_no_presence_is_logged_once_until_it_has_one_and_when_it_has(caplog: pytest.LogCaptureFixture) -> None:
    overview: dict[str, object] = {"id": 1, "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"}, "status": 3}

    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        assert client._login_result is not None
        nothing: list[dict[str, object]] = []
        for overviews in (nothing, nothing, [overview], nothing):
            aula.daily_overviews = overviews
            await client.get_daily_overviews(client._login_result.profiles)

    async def run() -> None:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            client = aula.point(AulaProxyClient(session, aula.access_token))
            await client.login()
            await act(aula, client)

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert caplog.text.count("Unable to retrieve presence") == 2
    assert caplog.text.count("Aula gives presence data for a child again") == 1


def test_the_calendar_is_read_with_the_csrf_token() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.events = [
            {
                "allDay": False,
                "belongsToProfiles": [11],
                "createdDateTime": "2026-12-01T08:00:00+00:00",
                "startDateTime": "2026-12-29T08:00:00+00:00",
                "endDateTime": "2026-12-29T09:00:00+00:00",
                "hasAttachments": False,
                "id": 7,
                "requiresNewAnswer": False,
                "responseRequired": False,
                "title": "Math",
                "type": "lesson",
            }
        ]

    async def act(client: AulaProxyClient) -> Any:
        assert client._login_result is not None
        return await client.get_calendar_events(client._login_result.profiles[0].institution_profiles, START, END)

    [event], aula = _read(arrange, act)
    assert (event.id, event.title) == (7, "Math")
    assert aula.requests[-1] == "calendar.getEventsByProfileIdsAndResourceIds"


def test_birthdays_threads_and_notifications_are_read() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.birthdays = [{"institutionProfileId": 31, "birthday": "2017-01-03", "institutionCode": "S1", "name": "Bo", "mainGroupName": "3A"}]
        aula.threads = [
            {
                "creator": {"answerDirectlyName": "Teacher", "fullName": "Teacher", "metadata": ""},
                "extraRecipientsCount": 0,
                "id": 5,
                "institutionCode": "S1",
                "isArchived": False,
                "isThreadOrSubscriptionDeleted": False,
                "latestMessage": {"id": "m1", "sendDateTime": "2026-12-28T08:00:00+00:00", "text": {"html": "<p>Hi</p>"}},
                "marked": False,
                "muted": False,
                "read": False,
                "recipients": [],
                "regardingChildren": [],
                "sensitive": False,
                "startedTime": "2026-12-28T08:00:00+00:00",
                "subject": "Trip",
            }
        ]

    async def act(client: AulaProxyClient) -> tuple[Any, Any, Any]:
        assert client._login_result is not None
        children = client._login_result.profiles[0].children
        return (
            await client.get_birthday_events(children, START, END),
            await client.get_message_threads(),
            await client.get_notifications(children),
        )

    (birthdays, threads, notifications), _ = _read(arrange, act)
    assert [(birthday.full_name, birthday.birthday_date) for birthday in birthdays] == [("Bo", date(2017, 1, 3))]
    assert [thread.subject for thread in threads] == ["Trip"]
    assert notifications == []


def test_a_childs_birthdays_are_those_aula_ties_to_it_or_to_no_child() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        birthday = {"institutionProfileId": 31, "birthday": "2017-01-03", "institutionCode": "S1", "mainGroupName": "3A"}
        aula.birthdays = [
            {**birthday, "name": "Bo", "relatedChildrenIds": [11]},
            {**birthday, "name": "Liv", "relatedChildrenIds": [12]},
            {**birthday, "name": "Max"},
        ]

    async def act(client: AulaProxyClient) -> Any:
        assert client._login_result is not None
        return await client.get_birthday_events(client._login_result.profiles[0].children, START, END)

    birthdays, _ = _read(arrange, act)
    assert [(birthday.full_name, birthday.related_children_ids) for birthday in birthdays] == [("Bo", [11]), ("Max", [])]


def test_the_widgets_are_read_with_their_tokens() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.weekly_plans = [
            {
                "id": 1,
                "name": "Alma",
                "unilogin": "alma",
                "weekPlan": [{"date": "2026-12-29", "tasks": [{"id": 4, "type": "task", "author": "", "group": "3A", "pill": "Danish", "content": "Read"}]}],
            }
        ]
        aula.easyiq_events = [
            {"start": "2026/12/29 08:00", "end": "2026/12/29 09:00", "itemType": "5", "title": "Gym", "ownername": "Coach", "description": ""}
        ]
        aula.newsletters = [{"navn": "Alma", "institutioner": [{"institution": "School", "ugebreve": [{"indhold": "<p>News</p>"}]}]}]

    async def act(client: AulaProxyClient) -> tuple[Any, Any, Any]:
        assert client._login_result is not None
        children = client._login_result.profiles[0].children
        return (
            await client.get_weekly_plans(children, START, END),
            await client.get_easyiq_weekly_plans(children, START, END),
            await client.get_newsletters(children, START, END),
        )

    (plans, easyiq, newsletters), aula = _read(arrange, act)
    assert [task.content for plan in plans for day in plan.daily_plans for task in day.tasks] == ["Read"]
    assert [event.title for plan in easyiq for day in plan.daily_plans for event in day.events] == ["Gym"]
    assert [letter.content_html for weekly in newsletters for letter in weekly.newsletters] == ["<p>News</p>"]
    assert aula.requests.count("aulaToken.getAulaToken") == 3


def test_a_widget_the_institution_does_not_have_is_not_read() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.widgets = []

    async def act(client: AulaProxyClient) -> Any:
        assert client._login_result is not None
        assert not client.has_widget(AulaWidgetId.WEEKPLAN_PARENTS)
        return await client.get_weekly_plans(client._login_result.profiles[0].children, START, END)

    plans, aula = _read(arrange, act)
    assert plans == []
    assert "meebook" not in aula.requests
