"""Tests that the simulated Aula refuses what the real one refuses, so that a client that sends it
wrongly fails its tests."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from aula_connect.login import AulaLoginClient
from aula_connect.login.exceptions import SAMLError
from aula_connect.testing import APP_REDIRECT_URI, SimulatedAulaApi, SimulatedAulaLogin

BROKER = "AUTH_SESSION_ID=broker-session"
NEMLOGIN = "SessionUuid=nemlogin-session"
AULA = "SimpleSAMLSessionID=aula-session"
PKCE = f"response_type=code&code_challenge_method=S256&redirect_uri={APP_REDIRECT_URI}&state=s&code_challenge=c"

LOGIN_REFUSALS: list[tuple[str, str, str, dict[str, str], int]] = [
    ("GET", "/broker/first-broker-login", "", {}, 403),
    ("GET", "/login/simplesaml/module.php/oidc/authorize.php", "", {}, 400),
    ("GET", f"/login/simplesaml/module.php/oidc/authorize.php?{PKCE.replace(APP_REDIRECT_URI, 'https://example.com')}", "", {}, 400),
    ("GET", "/broker/auth/realms/broker/protocol/saml?SAMLRequest=a+b/c=", "", {}, 400),
    ("POST", "/broker/select", BROKER, {"selectedIdp": "google"}, 400),
    ("POST", "/nemlogin/login/mitid/initialize", NEMLOGIN, {"__RequestVerificationToken": "forged"}, 400),
    ("POST", "/nemlogin/login/mitid", NEMLOGIN, {"MitIDAuthCode": "forged"}, 400),
    ("POST", "/broker/auth/realms/broker/broker/nemlogin3/endpoint", BROKER, {"SAMLResponse": "forged"}, 400),
    ("POST", "/broker/auth/realms/broker/login-actions/post-broker-login?session_code=sc&execution=ex", BROKER, {"selected-aktoer": "ELEV"}, 400),
    ("POST", "/broker/confirm", BROKER, {"confirmed": "no"}, 400),
    ("POST", "/login/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp", AULA, {"SAMLResponse": "forged"}, 400),
    ("POST", "/login/simplesaml/module.php/oidc/token.php", "", {"grant_type": "authorization_code", "code": "forged"}, 400),
]


@pytest.mark.parametrize(("method", "path", "cookie", "form", "status"), LOGIN_REFUSALS)
def test_the_simulated_login_refuses_a_step_sent_wrongly(method: str, path: str, cookie: str, form: dict[str, str], status: int) -> None:
    async def send() -> int:
        async with SimulatedAulaLogin() as aula, aiohttp.ClientSession() as session:
            headers = {"Cookie": cookie} if cookie else {}
            async with session.request(method, aula.url + path, data=form or None, headers=headers, allow_redirects=False) as response:
                return response.status

    assert asyncio.run(send()) == status


def test_a_login_that_does_not_keep_its_cookies_fails() -> None:
    async def login() -> None:
        # aiohttp keeps no cookie of an IP address unless told to.
        async with SimulatedAulaLogin() as aula, aiohttp.ClientSession() as session:
            await aula.point(AulaLoginClient(session, "parent")).authenticate()

    with pytest.raises(SAMLError):
        asyncio.run(login())


API_REFUSALS: list[tuple[str, str, int]] = [
    ("POST", f"/api/v{SimulatedAulaApi.VERSION}?method=calendar.getEventsByProfileIdsAndResourceIds&access_token=access", 403),
    ("GET", f"/api/v{SimulatedAulaApi.VERSION}?method=no.suchMethod&access_token=access", 404),
    ("GET", "/aulaapi/relatedweekplan/all", 401),
    ("POST", "/easyiq/weekplaninfo", 401),
    ("GET", "/minuddannelse/ugebrev", 401),
]


@pytest.mark.parametrize(("method", "path", "status"), API_REFUSALS)
def test_the_simulated_api_refuses_a_request_without_its_tokens(method: str, path: str, status: int) -> None:
    async def send() -> int:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession() as session:
            async with session.request(method, aula.url + path) as response:
                return response.status

    assert asyncio.run(send()) == status


MONDAY = "2026-12-28"
REQUEST: dict[str, object] = {
    "responseId": 501, "childId": 11, "startDate": MONDAY, "endDate": "2027-01-03", "isPresenceTimesRequired": True,
}
DAY: dict[str, object] = {"date": MONDAY, "isComing": True, "entryTime": "08:00", "exitTime": "15:00"}
ANSWER: dict[str, object] = {"vacationRegistrationResponseId": 501, "childId": 11, "days": [DAY], "comment": ""}
VACATION: dict[str, object] = {"childIds": [11], "intervals": [{"startDate": MONDAY, "endDate": MONDAY}], "comment": ""}
REPLY: dict[str, object] = {"threadId": 7, "message": {"text": "<p>Hej</p>", "attachmentIds": []}, "commonInboxId": None, "otpInboxId": None}

WRITE_REFUSALS: list[tuple[str, object]] = [
    ("presence.updateStatusByInstitutionProfileIds", {"institutionProfileIds": [11], "status": 3}),
    ("presence.updateStatusByInstitutionProfileIds", {"institutionProfileIds": [11], "status": True}),
    ("presence.updateStatusByInstitutionProfileIds", {"institutionProfileIds": [12], "status": 1}),
    ("presence.updateStatusByInstitutionProfileIds", {"institutionProfileIds": 11, "status": 1}),
    ("presence.updateStatusByInstitutionProfileIds", {"institutionProfileIds": [11], "status": 1, "date": MONDAY}),
    ("presence.updateStatusByInstitutionProfileIds", [11]),
    ("presence.updateStatusByInstitutionProfileIds", "not json"),
    ("calendar.addVacation", {**VACATION, "childIds": []}),
    ("calendar.addVacation", {**VACATION, "comment": "x" * 251}),
    ("calendar.addVacation", {**VACATION, "comment": None}),
    ("calendar.addVacation", {**VACATION, "intervals": [{"startDate": MONDAY, "endDate": MONDAY}] * 2}),
    ("calendar.addVacation", {**VACATION, "intervals": [MONDAY]}),
    ("calendar.addVacation", {**VACATION, "intervals": [{"startDate": MONDAY}]}),
    ("calendar.addVacation", {**VACATION, "intervals": [{"startDate": "2026-12-28T00:00:00", "endDate": MONDAY}]}),
    ("calendar.addVacation", {**VACATION, "intervals": [{"startDate": "2027-02-30", "endDate": "2027-02-30"}]}),
    ("calendar.addVacation", {**VACATION, "intervals": [{"startDate": MONDAY, "endDate": "2026-12-27"}]}),
    ("calendar.addVacation", {"childIds": [11], "intervals": [{"startDate": MONDAY, "endDate": MONDAY}]}),
    ("calendar.deleteEvent", {"id": 9001, "occurrenceDateTime": None}),
    ("calendar.deleteEvent", {"id": 1}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "vacationRegistrationResponseId": 502}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "childId": 12}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "comment": None}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": []}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [MONDAY]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{"date": MONDAY, "isComing": False}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "date": "2027-01-02"}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "date": "2027-01-04"}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "isComing": None}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "isComing": False}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "exitTime": ""}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "entryTime": "8:00"}]}),
    ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "entryTime": "16:00"}]}),
    ("calendar.respondToVacationRegistrationRequest", {"vacationRegistrationResponseId": 501, "childId": 11, "days": [DAY]}),
    ("messaging.reply", {**REPLY, "threadId": 8}),
    ("messaging.reply", {**REPLY, "commonInboxId": 1}),
    ("messaging.reply", {**REPLY, "otpInboxId": 1}),
    ("messaging.reply", {**REPLY, "message": "<p>Hej</p>"}),
    ("messaging.reply", {**REPLY, "message": {"text": "<p>Hej</p>"}}),
    ("messaging.reply", {**REPLY, "message": {"text": "<p>Hej</p>", "attachmentIds": [1]}}),
    ("messaging.reply", {**REPLY, "message": {"text": "<p> </p>", "attachmentIds": []}}),
    ("messaging.reply", {**REPLY, "message": {"text": 1, "attachmentIds": []}}),
    ("messaging.reply", {**REPLY, "message": {"text": "x" * 6601, "attachmentIds": []}}),
    ("messaging.reply", {**REPLY, "message": {"text": "<br>" * 2500, "attachmentIds": []}}),
    ("messaging.reply", {**REPLY, "sensitive": False}),
]


def _simulated(aula: SimulatedAulaApi) -> None:
    aula.vacation_requests = [REQUEST]
    aula.vacations = [{"vacationId": 9001, "startDate": MONDAY, "endDate": MONDAY, "isEditable": True, "childIds": [11]}]
    aula.threads = [{"id": 7}]


@pytest.mark.parametrize(("method", "body"), WRITE_REFUSALS)
def test_the_simulated_api_refuses_a_write_not_sent_as_aulas_portal_sends_it(method: str, body: object) -> None:
    async def send() -> tuple[int, object]:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession() as session:
            _simulated(aula)
            url = f"{aula.url}/api/v{aula.VERSION}?method={method}&access_token=access"
            data = body if isinstance(body, str) else json.dumps(body)
            async with session.post(url, data=data, headers={"csrfp-token": aula.csrf_token}) as response:
                return response.status, (await response.json())["status"]["code"]

    assert asyncio.run(send()) == (400, 40)


READ_REFUSALS = [
    "presence.getPresenceConfigurationByChildIds",
    "presence.getVacationAnnouncementsByChildren&childIds[]=12",
    "presence.getVacationRegistrationsByChildren&childIds[]=11&childIds[]=x",
    "presence.getVacationRegistrationResponse&vacationRegistrationResponseId=502",
    "presence.getVacationRegistrationResponse",
]


@pytest.mark.parametrize("query", READ_REFUSALS)
def test_the_simulated_api_refuses_a_read_of_no_child_or_request_of_the_account(query: str) -> None:
    async def send() -> tuple[int, object]:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession() as session:
            _simulated(aula)
            async with session.get(f"{aula.url}/api/v{aula.VERSION}?method={query}&access_token=access") as response:
                return response.status, (await response.json())["status"]["code"]

    assert asyncio.run(send()) == (400, 40)


def test_the_simulated_api_answers_a_write_sent_as_aulas_portal_sends_it() -> None:
    async def send() -> list[int]:
        async with SimulatedAulaApi() as aula, aiohttp.ClientSession() as session:
            _simulated(aula)
            statuses: list[int] = []
            for method, body in [
                ("calendar.respondToVacationRegistrationRequest", {**ANSWER, "days": [{**DAY, "isComing": False, "entryTime": "", "exitTime": ""}]}),
                ("calendar.respondToVacationRegistrationRequest", ANSWER),
                ("calendar.deleteEvent", {"id": 9001}),
                ("messaging.reply", REPLY),
            ]:
                url = f"{aula.url}/api/v{aula.VERSION}?method={method}&access_token=access"
                async with session.post(url, json=body, headers={"csrfp-token": aula.csrf_token}) as response:
                    statuses.append(response.status)
            return statuses

    assert asyncio.run(send()) == [200, 200, 200, 200]
