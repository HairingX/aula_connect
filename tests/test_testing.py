"""Tests that the simulated Aula refuses what the real one refuses, so that a client that sends it
wrongly fails its tests."""

from __future__ import annotations

import asyncio

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
    ("GET", "/meebook/relatedweekplan/all", 401),
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
