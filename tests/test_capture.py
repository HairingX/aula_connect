"""Tests of keeping Aula's answers and handing them out with who someone is replaced, against the
simulated Aula."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, cast

import aiohttp
import pytest
from aiohttp import web
from multidict import CIMultiDict, CIMultiDictProxy

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.aula_errors import AulaCredentialError
from aula_connect.capture import Recorder
from aula_connect.http import HttpResponse, SentRequest
from aula_connect.testing import SimulatedAulaApi, SimulatedAulaLogin

START = datetime(2026, 12, 28, tzinfo=timezone.utc)
END = datetime(2027, 1, 4, tzinfo=timezone.utc)
KEY = b"a key for the tests"

# Every value that tells who someone is, as the account below has it.
PERSONAL = [
    "Pernille",
    "Østergaard",
    "pern4821",
    "Alma",
    "alma9921",
    "Kildebakkens",
    "280917",
    "Birgitte",
    "Holm",
    "birgitte.holm@example.org",
    "23 45 67 89",
    "Farmor Inge",
    "2048193",
    "2048194",
    "3301845",
    "3301846",
    "771234",
    "m88123",
    "sig=Zm9vYmFy",
]


def _account(aula: SimulatedAulaApi) -> None:
    institution = {"id": 3301845, "institutionCode": "280917", "institutionName": "Kildebakkens Skole"}
    aula.guardian = {"profileId": 2048193, "displayName": "Pernille Østergaard", "userId": "pern4821"}
    aula.institution = institution
    aula.child = {
        "id": 3301846,
        "institutionCode": "280917",
        "institutionProfile": institution,
        "name": "Alma Østergaard",
        "profileId": 2048194,
        "shortName": "AØ",
        "userId": "alma9921",
    }
    aula.daily_overviews = [
        {
            "id": 99001,
            "institutionProfile": {**institution, "id": 3301846},
            "status": 3,
            "checkInTime": "08:05:00",
            "exitWith": "Farmor Inge",
        }
    ]
    teacher = {"answerDirectlyName": "Birgitte Holm", "fullName": "Birgitte Holm", "metadata": "Lærer for Alma"}
    text = {
        "html": '<p>Hej Alma, ring på 23 45 67 89 eller skriv til birgitte.holm@example.org.</p>'
        '<img src="https://files.example.org/3301846/foto.jpg?sig=Zm9vYmFy&amp;exp=1">'
    }
    thread: dict[str, object] = {
        "creator": teacher,
        "id": 771234,
        "latestMessage": {"id": "m88123", "sendDateTime": "2026-12-28T08:00:00+00:00", "text": text},
        "regardingChildren": [],
        "recipients": [],
        "sensitive": False,
        "subject": "Tur for Alma",
    }
    aula.threads = [thread, {**thread, "id": 771235, "sensitive": True}]
    aula.messages = {
        771234: [{"id": "m88123", "messageType": "Message", "sendDateTime": "2026-12-28T08:00:00+00:00", "sender": teacher, "text": text}],
        771235: [{"id": "m88124", "text": {"html": "<p>Fortroligt</p>"}}],
    }
    aula.birthdays = [
        {"institutionProfileId": 3301846, "birthday": "2017-01-03", "institutionCode": "280917", "name": "Alma Østergaard", "mainGroupName": "3A"}
    ]
    aula.events = [
        {
            "allDay": False,
            "belongsToProfiles": [3301846],
            "createdDateTime": "2026-12-01T08:00:00+00:00",
            "startDateTime": "2026-12-29T08:00:00+00:00",
            "endDateTime": "2026-12-29T09:00:00+00:00",
            "id": 5512345,
            "title": "Dansk",
            "type": "lesson",
        }
    ]
    aula.weekly_plans = [
        {
            "id": 1,
            "name": "Alma Østergaard",
            "unilogin": "alma9921",
            "weekPlan": [
                {"date": "2026-12-29", "tasks": [{"id": 4, "type": "task", "author": "Birgitte Holm", "group": "3A", "pill": "Dansk", "content": "Læs s. 12"}]}
            ],
        }
    ]
    aula.easyiq_events = [
        {"start": "2026/12/29 08:00", "end": "2026/12/29 09:00", "itemType": "5", "title": "Idræt", "ownername": "Birgitte Holm", "description": ""}
    ]
    aula.newsletters = [{"navn": "Alma Østergaard", "institutioner": [{"institution": "Kildebakkens Skole", "ugebreve": [{"indhold": "<p>Alma har fri</p>"}]}]}]


def _read_everything(key: bytes = KEY) -> tuple[list[str], dict[str, Any], AulaClient, SimulatedAulaApi]:
    async def run() -> tuple[list[str], dict[str, Any], AulaClient, SimulatedAulaApi]:
        async with (
            SimulatedAulaLogin() as login,
            SimulatedAulaApi(login=login) as aula,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            login_client = login.point(AulaLoginClient(session, "parent"))
            tokens = (await login_client.authenticate())["tokens"]
            _account(aula)
            client = AulaClient(
                session,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                expires_at=time.time() + 3600,
                mitid_username="parent",
                login_client=login_client,
            )
            aula.point(client.api)
            failed = await client.read_everything(START, END)
            return failed, client.responses(key), client, aula

    return asyncio.run(run())


def _raw(client: AulaClient) -> list[Any]:
    return [exchange.response for exchange in client.api.recorder.exchanges()]


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for name, item in cast(dict[str, Any], value).items() for text in [name, *_strings(item)]]
    if isinstance(value, list):
        return [text for item in cast(list[Any], value) for text in _strings(item)]
    return [str(value)] if value is not None else []


def _same_shape(original: Any, replaced: Any) -> None:
    """Every value is of its type and, as text, of its length, at its place."""
    if isinstance(original, dict):
        mapping = cast(dict[str, Any], original)
        assert isinstance(replaced, dict) and len(cast(dict[str, Any], replaced)) == len(mapping)
        for (name, item), (other, inner) in zip(mapping.items(), cast(dict[str, Any], replaced).items()):
            assert len(other) == len(name)
            _same_shape(item, inner)
    elif isinstance(original, list):
        items = cast(list[Any], original)
        assert isinstance(replaced, list) and len(cast(list[Any], replaced)) == len(items)
        for item, inner in zip(items, cast(list[Any], replaced)):
            _same_shape(item, inner)
    else:
        assert type(replaced) is type(original)
        assert len(str(replaced)) == len(str(original)), (original, replaced)


def test_reading_everything_reads_each_kind_once_and_no_sensitive_thread() -> None:
    failed, _, _, aula = _read_everything()
    assert failed == []
    assert aula.requests == [
        "profiles.getProfilesByLogin",
        "profiles.getProfileContext",
        "profiles.getProfileMasterData",
        "presence.getDailyOverview",
        "messaging.getThreads",
        "messaging.getMessagesForThread",
        "notifications.getNotificationsForActiveProfile",
        "calendar.getEventsByProfileIdsAndResourceIds",
        "calendar.getBirthdayEventsForInstitutions",
        "aulaToken.getAulaToken",
        "meebook",
        "aulaToken.getAulaToken",
        "easyiq",
        "aulaToken.getAulaToken",
        "minuddannelse",
    ]


def test_the_answers_handed_out_hold_no_one_s_name_id_or_contact_and_no_token() -> None:
    _, export, client, _ = _read_everything()
    text = json.dumps(export, ensure_ascii=False)
    for value in PERSONAL:
        assert value not in text, value
    assert "access_token" not in text
    assert "aulaToken" not in text
    assert "Fortroligt" not in text
    assert any(value in json.dumps(_raw(client), ensure_ascii=False) for value in PERSONAL)


def test_the_answers_handed_out_keep_every_value_s_type_and_length() -> None:
    _, export, client, _ = _read_everything()
    for raw, exchange in zip(_raw(client), export["exchanges"]):
        _same_shape(raw, exchange["response"])


def test_a_value_is_replaced_by_the_same_one_wherever_it_is() -> None:
    _, export, _, _ = _read_everything()
    exchanges = {exchange["endpoint"]: exchange for exchange in export["exchanges"]}
    [profile] = exchanges["profiles.getProfilesByLogin"]["response"]["data"]["profiles"]
    [child] = profile["children"]
    [event] = exchanges["calendar.getEventsByProfileIdsAndResourceIds"]["response"]["data"]
    [birthday] = exchanges["calendar.getBirthdayEventsForInstitutions"]["response"]["data"]
    [thread] = exchanges["messaging.getThreads"]["response"]["data"]["threads"][:1]
    first = child["name"].split()[0]
    assert event["belongsToProfiles"] == [child["id"]]
    assert birthday["institutionProfileId"] == child["id"]
    assert birthday["name"] == child["name"]
    assert thread["subject"] == f"Tur for {first}"
    assert f"Hej {first}," in thread["latestMessage"]["text"]["html"]
    assert f"threadId={thread['id']}" in exchanges["messaging.getMessagesForThread"]["url"]
    assert event["title"] == "Dansk"
    assert event["startDateTime"] == "2026-12-29T08:00:00+00:00"


def test_one_key_gives_the_same_answers_and_another_key_others() -> None:
    _, first, _, _ = _read_everything()
    _, again, _, _ = _read_everything()
    _, other, _, _ = _read_everything(b"another key")
    def answers(export: dict[str, Any]) -> list[Any]:
        return [(re.sub(r"//[^/]+", "", exchange["url"]), exchange["response"]) for exchange in export["exchanges"]]

    assert answers(first) == answers(again)
    assert answers(first) != answers(other)


def test_the_answers_handed_out_say_the_api_version_and_the_type_at_each_place() -> None:
    _, export, _, _ = _read_everything()
    assert export["aula_api_version"] == SimulatedAulaApi.VERSION
    shapes = export["shapes"]["GET presence.getDailyOverview"]
    assert shapes["data[].exitWith"] == ["str"]
    assert shapes["data[].id"] == ["int"]
    assert shapes["data"] == ["list"]


def test_reading_everything_names_what_it_could_not_read_and_reads_the_rest() -> None:
    async def run() -> list[str]:
        async with (
            SimulatedAulaLogin() as login,
            SimulatedAulaApi(login=login) as aula,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            login_client = login.point(AulaLoginClient(session, "parent"))
            tokens = (await login_client.authenticate())["tokens"]
            aula.widgets = []

            async def broken(request: web.Request) -> web.Response:
                return web.json_response({"status": {"code": 500, "message": "Down"}}, status=500)

            aula.answers["presence.getDailyOverview"] = broken
            client = AulaClient(session, tokens["access_token"], tokens["refresh_token"], time.time() + 3600, "parent", login_client)
            aula.point(client.api)
            failed = await client.read_everything(START, END)
            assert "calendar.getBirthdayEventsForInstitutions" in aula.requests
            assert "meebook" not in aula.requests
            return failed

    [failure] = asyncio.run(run())
    assert failure.startswith("daily overviews: ")


def test_reading_everything_stops_where_the_login_fails() -> None:
    async def run() -> tuple[list[str], list[str]]:
        async with (
            SimulatedAulaLogin() as login,
            SimulatedAulaApi(login=login) as aula,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            login_client = login.point(AulaLoginClient(session, "parent"))
            tokens = (await login_client.authenticate())["tokens"]

            async def broken(request: web.Request) -> web.Response:
                return web.json_response({"status": {"code": 500, "message": "Down"}}, status=500)

            aula.answers["profiles.getProfilesByLogin"] = broken
            client = AulaClient(session, tokens["access_token"], tokens["refresh_token"], time.time() + 3600, "parent", login_client)
            aula.point(client.api)
            return await client.read_everything(START, END), aula.requests

    failed, requests = asyncio.run(run())
    assert [failure.split(":")[0] for failure in failed] == ["profiles"]
    assert requests == []


def _response(body: bytes, status: int = 200) -> HttpResponse:
    return HttpResponse(status, "OK", "https://aula.example/api", CIMultiDictProxy(CIMultiDict()), body, "utf-8", SentRequest("GET", "https://aula.example/api"))


def test_a_recorder_keeps_the_newest_answer_to_each_request_and_forgets_the_oldest() -> None:
    recorder = Recorder(limit=2)
    recorder.record("GET", "https://aula.example/api?method=a", None, None, _response(b'{"n": 1}'))
    recorder.record("GET", "https://aula.example/api?method=b", None, None, _response(b'{"n": 2}'))
    recorder.record("GET", "https://aula.example/api?method=a", None, None, _response(b'{"n": 3}'))
    recorder.record("GET", "https://aula.example/api?method=c", None, None, _response(b"<html>", 500))
    assert [(exchange.endpoint, exchange.status, exchange.response) for exchange in recorder.exchanges()] == [
        ("a", 200, {"n": 3}),
        ("c", 500, "<html>"),
    ]
    recorder.clear()
    assert recorder.exchanges() == []


def test_a_recorder_keeps_no_request_for_a_token_and_the_query_it_was_sent_with() -> None:
    recorder = Recorder()
    recorder.record("GET", "https://aula.example/api?method=aulaToken.getAulaToken", None, None, _response(b'"t"'))
    recorder.record("POST", "https://aula.example/widget/read", {"week": "2026-W53"}, {"id": 1}, _response(b"[]"))
    [exchange] = recorder.exchanges()
    assert (exchange.endpoint, exchange.url, exchange.request) == ("/widget/read", "https://aula.example/widget/read?week=2026-W53", {"id": 1})


def test_reading_everything_gives_up_where_only_a_new_login_helps(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async with (
            SimulatedAulaLogin() as login,
            SimulatedAulaApi(login=login) as aula,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            login_client = login.point(AulaLoginClient(session, "parent"))
            tokens = (await login_client.authenticate())["tokens"]
            client = AulaClient(session, tokens["access_token"], tokens["refresh_token"], time.time() + 3600, "parent", login_client)
            aula.point(client.api)

            async def refused(*args: object) -> None:
                raise AulaCredentialError("refused")

            monkeypatch.setattr(client, "get_daily_overviews", refused)
            await client.read_everything(START, END)

    with pytest.raises(AulaCredentialError):
        asyncio.run(run())
