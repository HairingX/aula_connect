"""Tests of how the API client takes the answers Aula and its widgets give only now and then,
against the simulated Aula with a request answering differently."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from aula_connect.api.aula_errors import AulaApiError, AulaCredentialError
from aula_connect.api.aula_proxy_client import AulaProxyClient, _decode_jwt_exp, _describe_token
from aula_connect.api.models.aula_profile_models import AulaChildProfile, AulaToken
from aula_connect.api.models.constants import AulaWidgetId
from aula_connect.testing import Handler, SimulatedAulaApi

START = datetime(2026, 12, 28, tzinfo=timezone.utc)
ONE_WEEK = START + timedelta(days=7)
TWO_WEEKS = START + timedelta(days=14)
MEEBOOK = "GET /meebook/relatedweekplan/all"
EASYIQ = "POST /easyiq/weekplaninfo"
MINUDDANNELSE = "GET /minuddannelse/ugebrev"
PLAN: dict[str, object] = {"id": 1, "name": "Alma", "unilogin": "alma", "weekPlan": [{"date": "2026-12-29", "tasks": []}]}


def _json(body: object, status: int = 200) -> Handler:
    async def answer(request: web.Request) -> web.StreamResponse:
        return web.json_response(body, status=status)

    return answer


def _text(text: str, status: int = 200) -> Handler:
    async def answer(request: web.Request) -> web.StreamResponse:
        return web.Response(text=text, status=status)

    return answer


async def _disconnect(request: web.Request) -> web.StreamResponse:
    """Drop the connection without an answer, as a failing network does."""
    assert request.transport is not None
    request.transport.close()
    return web.Response()


def _answering(aula: SimulatedAulaApi, key: str, *answers: Handler) -> None:
    """Answer the requests `key` names with `answers`, one each in turn, and then as the simulated Aula does."""
    remaining = list(answers)

    async def answer(request: web.Request) -> web.StreamResponse:
        handler = remaining.pop(0)
        if not remaining:
            del aula.answers[key]
        return await handler(request)

    aula.answers[key] = answer


def _run[T](
    act: Callable[[SimulatedAulaApi, AulaProxyClient], Awaitable[T]],
    login: bool = True,
) -> T:
    async def run() -> T:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            client = aula.point(AulaProxyClient(session, aula.access_token))
            if login:
                await client.login()
            return await act(aula, client)

    return asyncio.run(run())


def _children(client: AulaProxyClient) -> list[AulaChildProfile]:
    assert client._login_result is not None
    return client._login_result.profiles[0].children


def test_a_token_is_described_without_itself() -> None:
    now = datetime.now(timezone.utc)
    assert _describe_token(None) == "token=None"
    assert _describe_token(AulaToken("Bearer secret", now)).endswith("JWT exp=undecoded")
    assert "EXPIRED" in _describe_token(AulaToken("Bearer secret", now, now - timedelta(seconds=5)))


@pytest.mark.parametrize("payload", [b"[1, 2]", b"not json", b"\xff\xfe"])
def test_a_jwt_whose_claims_cannot_be_read_has_no_expiry(payload: bytes) -> None:
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    assert _decode_jwt_exp(f"header.{encoded}.signature") is None


def test_a_custom_call_reads_and_posts_aula_as_given() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[Any]:
        read = await client.custom_api_call("?method=profiles.getProfileContext", None)
        posted = await client.custom_api_call("?method=calendar.getEventsByProfileIdsAndResourceIds", '{"start": "2026-12-28"}')
        return [read["data"]["userId"], posted["data"], aula.requests[-2:]]

    assert _run(act) == ["pat", [], ["profiles.getProfileContext", "calendar.getEventsByProfileIdsAndResourceIds"]]


def test_a_custom_call_posts_nothing_that_is_no_json() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> Any:
        return await client.custom_api_call("?method=calendar.getEventsByProfileIdsAndResourceIds", "{not json")

    assert _run(act) == {"result": "Fail - invalid json supplied as post_data"}


def test_a_custom_call_gives_an_answer_that_is_no_json_as_text() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> Any:
        aula.answers["profiles.getProfileContext"] = _text("<p>Maintenance</p>")
        return await client.custom_api_call("?method=profiles.getProfileContext", None)

    assert _run(act) == {"raw_response": "<p>Maintenance</p>"}


def test_a_client_logged_in_gives_what_it_read_without_reading_it_again() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> tuple[bool, int]:
        first = client._login_result
        again = await client.login()
        return again is first, aula.requests.count("profiles.getProfileContext")

    assert _run(act) == (True, 1)


def test_a_login_aula_does_not_confirm_is_read_again() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> int:
        _answering(aula, "profiles.getProfilesByLogin", _text("<p>Not JSON</p>"))
        await client.login()
        return aula.requests.count("profiles.getProfileContext")

    assert _run(act) == 2


def test_the_login_follows_aula_to_a_newer_version_of_its_api() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> tuple[int, int]:
        aula.version = SimulatedAulaApi.VERSION + 2
        data = await client.login()
        return client.api_version, data.api_version

    assert _run(act, login=False) == (SimulatedAulaApi.VERSION + 2, SimulatedAulaApi.VERSION + 2)


def test_the_login_gives_up_on_an_api_ten_versions_on() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        aula.version = SimulatedAulaApi.VERSION + 20
        await client.login()

    with pytest.raises(ConnectionRefusedError, match="410"):
        _run(act, login=False)


@pytest.mark.parametrize("method", ["profiles.getProfilesByLogin", "profiles.getProfileContext"])
def test_a_login_aula_forbids_asks_for_a_new_login(method: str) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        aula.answers[method] = _json({"status": {"code": 403, "message": "Forbidden"}}, status=403)
        await client.login()

    with pytest.raises(AulaCredentialError):
        _run(act, login=False)


def test_profiles_in_a_form_not_known_fail_the_login_without_logging_them(caplog: pytest.LogCaptureFixture) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        aula.answers["profiles.getProfilesByLogin"] = _json({"status": {"message": "OK"}, "data": {"profiles": "Pat Example"}})
        await client.login()

    with pytest.raises(AttributeError):
        _run(act, login=False)
    assert "Error parsing profiles: AttributeError" in caplog.text
    assert "Pat Example" not in caplog.text


@pytest.mark.parametrize(
    "answer",
    [
        _json({"status": {"code": 500}}, status=500),
        _json({"status": {"message": "OK"}}),
        _json({"status": {"message": "OK"}, "data": {"userId": "pat", "pageConfiguration": {"widgetConfigurations": [{"widget": 5}]}}}),
    ],
)
def test_a_profile_context_aula_does_not_give_leaves_the_login_without_widgets(answer: Handler) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[Any]:
        aula.answers["profiles.getProfileContext"] = answer
        data = await client.login()
        return data.widgets

    assert _run(act, login=False) == []


@pytest.mark.parametrize("answer", [_json({}, status=500), _json({"status": {"message": "OK"}, "data": {"institutionProfiles": 5}})])
def test_master_data_aula_does_not_give_leaves_the_children_without_their_main_group(answer: Handler) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> str:
        aula.answers["profiles.getProfileMasterData"] = answer
        await client.login()
        return _children(client)[0].main_group.name

    assert _run(act, login=False) == ""


def test_a_read_aula_answers_without_content_gives_nothing() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[Any]:
        aula.answers["messaging.getThreads"] = _text("", status=204)
        return await client.get_message_threads()

    assert _run(act) == []


def test_a_read_in_a_form_not_known_fails_without_logging_it(caplog: pytest.LogCaptureFixture) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        aula.answers["presence.getDailyOverview"] = _json({"status": {"message": "OK"}, "data": [{"id": "Alma Example"}]})
        await client.get_daily_overviews(client._login_result.profiles if client._login_result else [])

    with pytest.raises(ValueError):
        _run(act)
    assert "Error parsing daily overviews: ValueError" in caplog.text
    assert "Alma Example" not in caplog.text


def test_a_server_error_with_a_status_python_has_no_name_for_is_tried_again() -> None:
    """Cloudflare, in front of many sites, answers 520 to 527 for errors of the server behind it."""

    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[Any]:
        _answering(aula, "messaging.getThreads", _text("Web server is returning an unknown error", status=520))
        return await client.get_message_threads()

    assert _run(act) == []


@pytest.mark.parametrize("drops", [1, 2])
def test_a_read_the_network_drops_is_tried_again(drops: int) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[Any]:
        _answering(aula, "messaging.getThreads", *[_disconnect] * drops)
        return await client.get_message_threads()

    assert _run(act) == []


def test_a_read_the_network_keeps_dropping_fails_as_a_network_error() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        aula.answers["messaging.getThreads"] = _disconnect
        await client.get_message_threads()

    with pytest.raises(aiohttp.ClientError):
        _run(act)


def test_the_messages_of_a_thread_are_read_unless_it_is_sensitive() -> None:
    thread: dict[str, object] = {
        "creator": {"answerDirectlyName": "Teacher", "fullName": "Teacher", "metadata": ""},
        "id": 5,
        "latestMessage": {"id": "m1", "sendDateTime": "2026-12-28T08:00:00+00:00", "text": {"html": "<p>Hi</p>"}},
        "regardingChildren": [],
        "recipients": [],
        "sensitive": False,
        "subject": "Trip",
    }
    message: dict[str, object] = {
        "id": "m1",
        "messageType": "Message",
        "sendDateTime": "2026-12-28T08:00:00+00:00",
        "sender": {"answerDirectlyName": "Teacher", "fullName": "Teacher", "metadata": ""},
        "text": {"html": "<p>Hi</p>"},
    }

    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> list[str]:
        aula.threads = [thread, {**thread, "id": 6, "sensitive": True}]
        aula.messages = {5: [message]}
        readable, sensitive = await client.get_message_threads()
        with pytest.raises(PermissionError):
            await client.get_messages(sensitive)
        return [read.text.html for read in await client.get_messages(readable) if read.text is not None]

    assert _run(act) == ["<p>Hi</p>"]


def test_the_guardian_is_asked_for_where_the_login_did_not_read_who_it_is() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> int:
        assert client._login_result is not None
        client._login_result.profiles[0].user_id = ""
        await client.get_newsletters(_children(client), START, ONE_WEEK)
        return aula.requests.count("profiles.getProfileContext")

    assert _run(act) == 2


def test_a_guardian_aula_does_not_tell_fails_the_widget_read() -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> None:
        assert client._login_result is not None
        client._login_result.profiles[0].user_id = ""
        aula.answers["profiles.getProfileContext"] = _json({}, status=500)
        await client.get_easyiq_weekly_plans(_children(client), START, ONE_WEEK)

    with pytest.raises(AulaApiError, match="guardian user ID: HTTP 500"):
        _run(act)


WIDGET_READS: dict[str, tuple[str, Callable[[AulaProxyClient, list[AulaChildProfile], datetime], Awaitable[list[Any]]]]] = {
    "Meebook": (MEEBOOK, lambda client, children, end: client.get_weekly_plans(children, START, end)),
    "EasyIQ": (EASYIQ, lambda client, children, end: client.get_easyiq_weekly_plans(children, START, end)),
    "MinUddannelse": (MINUDDANNELSE, lambda client, children, end: client.get_newsletters(children, START, end)),
}


def _widget(name: str, *answers: Handler, end: datetime = ONE_WEEK) -> tuple[list[Any], list[str]]:
    key, read = WIDGET_READS[name]

    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> tuple[list[Any], list[str]]:
        aula.weekly_plans = [PLAN]
        if answers:
            _answering(aula, key, *answers)
        return await read(client, _children(client), end), aula.requests

    return _run(act)


EXPIRED = _json({"message": "JWT-Token expired, please renew."})
UNAUTHORIZED = _json({"message": "unauthorized"}, status=401)


@pytest.mark.parametrize("name", WIDGET_READS)
@pytest.mark.parametrize("refusal", [UNAUTHORIZED, EXPIRED], ids=["401", "expired"])
def test_a_widget_refusing_its_token_is_read_again_on_a_new_session_and_token(name: str, refusal: Handler) -> None:
    _, requests = _widget(name, refusal)
    assert requests.count("aulaToken.getAulaToken") == 2
    assert requests.count("profiles.getProfilesByLogin") >= 2


@pytest.mark.parametrize("name", WIDGET_READS)
def test_a_widget_refusing_its_new_token_too_fails_without_asking_for_a_new_login(name: str) -> None:
    with pytest.raises(AulaApiError, match="401 even after full recovery"):
        _widget(name, UNAUTHORIZED, UNAUTHORIZED)


@pytest.mark.parametrize("name", WIDGET_READS)
def test_a_widget_the_network_drops_once_recovered_gives_nothing(name: str) -> None:
    # aiohttp itself sends a GET once more on a connection that was dropped.
    assert _widget(name, UNAUTHORIZED, _disconnect, _disconnect)[0] == []


@pytest.mark.parametrize("name", WIDGET_READS)
def test_a_widget_failing_at_once_fails_the_read(name: str) -> None:
    error = _json({"message": "down"}, status=500)
    with pytest.raises(AulaApiError):
        _widget(name, error, error, error)


@pytest.mark.parametrize("name", WIDGET_READS)
def test_a_widget_failing_after_the_first_week_skips_the_week(name: str, caplog: pytest.LogCaptureFixture) -> None:
    async def first_week(request: web.Request) -> web.StreamResponse:
        return web.json_response({"Events": [], "personer": []} if request.method == "POST" or "ugebrev" in request.path else [PLAN])

    error = _json({"message": "down"}, status=500)
    _widget(name, first_week, error, error, error, end=TWO_WEEKS)
    assert f"Failed to retrieve {name} data: HTTP 500" in caplog.text


def test_a_meebook_week_answered_with_no_plans_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    plans, _ = _widget("Meebook", _json({"error": "no week plan"}))
    assert plans == []
    assert "Unexpected Meebook response type (dict)" in caplog.text


def test_a_widget_token_handed_out_expired_is_used_all_the_same(caplog: pytest.LogCaptureFixture) -> None:
    async def act(aula: SimulatedAulaApi, client: AulaProxyClient) -> AulaToken | None:
        aula.widget_token_lifetime = -60
        return await client._get_token(AulaWidgetId.WEEKPLAN_PARENTS)

    with caplog.at_level(logging.WARNING):
        token = _run(act)
    assert token is not None
    assert "non-positive TTL" in caplog.text
