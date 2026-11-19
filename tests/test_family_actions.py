"""Tests of what a guardian does in Aula - reporting sick, vacations, vacation requests, replies -
and of the child's picture, against the simulated Aula."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from collections.abc import Awaitable, Callable
from datetime import date, time as clock, timedelta
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.aula_errors import (
    AulaApiError,
    MethodRefusedError,
    NoSickReportRouteError,
    SickReportRouteNotSupportedError,
)
from aula_connect.api.aula_proxy_client import MESSAGE_MAX_LENGTH, _one_year_after
from aula_connect.api.models.aula_presence_parser import AulaPresenceParser
from aula_connect.api.module import (
    AulaChildProfile,
    AulaPresenceModuleType,
    AulaPresencePermission,
    AulaPresenceStatus,
    AulaSickReportRoute,
    AulaVacationDay,
)
from aula_connect.api.responses.get_presence_configuration_by_child_ids_response import AulaGetPresenceConfigurationByChildIdsResponse
from aula_connect.api.responses.get_vacation_announcements_by_children_response import AulaGetVacationAnnouncementsByChildrenResponse
from aula_connect.api.responses.get_vacation_registration_response_response import AulaGetVacationRegistrationResponseResponse
from aula_connect.api.responses.get_vacation_registrations_by_children_response import AulaGetVacationRegistrationsByChildrenResponse
from aula_connect.testing import SimulatedAulaApi

from response_types import mismatches

TODAY = date.today()
MONDAY = TODAY + timedelta(days=7 - TODAY.weekday())
"""The Monday of next week."""
KEY = b"a key for the tests"
TABULEX: dict[str, object] = {"widgetSupplier": "IST", "url": "https://tabulex.example/TabulexAulaLogin?school=1"}

Act = Callable[[AulaClient, AulaChildProfile], Awaitable[Any]]


def _run(arrange: Callable[[SimulatedAulaApi], None], act: Act) -> tuple[Any, SimulatedAulaApi, AulaClient]:
    async def run() -> tuple[Any, SimulatedAulaApi, AulaClient]:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            arrange(aula)
            client = AulaClient(
                session,
                access_token=aula.access_token,
                refresh_token="refresh",
                expires_at=time.time() + 3600,
                mitid_username="parent",
                login_client=AulaLoginClient(session, "parent"),
            )
            aula.point(client.api)
            [child] = (await client.login()).profiles[0].children
            return await act(client, child), aula, client

    return asyncio.run(run())


def _nothing(aula: SimulatedAulaApi) -> None:
    return None


def _overview(status: int) -> Callable[[SimulatedAulaApi], None]:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.daily_overviews = [{"id": 1, "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"}, "status": status}]

    return arrange


WRITES = {
    "presence.updateStatusByInstitutionProfileIds",
    "calendar.addVacation",
    "calendar.deleteEvent",
    "calendar.respondToVacationRegistrationRequest",
    "messaging.reply",
}


def _written(aula: SimulatedAulaApi) -> list[str]:
    return [method for method in aula.requests if method in WRITES]


# Reporting sick


def test_a_child_aulas_presence_module_lets_the_guardian_report_sick_is_reported_and_taken_back() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        [configuration] = await client.get_presence_configurations([child])
        route = await client.get_sick_report_route(child)
        await client.report_sick(child)
        [sick] = await client.get_daily_overviews((await client.login()).profiles)
        await client.undo_sick(child)
        [well] = await client.get_daily_overviews((await client.login()).profiles)
        return configuration, route, sick.status, well.status

    (configuration, route, sick, well), aula, _ = _run(_overview(AulaPresenceStatus.NOT_PRESENT), act)
    assert configuration.child_id == 11
    assert configuration.permission(AulaPresenceModuleType.REPORT_SICK) is AulaPresencePermission.EDITABLE
    assert configuration.permission(AulaPresenceModuleType.SLEEP) is AulaPresencePermission.DEACTIVATED
    assert (route, sick, well) == (AulaSickReportRoute.AULA, AulaPresenceStatus.SICK, AulaPresenceStatus.NOT_PRESENT)
    assert _written(aula) == ["presence.updateStatusByInstitutionProfileIds"] * 2


def test_taking_back_a_report_of_a_child_aula_does_not_tell_as_sick_sends_nothing() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match="not reported sick"):
            await client.undo_sick(child)

    _, aula, _ = _run(_overview(AulaPresenceStatus.PRESENT), act)
    assert _written(aula) == []


def test_a_child_reported_sick_through_tabulex_is_routed_there_and_refused_as_not_supported() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.presence_modules = {"report_sick": "readable"}
        aula.widgets.append("0101")
        aula.widget_fields["0101"] = TABULEX

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        route = await client.get_sick_report_route(child)
        with pytest.raises(SickReportRouteNotSupportedError) as raised:
            await client.report_sick(child)
        return route, raised.value.route

    (route, refused), aula, _ = _run(arrange, act)
    assert (route, refused) == (AulaSickReportRoute.TABULEX, "IST Tabulex")
    assert _written(aula) == []


@pytest.mark.parametrize(
    "widget",
    [{}, {"widgetSupplier": "IST", "url": "https://ist.example/other"}, {"widgetSupplier": "Other", "url": TABULEX["url"]}],
    ids=["no widget", "another IST widget", "another supplier"],
)
def test_a_child_with_no_route_known_cannot_be_reported_sick(widget: dict[str, object]) -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.presence_modules = {}
        aula.widgets.append("0101")
        aula.widget_fields["0101"] = widget

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        route = await client.get_sick_report_route(child)
        with pytest.raises(NoSickReportRouteError):
            await client.report_sick(child)
        return route

    route, aula, _ = _run(arrange, act)
    assert route is AulaSickReportRoute.NONE
    assert _written(aula) == []


def test_only_the_guardian_dashboard_counts_and_a_permission_aula_names_otherwise_is_deactivated() -> None:
    configuration = AulaPresenceParser.parse_configuration(
        {
            "uniStudentId": 11,
            "presenceConfiguration": {
                "dashboardModuleSettings": [
                    {"presenceDashboardContext": "employee_dashboard", "presenceModules": [{"moduleType": "vacation", "permission": "editable"}]},
                    {"presenceDashboardContext": "guardian_dashboard", "presenceModules": [{"moduleType": "report_sick", "permission": "writable"}]},
                ]
            },
        }
    )
    assert configuration.modules == {"report_sick": AulaPresencePermission.DEACTIVATED}
    assert not configuration.editable(AulaPresenceModuleType.VACATION)
    assert AulaPresenceParser.parse_configuration({"uniStudentId": 11}).modules == {}


# Vacations


def test_a_vacation_added_is_listed_and_deleted() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        await client.add_vacation([child, child], MONDAY, MONDAY + timedelta(days=4), "Hos mormor")
        listed = await client.get_vacations([child])
        await client.delete_vacation(listed[0].id)
        return listed, await client.get_vacations([child])

    ([vacation], after), aula, _ = _run(_nothing, act)
    assert (vacation.child_id, vacation.start_date, vacation.end_date, vacation.description, vacation.is_editable) == (
        11, MONDAY, MONDAY + timedelta(days=4), "Hos mormor", True,
    )
    assert after == []
    assert _written(aula) == ["calendar.addVacation", "calendar.deleteEvent"]


def test_a_vacation_of_one_day_a_year_long_and_from_today_is_taken() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        await client.add_vacation([child], TODAY, TODAY)
        await client.add_vacation([child], MONDAY, _one_year_after(MONDAY), "x" * 250)
        return [(vacation.start_date, vacation.end_date, vacation.description) for vacation in await client.get_vacations([child])]

    vacations, _, _ = _run(_nothing, act)
    assert vacations == [(TODAY, TODAY, None), (MONDAY, _one_year_after(MONDAY), "x" * 250)]


def test_a_year_after_the_29th_of_february_is_the_28th() -> None:
    assert _one_year_after(date(2028, 2, 29)) == date(2029, 2, 28)


@pytest.mark.parametrize(
    ("children", "start", "end", "comment", "message"),
    [
        (False, MONDAY, MONDAY, "", "No child"),
        (True, TODAY - timedelta(days=1), TODAY, "", "before today"),
        (True, MONDAY, MONDAY - timedelta(days=1), "", "ends before it starts"),
        (True, MONDAY, _one_year_after(MONDAY) + timedelta(days=1), "", "more than a year"),
        (True, MONDAY, MONDAY, "x" * 251, "longer than 250"),
    ],
    ids=["no child", "start in the past", "end before start", "more than a year", "comment too long"],
)
def test_a_vacation_the_portal_would_not_take_is_refused_and_nothing_sent(children: bool, start: date, end: date, comment: str, message: str) -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match=message):
            await client.add_vacation([child] if children else [], start, end, comment)

    _, aula, _ = _run(_nothing, act)
    assert _written(aula) == []


@pytest.mark.parametrize(("editable", "message"), [(None, "No vacation"), (False, "cannot be changed")])
def test_a_vacation_not_the_childrens_or_not_editable_is_not_deleted(editable: bool | None, message: str) -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        if editable is not None:
            aula.vacations = [{"vacationId": 4, "startDate": "2026-12-28", "endDate": "2026-12-28", "isEditable": editable, "childIds": [11]}]

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match=message):
            await client.delete_vacation(4)

    _, aula, _ = _run(arrange, act)
    assert _written(aula) == []


# Vacation requests

REQUEST: dict[str, object] = {
    "responseId": 501,
    "vacationRegistrationId": 50,
    "childId": 11,
    "title": "Juleferie",
    "startDate": MONDAY.isoformat(),
    "endDate": (MONDAY + timedelta(days=6)).isoformat(),
    "responseDeadline": (MONDAY - timedelta(days=1)).isoformat(),
    "noteToGuardian": "Sig til senest søndag",
    "isEditable": True,
    "isPresenceTimesRequired": True,
}


def _request(**fields: object) -> Callable[[SimulatedAulaApi], None]:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.vacation_requests = [{**REQUEST, **fields}]

    return arrange


def test_a_vacation_request_is_listed_read_and_answered() -> None:
    days = [
        AulaVacationDay(MONDAY + timedelta(days=1), False, clock(8), clock(15)),
        AulaVacationDay(MONDAY, True, clock(8), clock(15, 30)),
    ]

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        [before] = await client.get_vacation_requests([child])
        unanswered = await client.get_vacation_request(before.response_id)
        await client.answer_vacation_request(before.response_id, days, "Vi holder fri tirsdag")
        [after] = await client.get_vacation_requests([child])
        return before, unanswered, after, await client.get_vacation_request(before.response_id)

    (before, unanswered, after, answered), aula, _ = _run(_request(), act)
    assert (before.id, before.response_id, before.child_id, before.title, before.note_to_guardian) == (50, 501, 11, "Juleferie", "Sig til senest søndag")
    assert (before.start_date, before.end_date, before.response_deadline) == (MONDAY, MONDAY + timedelta(days=6), MONDAY - timedelta(days=1))
    assert before.missing_answer and before.answerable(TODAY) and before.is_presence_times_required
    assert not before.answerable(MONDAY)
    assert (unanswered.missing_answer, unanswered.days, unanswered.comment) == (True, [], None)
    assert not after.missing_answer
    assert (answered.response_id, answered.child_id, answered.comment, answered.missing_answer) == (501, 11, "Vi holder fri tirsdag", False)
    assert answered.days == [
        AulaVacationDay(MONDAY, True, clock(8), clock(15, 30)),
        AulaVacationDay(MONDAY + timedelta(days=1), False, None, None),
    ]
    assert aula.vacation_answers[501]["days"] == [
        {"date": MONDAY.isoformat(), "isComing": True, "entryTime": "08:00", "exitTime": "15:30"},
        {"date": (MONDAY + timedelta(days=1)).isoformat(), "isComing": False, "entryTime": "", "exitTime": ""},
    ]


def test_a_request_that_asks_for_no_times_is_answered_without_them() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        await client.answer_vacation_request(501, [AulaVacationDay(MONDAY, True, clock(8), clock(15))])

    _, aula, _ = _run(_request(isPresenceTimesRequired=False, responseDeadline=None), act)
    assert aula.vacation_answers[501]["days"] == [{"date": MONDAY.isoformat(), "isComing": True, "entryTime": "", "exitTime": ""}]


PAST_PERIOD = {"startDate": (TODAY - timedelta(days=14)).isoformat(), "responseDeadline": None}


@pytest.mark.parametrize(
    ("fields", "days", "message"),
    [
        ({"responseDeadline": (TODAY - timedelta(days=1)).isoformat()}, [AulaVacationDay(MONDAY, False)], "deadline"),
        ({}, [], "No day"),
        ({}, [AulaVacationDay(MONDAY, False), AulaVacationDay(MONDAY, True, clock(8), clock(9))], "twice"),
        ({}, [AulaVacationDay(MONDAY + timedelta(days=7), False)], "not in the request's period"),
        ({}, [AulaVacationDay(MONDAY + timedelta(days=5), False)], "no weekday"),
        (PAST_PERIOD, [AulaVacationDay(TODAY - timedelta(days=7 + TODAY.weekday()), False)], "has passed"),
        ({}, [AulaVacationDay(MONDAY, None)], "not answered"),
        ({}, [AulaVacationDay(MONDAY, True, clock(8))], "entry and exit"),
        ({}, [AulaVacationDay(MONDAY, True, clock(15), clock(8))], "entry time after"),
    ],
    ids=["deadline passed", "no day", "a day twice", "outside the period", "weekend", "past day", "unanswered", "no times", "entry after exit"],
)
def test_an_answer_the_portal_would_not_send_is_refused_and_nothing_sent(fields: dict[str, object], days: list[AulaVacationDay], message: str) -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match=message):
            await client.answer_vacation_request(501, days)

    _, aula, _ = _run(_request(**fields), act)
    assert _written(aula) == []


def test_a_vacation_request_aula_tells_nothing_of_is_not_answered() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        async def no_content(request: web.Request) -> web.Response:
            return web.Response(status=204)

        aula.answers["presence.getVacationRegistrationResponse"] = no_content

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match="tells nothing"):
            await client.answer_vacation_request(501, [AulaVacationDay(MONDAY, False)])

    _, aula, _ = _run(arrange, act)
    assert _written(aula) == []


def test_a_vacation_request_aula_does_not_know_is_its_error() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(AulaApiError, match="Aula code 40"):
            await client.get_vacation_request(999)

    _run(_nothing, act)


def test_a_read_for_no_child_asks_aula_nothing() -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        return await client.get_presence_configurations([]), await client.get_vacations([]), await client.get_vacation_requests([])

    found, aula, _ = _run(_nothing, act)
    assert found == ([], [], [])
    assert not [method for method in aula.requests if method.startswith("presence.")]


# Messages


def _thread(thread_id: int, children: list[int], latest: str) -> dict[str, object]:
    return {
        "id": thread_id,
        "creator": {"answerDirectlyName": "Lærer", "fullName": "Lærer", "metadata": "Skole"},
        "subject": f"Tråd {thread_id}",
        "regardingChildren": [{"displayName": "Alma", "profileId": profile_id, "shortName": "AE"} for profile_id in children],
        "recipients": [],
        "latestMessage": {"id": f"m{thread_id}", "sendDateTime": latest, "text": {"html": "<p>Hej</p>"}},
    }


def test_the_threads_about_a_child_are_those_regarding_it_the_newest_first() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.threads = [
            _thread(1, [101], "2026-12-01T08:00:00+00:00"),
            _thread(2, [102], "2026-12-09T08:00:00+00:00"),
            _thread(3, [102, 101], "2026-12-05T08:00:00+00:00"),
            _thread(4, [101], "2026-12-03"),
            _thread(5, [], "2026-12-10T08:00:00+00:00"),
        ]

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        return [thread.id for thread in await client.threads_about(child)]

    found, _, _ = _run(arrange, act)
    assert found == [3, 4, 1]


def test_a_reply_is_sent_as_escaped_paragraphs_and_neither_marks_the_thread_read_nor_is_kept() -> None:
    text = "  Mille er syg <i>i dag</i> & i morgen.\n \n\nHilsen\n  Pat  \n"

    def arrange(aula: SimulatedAulaApi) -> None:
        aula.threads = [_thread(7, [101], "2026-12-01T08:00:00+00:00")]

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        await client.reply(7, text)
        [thread] = await client.threads_about(child)
        return thread

    thread, aula, client = _run(arrange, act)
    html = "<p>Mille er syg &lt;i&gt;i dag&lt;/i&gt; &amp; i morgen.</p><p>Hilsen<br>Pat</p>"
    assert aula.messages[7][-1]["text"] == {"html": html}
    assert thread.latest_message is not None and thread.latest_message.text is not None and thread.latest_message.text.html == html
    assert "messaging.setLastReadMessage" not in aula.requests
    assert [exchange for exchange in client.api.recorder.exchanges() if exchange.endpoint == "messaging.reply"] == []
    assert "Mille" not in json.dumps(client.responses(KEY), ensure_ascii=False)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (" \n\n \n", "empty"),
        ("&" * (MESSAGE_MAX_LENGTH // 5 + 1), "longer"),
        ("a\n" * 2000, "longer"),
    ],
    ids=["empty", "too long once escaped", "too much HTML"],
)
def test_a_reply_the_portal_would_not_send_is_refused_and_nothing_sent(text: str, message: str) -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.threads = [_thread(7, [101], "2026-12-01T08:00:00+00:00")]

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(ValueError, match=message):
            await client.reply(7, text)

    _, aula, _ = _run(arrange, act)
    assert _written(aula) == []


def test_a_reply_of_the_longest_length_is_sent() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.threads = [_thread(7, [101], "2026-12-01T08:00:00+00:00")]

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        await client.reply(7, "&" * (MESSAGE_MAX_LENGTH // 5))

    _, aula, _ = _run(arrange, act)
    assert len(aula.messages[7]) == 1


def test_a_write_aula_fails_is_sent_once_and_its_error_raised() -> None:
    sent: list[str] = []

    def arrange(aula: SimulatedAulaApi) -> None:
        async def failing(request: web.Request) -> web.Response:
            sent.append(request.query["method"])
            return web.json_response({"status": {"code": 500, "message": "Server error"}}, status=500)

        aula.answers["messaging.reply"] = failing

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(AulaApiError, match="HTTP 500"):
            await client.reply(7, "Hej")

    _run(arrange, act)
    assert sent == ["messaging.reply"]


@pytest.mark.parametrize("method", sorted(WRITES))
def test_reading_a_write_is_refused(method: str) -> None:
    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        with pytest.raises(MethodRefusedError):
            await client.read(method, {}, KEY, body={})

    _run(_nothing, act)


# The child's picture


def test_the_childs_picture_is_read_anew_each_time() -> None:
    picture = {"id": 3, "url": "https://files.example/p.jpg?Expires=1", "scanningStatus": "available", "key": "k", "bucket": "b"}

    def arrange(aula: SimulatedAulaApi) -> None:
        aula.child["profilePicture"] = picture

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        first = await client.get_profile_picture(child)
        picture["url"] = "https://files.example/p.jpg?Expires=2"
        second = await client.get_profile_picture(child)
        other = dataclasses.replace(child, id=12)
        return first, second, await client.get_profile_picture(other)

    (first, second, other), _, _ = _run(arrange, act)
    assert first is not None and (first.url, first.scanning_status) == ("https://files.example/p.jpg?Expires=1", "available")
    assert second is not None and second.url == "https://files.example/p.jpg?Expires=2"
    assert other is None


def test_a_widgets_supplier_and_address_are_read() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.widget_fields["0001"] = TABULEX

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        return (await client.login()).widgets[0]

    widget, _, _ = _run(arrange, act)
    assert (widget.widget_supplier, widget.url) == ("IST", TABULEX["url"])


# The simulated answers


def test_the_simulated_answers_are_in_the_types_the_library_declares() -> None:
    declared = {
        "presence.getPresenceConfigurationByChildIds": AulaGetPresenceConfigurationByChildIdsResponse,
        "presence.getVacationAnnouncementsByChildren": AulaGetVacationAnnouncementsByChildrenResponse,
        "presence.getVacationRegistrationsByChildren": AulaGetVacationRegistrationsByChildrenResponse,
        "presence.getVacationRegistrationResponse": AulaGetVacationRegistrationResponseResponse,
    }

    def arrange(aula: SimulatedAulaApi) -> None:
        _request()(aula)
        aula.vacations = [{"vacationId": 4, "startDate": "2026-12-28", "endDate": "2026-12-28", "description": "", "isEditable": True, "childIds": [11]}]

    async def act(client: AulaClient, child: AulaChildProfile) -> None:
        await client.get_presence_configurations([child])
        await client.get_vacations([child])
        await client.get_vacation_requests([child])
        await client.answer_vacation_request(501, [AulaVacationDay(MONDAY, False)])
        await client.get_vacation_request(501)

    _, _, client = _run(arrange, act)
    exchanges = [exchange for exchange in client.api.recorder.exchanges() if exchange.endpoint in declared]
    assert {exchange.endpoint for exchange in exchanges} == set(declared)
    for exchange in exchanges:
        assert mismatches(declared[exchange.endpoint], exchange.response) == [], exchange.endpoint


def test_a_vacation_dated_with_a_time_is_read_on_its_day() -> None:
    def arrange(aula: SimulatedAulaApi) -> None:
        aula.vacations = [
            {"vacationId": 4, "startDate": "2026-12-28T00:00:00+00:00", "endDate": "2026-12-30T00:00:00+00:00", "isEditable": False, "childIds": [11]}
        ]

    async def act(client: AulaClient, child: AulaChildProfile) -> Any:
        return await client.get_vacations([child])

    [vacation], _, _ = _run(arrange, act)
    assert (vacation.start_date, vacation.end_date, vacation.description) == (date(2026, 12, 28), date(2026, 12, 30), None)

