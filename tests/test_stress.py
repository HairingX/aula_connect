"""Stress tests of the clients against the simulated Aula, on a slow and failing network."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, cast

import aiohttp
from mitid_connect.testing import Network

from aula_connect.api.aula_errors import AulaApiError
from aula_connect.api.aula_proxy_client import AulaProxyClient
from aula_connect.client import AulaClient
from aula_connect.login import AulaLoginClient
from aula_connect.testing import SimulatedAulaApi, SimulatedAulaLogin

START = datetime(2026, 12, 28, tzinfo=timezone.utc)
END = datetime(2027, 1, 4, tzinfo=timezone.utc)
OVERVIEW: dict[str, object] = {"id": 1, "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"}, "status": 3}


def _jar() -> aiohttp.CookieJar:
    # The simulated Aula runs on 127.0.0.1, whose cookies aiohttp keeps only when told to.
    return aiohttp.CookieJar(unsafe=True)


def _reads(client: AulaProxyClient) -> list[Callable[[], Awaitable[object]]]:
    assert client._login_result is not None
    profiles = client._login_result.profiles
    children = profiles[0].children
    return [
        lambda: client.get_daily_overviews(profiles),
        lambda: client.get_message_threads(),
        lambda: client.get_notifications(children),
        lambda: client.get_birthday_events(children, START, END),
        lambda: client.get_calendar_events(profiles[0].institution_profiles, START, END),
    ]


def test_a_hundred_reads_at_once_all_answer_while_the_others_wait_on_the_network() -> None:
    """A hundred reads of 10-50 ms each: one after the other they would take about three seconds."""

    async def run() -> tuple[list[object], float, Network]:
        network = Network(latency=(0.01, 0.05), seed=2)
        async with SimulatedAulaApi(network=network) as aula, aiohttp.ClientSession(cookie_jar=_jar()) as session:
            aula.daily_overviews = [OVERVIEW]
            client = aula.point(AulaProxyClient(session, aula.access_token))
            await client.login()
            reads = _reads(client)
            started = time.monotonic()
            results = await asyncio.gather(*(reads[index % len(reads)]() for index in range(100)))
            return results, time.monotonic() - started, network

    results, elapsed, network = asyncio.run(run())
    assert all(isinstance(result, list) for result in results)
    assert [len(cast(list[object], overviews)) for overviews in results[::5]] == [1] * 20
    assert network.most_concurrent >= 50
    assert elapsed < 1.5


def test_reads_on_a_network_that_fails_now_and_then_are_retried_or_fail_cleanly() -> None:
    """With a fifth of the answers failing and three attempts each, almost every read gets through;
    one that does not raises the client's own error, and nothing else."""

    network = Network(latency=(0.0, 0.01), failure_rate=0.2, seed=3)

    async def run() -> list[object]:
        async with SimulatedAulaApi(network=network) as aula, aiohttp.ClientSession(cookie_jar=_jar()) as session:
            aula.daily_overviews = [OVERVIEW]
            network.failure_rate = 0.0
            client = aula.point(AulaProxyClient(session, aula.access_token))
            await client.login()
            network.failure_rate = 0.2
            reads = _reads(client)
            return await asyncio.gather(*(reads[index % len(reads)]() for index in range(200)), return_exceptions=True)

    results = asyncio.run(run())
    failed = [result for result in results if isinstance(result, BaseException)]
    assert all(isinstance(error, AulaApiError) for error in failed), failed
    assert len(failed) < 10
    assert network.failures > 30


def test_reads_waiting_on_an_expired_token_renew_it_once() -> None:
    """Fifty reads at once find the access token expired; one renews it, the others wait for it."""
    async def run() -> tuple[int, list[object]]:
        network = Network(latency=(0.01, 0.03), seed=4)
        async with SimulatedAulaLogin(network=network) as login, aiohttp.ClientSession(cookie_jar=_jar()) as session:
            login_client = login.point(AulaLoginClient(session, "parent"))
            await login_client.authenticate()
            assert login_client.tokens is not None
            tokens = dict(login_client.tokens)
            async with SimulatedAulaApi(network=network, login=login) as aula:
                aula.daily_overviews = [OVERVIEW]
                renewed: list[str] = []
                client = AulaClient(
                    session,
                    access_token=str(tokens["access_token"]),
                    refresh_token=str(tokens["refresh_token"]),
                    expires_at=0.0,
                    mitid_username="parent",
                    login_client=login_client,
                    token_update_callback=lambda access, refresh, expires: renewed.append(access),
                )
                aula.point(client.api)
                assert login.renewals == 0
                assert client.api._login_result is None
                await client.login()
                login_result = client.api._login_result
                assert login_result is not None
                profiles = login_result.profiles
                assert login.renewals == 1
                client._expires_at = 0.0
                results = await asyncio.gather(*(client.get_daily_overviews(profiles) for _ in range(50)))
                assert len(renewed) == 2
                return login.renewals, list(results)

    renewals, results = asyncio.run(run())
    assert renewals == 2
    assert [len(cast(list[object], result)) for result in results] == [1] * 50


def test_widget_reads_at_once_fetch_the_widget_token_once() -> None:
    async def run() -> tuple[int, list[Any]]:
        network = Network(latency=(0.01, 0.04), seed=5)
        async with SimulatedAulaApi(network=network) as aula, aiohttp.ClientSession(cookie_jar=_jar()) as session:
            aula.weekly_plans = [
                {"id": 1, "name": "Alma", "unilogin": "alma", "weekPlan": [{"date": "2026-12-29", "tasks": []}]}
            ]
            client = aula.point(AulaProxyClient(session, aula.access_token))
            await client.login()
            assert client._login_result is not None
            children = client._login_result.profiles[0].children
            results = await asyncio.gather(*(client.get_weekly_plans(children, START, END) for _ in range(20)))
            return aula.requests.count("aulaToken.getAulaToken"), list(results)

    tokens, results = asyncio.run(run())
    assert tokens == 1
    assert all(len(plans) == 1 for plans in results)


def test_a_login_on_a_slow_network_still_completes() -> None:
    """About forty requests of 20-60 ms each, MitID's polls among them."""

    async def run() -> tuple[bool, Network]:
        network = Network(latency=(0.02, 0.06), seed=6)
        async with SimulatedAulaLogin(network=network) as login, aiohttp.ClientSession(cookie_jar=_jar()) as session:
            login.mitid.app_answers = ["timeout"] * 5 + ["channel_validation_tqr", "timeout", "channel_verified", "OK"]
            result = await login.point(AulaLoginClient(session, "parent")).authenticate()
            return bool(result["success"]), network

    success, network = asyncio.run(run())
    assert success
    assert network.requests >= 25
