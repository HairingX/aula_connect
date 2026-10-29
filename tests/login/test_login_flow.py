"""Tests of the whole login, from Aula's OAuth through MitID back to the tokens, against the
simulated chain."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from aula_connect.login import AulaLoginClient
from aula_connect.login.exceptions import AulaAuthenticationError, TokenExpiredError
from aula_connect.testing import SimulatedAulaLogin


def _session() -> aiohttp.ClientSession:
    # The simulated chain runs on 127.0.0.1, whose cookies aiohttp keeps only when told to.
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))


def test_a_login_gives_tokens_aula_accepts() -> None:
    async def login() -> dict[str, object]:
        async with SimulatedAulaLogin() as aula, _session() as session:
            client = aula.point(AulaLoginClient(session, "parent"))
            result = await client.authenticate()
            assert client.tokens is not None
            assert client.tokens["access_token"] in aula.refresh_tokens.values()
            return result

    result = asyncio.run(login())
    assert result["success"] is True


@pytest.mark.parametrize(("role_selection", "confirmation_page"), [(False, False), (True, False), (False, True)])
def test_a_login_passes_the_brokers_optional_pages(role_selection: bool, confirmation_page: bool) -> None:
    async def login() -> bool:
        async with SimulatedAulaLogin() as aula, _session() as session:
            aula.role_selection = role_selection
            aula.confirmation_page = confirmation_page
            result = await aula.point(AulaLoginClient(session, "parent")).authenticate()
            return bool(result["success"])

    assert asyncio.run(login())


def test_the_identity_chosen_is_the_one_logged_in_as() -> None:
    async def login() -> tuple[str | None, list[str]]:
        async with SimulatedAulaLogin(identities=["Parent", "Teacher"]) as aula, _session() as session:
            client = aula.point(AulaLoginClient(session, "parent"))
            offered: list[str] = []

            async def choose(names: list[str]) -> str:
                offered.extend(names)
                return "2"

            client.identity_selector = choose
            await client.authenticate()
            return aula.chosen_identity, offered

    assert asyncio.run(login()) == ("Teacher", ["Parent", "Teacher"])


def test_without_a_choice_the_first_identity_is_taken() -> None:
    async def login() -> str | None:
        async with SimulatedAulaLogin(identities=["Parent", "Teacher"]) as aula, _session() as session:
            await aula.point(AulaLoginClient(session, "parent")).authenticate()
            return aula.chosen_identity

    assert asyncio.run(login()) == "Parent"


def test_the_qr_codes_are_shown_while_mitid_waits_for_the_scan() -> None:
    async def login() -> bool:
        async with SimulatedAulaLogin() as aula, _session() as session:
            client = aula.point(AulaLoginClient(session, "parent"))
            aula.mitid.app_answers = ["timeout", "channel_validation_tqr", "timeout", "channel_verified", "OK"]
            seen = False
            task = asyncio.create_task(client.authenticate())
            while not task.done():
                svg = client.get_qr_codes_svg()
                seen = seen or (svg is not None and all(code.startswith("<svg") for code in svg))
                await asyncio.sleep(0)
            await task
            assert client.get_qr_codes_svg() is None
            return seen

    assert asyncio.run(login())


def test_a_user_mitid_does_not_know_fails() -> None:
    async def login() -> None:
        async with SimulatedAulaLogin() as aula, _session() as session:
            await aula.point(AulaLoginClient(session, "somebody-else")).authenticate()

    with pytest.raises(AulaAuthenticationError):
        asyncio.run(login())


def test_the_access_token_is_renewed_with_the_refresh_token() -> None:
    async def renew() -> tuple[bool, str, str]:
        async with SimulatedAulaLogin() as aula, _session() as session:
            client = aula.point(AulaLoginClient(session, "parent"))
            await client.authenticate()
            assert client.tokens is not None
            before = str(client.tokens["access_token"])
            renewed = await client.renew_access_token()
            return renewed, before, str(client.tokens["access_token"])

    renewed, before, after = asyncio.run(renew())
    assert renewed
    assert after != before


def test_a_refresh_token_aula_has_revoked_asks_for_a_new_login() -> None:
    async def renew() -> None:
        async with SimulatedAulaLogin() as aula, _session() as session:
            client = aula.point(AulaLoginClient(session, "parent"))
            await client.authenticate()
            assert client.tokens is not None
            aula.revoked.add(str(client.tokens["refresh_token"]))
            await client.renew_access_token()

    with pytest.raises(TokenExpiredError):
        asyncio.run(renew())
