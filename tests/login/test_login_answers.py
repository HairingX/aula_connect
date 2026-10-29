"""Tests of how the login takes the answers the real chain gives only now and then, against the
simulated chain with a step answering differently."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import web
from mitid_connect.testing import User

from aula_connect.login import AulaLoginClient
from aula_connect.login.exceptions import (
    AulaAuthenticationError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
    TokenExpiredError,
)
from aula_connect.testing import APP_REDIRECT_URI, Handler, SimulatedAulaLogin

AUTHORIZE = "GET /login/simplesaml/module.php/oidc/authorize.php"
BROKER_START = "GET /broker/auth/realms/broker/protocol/saml"
BROKER_SELECT = "POST /broker/select"
MITID_PAGE = "GET /nemlogin/login/mitid"
MITID_INITIALIZE = "POST /nemlogin/login/mitid/initialize"
MITID_COMPLETE = "POST /nemlogin/login/mitid"
LOGIN_OPTIONS = "GET /nemlogin/loginoption"
CHOOSE_OPTION = "POST /nemlogin/loginoption"
BROKER_ENDPOINT = "POST /broker/auth/realms/broker/broker/nemlogin3/endpoint"
FIRST_BROKER_LOGIN = "GET /broker/first-broker-login"
BACK_TO_AULA = "GET /broker/back-to-aula"
AULA_ACS = "POST /login/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp"
OIDC_CALLBACK = "GET /login/oidc/callback"
TOKEN = "POST /login/simplesaml/module.php/oidc/token.php"


def _session() -> aiohttp.ClientSession:
    # The simulated chain runs on 127.0.0.1, whose cookies aiohttp keeps only when told to.
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))


def _page(text: str = "", status: int = 200, location: str | None = None) -> Handler:
    async def answer(request: web.Request) -> web.StreamResponse:
        headers = {"Location": location} if location is not None else None
        return web.Response(text=text, status=status, headers=headers, content_type="text/html")

    return answer


def _json(body: object, status: int = 200) -> Handler:
    async def answer(request: web.Request) -> web.StreamResponse:
        return web.json_response(body, status=status)

    return answer


async def _disconnect(request: web.Request) -> web.StreamResponse:
    """Drop the connection without an answer, as a failing network does."""
    assert request.transport is not None
    request.transport.close()
    return web.Response()


def _login[T](
    act: Callable[[SimulatedAulaLogin, AulaLoginClient], Awaitable[T]],
    answers: dict[str, Handler] | None = None,
    **options: Any,
) -> T:
    async def run() -> T:
        async with SimulatedAulaLogin(**options) as aula, _session() as session:
            aula.answers.update(answers or {})
            return await act(aula, aula.point(AulaLoginClient(session, "parent")))

    return asyncio.run(run())


async def _authenticate(aula: SimulatedAulaLogin, client: AulaLoginClient) -> dict[str, Any]:
    return await client.authenticate()


def _fails(answers: dict[str, Handler], error: type[Exception], match: str | None = None, **options: Any) -> None:
    with pytest.raises(error, match=match):
        _login(_authenticate, answers, **options)


def test_aula_answering_the_authorization_with_a_form_sends_the_login_to_its_action() -> None:
    async def start(aula: SimulatedAulaLogin, client: AulaLoginClient) -> str:
        return await client.step1_start_oauth_flow()

    page = '<form method="post" action="https://broker.example/saml"></form>'
    assert _login(start, {AUTHORIZE: _page(page)}) == "https://broker.example/saml"


def test_aula_answering_the_authorization_with_a_refresh_sends_the_login_to_its_url() -> None:
    async def start(aula: SimulatedAulaLogin, client: AulaLoginClient) -> str:
        return await client.step1_start_oauth_flow()

    page = '<meta http-equiv="refresh" content="0; URL=https://broker.example/saml">'
    assert _login(start, {AUTHORIZE: _page(page)}) == "https://broker.example/saml"


@pytest.mark.parametrize(
    ("answer", "message"),
    [(_page("<p>Welcome</p>"), "no redirect found"), (_page(status=500), "Unexpected OAuth authorization response")],
)
def test_aula_sending_the_authorization_nowhere_fails_the_login(answer: Handler, message: str) -> None:
    _fails({AUTHORIZE: answer}, OAuthError, message)


@pytest.mark.parametrize(
    "step",
    [AUTHORIZE, BROKER_START, MITID_INITIALIZE, MITID_COMPLETE, BROKER_ENDPOINT, AULA_ACS, TOKEN],
)
def test_a_step_the_network_drops_fails_the_login_as_a_network_error(step: str) -> None:
    _fails({step: _disconnect}, NetworkError)


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({BROKER_START: _page(status=302)}, "missing Location"),
        ({BROKER_START: _page(status=404)}, "Unexpected status code: 404"),
        ({BROKER_START: _page(status=302, location="/login/elsewhere"), "GET /login/elsewhere": _page("<p>?</p>")}, "Unexpected page"),
        ({BROKER_START: _page(status=302, location="/broker/auth/realms/broker/protocol/saml")}, "Too many redirects"),
        ({BROKER_START: _page("<p>Choose</p>")}, "No usable form"),
        ({BROKER_SELECT: _page("unknown identity provider", status=400)}, "IdP selection"),
        ({MITID_PAGE: _page("<form></form>")}, "RequestVerificationToken"),
    ],
)
def test_a_chain_that_does_not_lead_to_mitid_fails_the_login(answers: dict[str, Handler], message: str) -> None:
    _fails(answers, SAMLError, message)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (_json({}), "No Aux"),
        (_page("<p>Not JSON</p>"), "Invalid MitID response format"),
        (_json({"Aux": "bm90IEpTT04="}), "Invalid MitID response format"),
    ],
)
def test_nemlogin_not_starting_mitid_fails_the_login(answer: Handler, message: str) -> None:
    _fails({MITID_INITIALIZE: answer}, MitIDError, message)


def _code_token_login(password: str | None, digits: str | None, auth_method: str = "TOKEN") -> dict[str, Any]:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> dict[str, Any]:
        client.auth_method = auth_method
        client.mitid_password = password
        client.mitid_token = digits
        return await client.authenticate()

    user = User(app=False, code_token=True, token_digits="314159", password="correct horse")
    return _login(login, users={"parent": user})


def test_the_code_token_login_proves_the_digits_and_then_the_password() -> None:
    assert _code_token_login("correct horse", "314159")["success"] is True


@pytest.mark.parametrize(
    ("password", "digits", "message"),
    [
        (None, "314159", "password is required"),
        ("correct horse", None, "token digits are required"),
        ("correct horse", "000000", "MitID authentication failed"),
        ("wrong password", "314159", "MitID authentication failed"),
    ],
)
def test_the_code_token_login_needs_the_right_password_and_digits(password: str | None, digits: str | None, message: str) -> None:
    with pytest.raises(MitIDError, match=message):
        _code_token_login(password, digits)


def test_the_app_login_of_a_user_with_only_a_code_token_fails() -> None:
    with pytest.raises(MitIDError, match="APP not available"):
        _code_token_login("correct horse", "314159", auth_method="APP")


def test_a_method_the_user_does_not_have_fails_the_login() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> None:
        client.auth_method = "TOKEN"
        await client.authenticate()

    with pytest.raises(MitIDError, match="TOKEN not available"):
        _login(login)


@pytest.mark.parametrize(
    ("page", "message"),
    [('<input name="SAMLResponse" value="saml"/>', "RelayState"), ('<input name="RelayState" value="relay"/>', "SAMLResponse")],
)
def test_nemlogin_answering_without_its_saml_response_fails_the_login(page: str, message: str) -> None:
    _fails({MITID_COMPLETE: _page(f"<form>{page}</form>")}, SAMLError, message)


def test_an_identity_chosen_by_number_is_the_one_logged_in_as() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> str | None:
        client.identity_selector = lambda names: 2
        await client.authenticate()
        return aula.chosen_identity

    assert _login(login, identities=["Parent", "Teacher"]) == "Teacher"


@pytest.mark.parametrize("choice", ["3", "0", "Teacher"])
def test_an_identity_not_offered_fails_the_login(choice: str) -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> None:
        client.identity_selector = lambda names: choice
        await client.authenticate()

    with pytest.raises(MitIDError, match="Identity not in list"):
        _login(login, identities=["Parent", "Teacher"])


def test_a_choice_that_fails_fails_the_login() -> None:
    def choose(names: list[str]) -> str:
        raise RuntimeError("the user closed the page")

    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> None:
        client.identity_selector = choose
        await client.authenticate()

    with pytest.raises(AulaAuthenticationError, match="the user closed the page"):
        _login(login, identities=["Parent", "Teacher"])


def test_the_choice_of_identity_sends_the_inputs_known_only_by_their_id() -> None:
    sent: dict[str, str] = {}
    page = (
        '<form method="post" action="/loginoption"><input id="Culture" value="da"/><input type="submit"/></form>'
        '<a class="list-link" data-loginoptions=\'{"id":1}\'><div class="list-link-text">Teacher</div></a>'
    )

    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> str | None:
        async def choose(request: web.Request) -> web.StreamResponse:
            sent.update({name: str(value) for name, value in (await request.post()).items()})
            return await aula._loginoption_choose(request)

        aula.answers[CHOOSE_OPTION] = choose
        await client.authenticate()
        return aula.chosen_identity

    assert _login(login, {LOGIN_OPTIONS: _page(page)}, identities=["Parent", "Teacher"]) == "Teacher"
    assert sent["Culture"] == "da"
    assert "SessionStorageActiveSessionUuid" in sent


def test_the_broker_not_taking_the_saml_response_fails_the_login() -> None:
    _fails({BROKER_ENDPOINT: _page("<p>Error</p>")}, SAMLError, "No redirect from broker endpoint")


def test_a_broker_page_without_a_form_is_passed_with_the_session_of_its_url() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> dict[str, Any]:
        aula.role_selection = False
        return await client.authenticate()

    assert _login(login, {FIRST_BROKER_LOGIN: _page("<p>Welcome back</p>")})["success"] is True


def test_a_broker_page_that_lost_its_session_fails_the_login(caplog: pytest.LogCaptureFixture) -> None:
    async def first_login(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound("/broker/first-broker-login-again")

    form = '<form method="post" action="/broker/auth/realms/broker/login-actions/post-broker-login"></form>'
    answers = {FIRST_BROKER_LOGIN: first_login, "GET /broker/first-broker-login-again": _page(form)}
    with caplog.at_level(logging.WARNING):
        _fails(answers, SAMLError, "No redirect from post-broker-login")
    assert "Missing broker session parameters" in caplog.text


@pytest.mark.parametrize(
    ("page", "message"),
    [("<p>Done</p>", "No SAML form"), ('<form><input name="RelayState" value="relay-aula"/></form>', "SAMLResponse")],
)
def test_the_broker_answering_without_its_saml_response_fails_the_login(page: str, message: str) -> None:
    _fails({BACK_TO_AULA: _page(page)}, SAMLError, message)


def test_a_saml_form_without_an_action_is_sent_to_aulas_endpoint() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> dict[str, Any]:
        aula.answers[BACK_TO_AULA] = _page(f'<form method="post"><input name="SAMLResponse" value="{aula._saml_aula}"/></form>')
        return await client.authenticate()

    assert _login(login)["success"] is True


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({AULA_ACS: _page("<p>Error</p>")}, "No redirect from Aula SAML endpoint"),
        ({OIDC_CALLBACK: _page("<p>Welcome</p>")}, "Did not receive OAuth callback URL: 200"),
        ({OIDC_CALLBACK: _page(status=302, location="/login/oidc/callback")}, "Too many redirects"),
        ({OIDC_CALLBACK: _page(status=302, location=f"{APP_REDIRECT_URI}?code=forged&state=forged")}, "State parameter mismatch"),
        ({TOKEN: _json({"error": "server_error"}, status=500)}, "Token exchange failed: 500"),
        ({TOKEN: _page("<p>Not JSON</p>")}, "Invalid token response format"),
    ],
)
def test_aula_not_handing_out_tokens_fails_the_login(answers: dict[str, Handler], message: str) -> None:
    _fails(answers, OAuthError, message)


def test_aulas_error_sent_back_to_the_app_fails_the_login_without_requesting_the_app() -> None:
    """The app's address is the app's own, which is never requested, whatever it carries."""
    answers = {OIDC_CALLBACK: _page(status=302, location=f"{APP_REDIRECT_URI}?error=access_denied")}
    _fails(answers, OAuthError, "No authorization code")


def _renewing(answer: Handler, tokens: dict[str, Any] | None) -> tuple[bool, dict[str, Any] | None]:
    async def renew(aula: SimulatedAulaLogin, client: AulaLoginClient) -> tuple[bool, dict[str, Any] | None]:
        client.tokens = tokens
        renewed = await client.renew_access_token()
        return renewed, client.tokens

    return _login(renew, {TOKEN: answer})


def test_a_renewal_without_a_refresh_token_renews_nothing() -> None:
    assert _renewing(_json({}), None) == (False, None)
    assert _renewing(_json({}), {"access_token": "old"}) == (False, {"access_token": "old"})


@pytest.mark.parametrize("answer", [_page("<p>Not JSON</p>"), _json({"token_type": "Bearer"}), _page("Bad request", status=400)])
def test_a_renewal_aula_answers_unknowingly_renews_nothing_and_may_be_tried_again(answer: Handler) -> None:
    tokens = {"access_token": "old", "refresh_token": "refresh"}
    assert _renewing(answer, dict(tokens)) == (False, tokens)


def test_a_renewal_without_a_new_refresh_token_keeps_the_one_there_is() -> None:
    renewed, tokens = _renewing(_json({"access_token": "new"}), {"access_token": "old", "refresh_token": "refresh"})
    assert renewed and tokens == {"access_token": "new", "refresh_token": "refresh"}


@pytest.mark.parametrize("status", [401, 403])
def test_a_refresh_token_aula_refuses_needs_a_new_login(status: int) -> None:
    with pytest.raises(TokenExpiredError):
        _renewing(_json({}, status=status), {"refresh_token": "refresh"})


def test_a_renewal_the_network_drops_is_a_network_error() -> None:
    with pytest.raises(NetworkError):
        _renewing(_disconnect, {"refresh_token": "refresh"})


def test_the_login_logs_its_steps_only_when_verbose_and_its_details_only_when_debugging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def logged(verbose: bool = False, debug: bool = False) -> set[int]:
        caplog.clear()
        client = AulaLoginClient(MagicMock(), "parent", verbose=verbose, debug=debug)
        for level in ("DEBUG", "INFO", "WARN", "ERROR", "NOTICE"):
            client.log(f"{level} code=secret", level)
        assert "secret" not in caplog.text
        return {record.levelno for record in caplog.records}

    with caplog.at_level(logging.DEBUG, logger="aula_connect.login.client"):
        assert logged() == {logging.WARNING, logging.ERROR, logging.INFO}
        assert logged(verbose=True) == {logging.INFO, logging.WARNING, logging.ERROR}
        assert logged(verbose=True, debug=True) == {logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR}


def test_the_tokens_are_there_once_logged_in() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> list[object]:
        before: list[object] = [client.is_authenticated(), client.access_token, client.refresh_token]
        tokens = (await client.authenticate())["tokens"]
        after = [client.is_authenticated(), client.access_token == tokens["access_token"], client.refresh_token == tokens["refresh_token"]]
        return before + after

    assert _login(login) == [False, None, None, True, True, True]


def test_the_mitid_login_is_there_only_while_it_runs() -> None:
    async def login(aula: SimulatedAulaLogin, client: AulaLoginClient) -> list[bool]:
        seen: list[bool] = []
        task = asyncio.create_task(client.authenticate())
        while not task.done():
            seen.append(client.get_mitid_client() is not None)
            await asyncio.sleep(0)
        await task
        return [any(seen), client.get_mitid_client() is None]

    assert _login(login) == [True, True]
