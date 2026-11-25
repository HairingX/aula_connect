"""Tests of reporting a child sick through IST's Tabulex, and of reading it, against a simulated Aula and Tabulex."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import pytest

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.aula_errors import NoSickReportRouteError, SickReportFinalError
from aula_connect.api.models.aula_presence_models import AulaSickReportCheck, AulaSickReportRoute
from aula_connect.api.models.aula_profile_models import AulaChildProfile
from aula_connect.tabulex import (
    TabulexChild,
    TabulexClient,
    TabulexDay,
    TabulexError,
    TabulexSchoolDay,
    match,
    parse_children,
    parse_day,
    parse_school_days,
)
from aula_connect.capture import Recorder
from aula_connect.testing import SimulatedAulaApi, SimulatedTabulex

CPR = "1234567890"
Arrange = Callable[[SimulatedAulaApi, SimulatedTabulex], None]
Act = Callable[[AulaClient, AulaChildProfile, SimulatedTabulex], Awaitable[Any]]


def _tabulex_route(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
    aula.presence_modules = {"report_sick": "readable"}
    aula.widgets.append("0047")
    aula.widget_fields["0047"] = tabulex.widget


def _run(act: Act, arrange: Arrange = _tabulex_route) -> tuple[Any, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
    async def run() -> tuple[Any, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
        async with (
            SimulatedAulaApi() as aula,
            SimulatedTabulex(aula) as tabulex,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            arrange(aula, tabulex)
            client = AulaClient(
                session,
                access_token=aula.access_token,
                refresh_token="refresh",
                expires_at=time.time() + 3600,
                mitid_username="parent",
                login_client=AulaLoginClient(session, "parent"),
            )
            aula.point(client.api)
            tabulex.point(client)
            [child] = (await client.login()).profiles[0].children
            try:
                result: Any = await act(client, child, tabulex)
            except Exception as error:
                result = error
            return result, aula, tabulex, client

    return asyncio.run(run())


async def _report(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> AulaSickReportRoute:
    return await client.report_sick(child)


def test_a_child_whose_route_is_tabulex_is_reported_sick_there_once_by_its_cpr() -> None:
    result, aula, tabulex, _ = _run(_report)
    assert result is AulaSickReportRoute.TABULEX and tabulex.sick_reports == [CPR]
    assert "presence.updateStatusByInstitutionProfileIds" not in aula.requests


def test_tabulex_tells_the_child_sick_today_once_reported() -> None:
    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        async with client.tabulex() as portal:
            [found] = await portal.children()
            before = await portal.today(found)
            await portal.report_sick_today(found)
            return found, before, await portal.today(found), await portal.tomorrow(found), await portal.school_days(found)

    (found, before, after, tomorrow, days), _, _, _ = _run(act)
    assert found == TabulexChild(CPR, "Alma", "Example", "280123", "Made-up School", "3A", True)
    assert before is not None and not before.sick and after is not None and after.sick
    assert tomorrow is not None and not tomorrow.sick
    assert days == [TabulexSchoolDay(datetime.date(2026, 11, 24), True), TabulexSchoolDay(datetime.date(2026, 11, 29), False)]


def test_a_child_tabulex_knows_by_no_such_name_is_not_reported() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.children = [{**tabulex.children[0], "Fornavn": "Bo"}]

    error, _, tabulex, _ = _run(_report, arrange)
    assert isinstance(error, TabulexError) and "no child" in str(error) and tabulex.sick_reports == []


def test_a_sick_report_tabulex_refuses_says_so_and_is_never_sent_again() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.refuse_reports = True

    error, _, tabulex, _ = _run(_report, arrange)
    assert isinstance(error, TabulexError) and "HTTP 500" in str(error)
    assert [request for request in tabulex.requests if request.startswith("PUT ")] == [f"PUT {SimulatedTabulex.PORTAL}/api/Fravaer/MeldSygIdag/"]


def test_a_sick_report_through_tabulex_cannot_be_taken_back() -> None:
    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        await client.undo_sick(child)

    error, aula, tabulex, _ = _run(act)
    assert isinstance(error, SickReportFinalError) and error.route == "IST Tabulex"
    assert tabulex.requests == [] and "presence.updateStatusByInstitutionProfileIds" not in aula.requests


def test_a_login_to_tabulex_that_does_not_reach_the_portal_is_refused_before_any_report() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.leave_to_elsewhere = True

    error, _, tabulex, _ = _run(_report, arrange)
    assert isinstance(error, TabulexError) and str(error).startswith(f"The login to Tabulex ended at {SimulatedTabulex.ELSEWHERE}/login")
    assert tabulex.sick_reports == []


def test_tabulex_is_not_reached_without_its_widget() -> None:
    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        async with client.tabulex():
            return None

    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        aula.widget_fields["0047"] = {**tabulex.widget, "type": "secure"}

    error, _, tabulex, _ = _run(act, arrange)
    assert isinstance(error, NoSickReportRouteError) and tabulex.requests == []


def test_tabulex_answers_that_are_no_json_or_an_error_are_told_without_its_data() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.garbled = True

    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        errors: list[str] = []
        async with client.tabulex() as portal:
            unknown = TabulexChild("0000000000", "Bo", "")
            for call in (portal.today(unknown), portal.school_days(unknown), portal.children()):
                try:
                    await call
                except TabulexError as error:
                    errors.append(str(error))
        async with aiohttp.ClientSession() as session:
            try:
                await TabulexClient(session, f"http://{SimulatedTabulex.PORTAL}:1", Recorder()).children()
            except TabulexError as error:
                errors.append(str(error))
        return errors

    errors, _, _, _ = _run(act, arrange)
    assert errors[:3] == [
        "Tabulex answered HTTP 404 for today's absence",
        "Tabulex answered HTTP 404 for the school days",
        "Tabulex answered no JSON for the children",
    ]
    assert errors[3].startswith("Tabulex could not be reached for the children:")


def test_without_the_xsrf_token_its_page_set_the_portal_refuses_the_api() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.xsrf_cookie = False

    error, _, tabulex, _ = _run(_report, arrange)
    assert isinstance(error, TabulexError) and str(error) == "Tabulex answered HTTP 500 for the children"
    assert tabulex.sick_reports == []


def test_a_sick_report_that_gets_no_answer_says_tabulex_may_have_registered_it() -> None:
    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        async with aiohttp.ClientSession() as session:
            await TabulexClient(session, f"http://{SimulatedTabulex.PORTAL}:1").report_sick_today(TabulexChild(CPR, "Alma", "Example"))

    error, _, _, _ = _run(act)
    assert isinstance(error, TabulexError) and "may or may not have registered it" in str(error)


def test_reading_everything_reads_tabulex_and_its_answers_tell_no_cpr_nor_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        now = datetime.datetime.now(datetime.UTC)
        failed = await client.read_everything(now, now + datetime.timedelta(days=7))
        return failed, client.responses(b"k" * 32)

    (failed, answers), _, tabulex, _ = _run(act)
    assert [failure for failure in failed if "Tabulex" in failure] == []
    endpoints = sorted(exchange["endpoint"].rsplit("/", 1)[0] for exchange in answers["exchanges"] if "/api/" in exchange["endpoint"])
    assert endpoints[-4:] == ["/api", "/api/Fravaer/Idag", "/api/Fravaer/Imorgen", "/api/Fravaer/skoledage"]
    text = json.dumps(answers, ensure_ascii=False)
    assert [secret for secret in (CPR, tabulex.xsrf, tabulex.portal_session) if secret in text or secret in caplog.text] == []
    assert any(kind.startswith("GET /api/Fravaer/Idag/") for kind in answers["shapes"])


def test_reading_everything_tells_a_failed_read_of_tabulex() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.leave_to_elsewhere = True

    async def act(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> Any:
        now = datetime.datetime.now(datetime.UTC)
        return await client.read_everything(now, now + datetime.timedelta(days=7))

    failed, _, _, _ = _run(act, arrange)
    assert [failure for failure in failed if failure.startswith("Tabulex: The login to Tabulex ended at")] != []


def test_a_child_is_found_in_tabulex_by_its_first_name_then_by_its_last() -> None:
    child = AulaChildProfile.__new__(AulaChildProfile)
    child.first_name, child.name = "Alma", "Alma Example"
    alma = TabulexChild("1", "alma", "Other")
    twin = [TabulexChild("1", "Alma", "Other"), TabulexChild("2", "Alma", "Example")]
    assert match(child, [alma, TabulexChild("3", "Bo", "Example")]) == alma
    assert match(child, twin) == twin[1]
    assert match(child, [TabulexChild("1", "Alma", ""), TabulexChild("2", "Alma", "")]) is None
    assert match(child, []) is None


def test_the_children_tabulex_lists_are_read_as_far_as_they_can_be() -> None:
    answer = [
        {"Cpr": "1", "Fornavn": "Alma", "Efternavn": "Example", "SkoleKode": 280123, "Klasse": 3, "SkoleFravaerAdgang": "ja"},
        {"Cpr": "", "Fornavn": "Bo"},
        {"Cpr": "2", "Fornavn": None},
        "no child",
    ]
    assert parse_children(answer) == [TabulexChild("1", "Alma", "Example", "280123", None, "3", None)]
    assert parse_children({"Cpr": "1"}) == []
    assert "1" not in repr(parse_children(answer)[0]).replace("280123", "")


@pytest.mark.parametrize(
    ("answer", "sick"),
    [
        ({"Dag": "2026-11-24T00:00:00", "Aarsag": "Sygdom"}, True),
        ({"Dag": None, "Aarsag": "Sygdom"}, False),
        ({"Dag": "2026-11-24T00:00:00", "Aarsag": "Ferie"}, False),
        ({"HarHalvdagsFravaerSetting": True, "Trin": 3, "FoersteLektionAarsag": "Sygdom"}, True),
        ({"HarHalvdagsFravaerSetting": True, "Trin": 8, "FoersteLektionAarsag": "Sygdom"}, False),
        ({"HarHalvdagsFravaerSetting": True, "Trin": 8, "FoersteLektionAarsag": "Sygdom", "SidsteLektionAarsag": "Sygdom"}, True),
        ({"HarHalvdagsFravaerSetting": True, "Trin": True, "FoersteLektionAarsag": "Sygdom"}, True),
    ],
)
def test_a_day_is_sick_as_the_portal_itself_tells_it(answer: dict[str, object], sick: bool) -> None:
    day = parse_day(answer)
    assert isinstance(day, TabulexDay) and day.sick is sick


def test_a_day_or_school_days_tabulex_sends_otherwise_are_read_as_none() -> None:
    assert parse_day(None) is None and parse_day([]) is None
    days = [{"Dato": "2026-11-24T00:00:00", "SkoleDag": True}, {"Dato": "not a date"}, {"Dato": None}, "x", {"Dato": "2026-11-25", "SkoleDag": "ja"}]
    assert parse_school_days(days) == [TabulexSchoolDay(datetime.date(2026, 11, 24), True), TabulexSchoolDay(datetime.date(2026, 11, 25), False)]
    assert parse_school_days({"Dato": "2026-11-24"}) == []


async def _check(client: AulaClient, child: AulaChildProfile, tabulex: SimulatedTabulex) -> AulaSickReportCheck:
    return await client.check_sick_report(child)


def test_checking_a_sick_report_through_tabulex_finds_the_child_and_sends_nothing() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.sick_today.add(CPR)

    check, aula, tabulex, _ = _run(_check, arrange)
    assert check == AulaSickReportCheck(AulaSickReportRoute.TABULEX, True, True, "PUT /api/Fravaer/MeldSygIdag/")
    assert tabulex.sick_reports == [] and [request for request in tabulex.requests if not request.startswith(("GET ", "POST "))] == []
    assert "presence.updateStatusByInstitutionProfileIds" not in aula.requests


def test_checking_a_child_tabulex_does_not_know_says_it_would_send_nothing() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        _tabulex_route(aula, tabulex)
        tabulex.children = [{**tabulex.children[0], "Fornavn": "Bo"}]

    check, _, _, _ = _run(_check, arrange)
    assert check == AulaSickReportCheck(AulaSickReportRoute.TABULEX, False, None, None)


@pytest.mark.parametrize(("status", "sick"), [(1, True), (0, False), (None, None)])
def test_checking_a_sick_report_in_aula_reads_the_childs_presence_and_sends_nothing(status: int | None, sick: bool | None) -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.presence_modules = {"report_sick": "editable"}
        if status is not None:
            aula.daily_overviews = [{"id": 1, "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"}, "status": status}]

    check, aula, tabulex, _ = _run(_check, arrange)
    assert check == AulaSickReportCheck(AulaSickReportRoute.AULA, True, sick, "POST presence.updateStatusByInstitutionProfileIds")
    assert "presence.updateStatusByInstitutionProfileIds" not in aula.requests and tabulex.requests == []


def test_checking_a_child_with_no_route_says_it_would_send_nothing() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.presence_modules = {}

    check, _, _, _ = _run(_check, arrange)
    assert check == AulaSickReportCheck(AulaSickReportRoute.NONE, False, None, None)
