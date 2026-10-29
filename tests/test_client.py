"""Tests of reading Aula with tokens kept fresh, from a login through the simulated login chain to
the simulated API."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.models.constants import AulaWidgetId
from aula_connect.testing import SimulatedAulaApi, SimulatedAulaLogin

START = datetime(2026, 12, 28, tzinfo=timezone.utc)
END = datetime(2027, 1, 4, tzinfo=timezone.utc)


def test_a_client_on_a_logins_tokens_reads_all_of_aula() -> None:
    async def run() -> dict[str, Any]:
        async with (
            SimulatedAulaLogin() as login,
            SimulatedAulaApi(login=login) as aula,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
        ):
            login_client = login.point(AulaLoginClient(session, "parent"))
            tokens = (await login_client.authenticate())["tokens"]
            aula.version = SimulatedAulaApi.VERSION + 1
            aula.birthdays = [{"institutionProfileId": 31, "birthday": "2017-01-03", "institutionCode": "S1", "name": "Bo", "mainGroupName": "3A"}]
            client = AulaClient(
                session,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                expires_at=time.time() + 3600,
                mitid_username="parent",
                login_client=login_client,
            )
            aula.point(client.api)
            await client.connection_check()
            data = await client.login()
            [profile] = data.profiles
            children = profile.children
            reads = {
                "version": client.aula_version,
                "widgets": [client.has_widget(widget) for widget in (AulaWidgetId.WEEKPLAN_PARENTS, AulaWidgetId.REMINDERS)],
                "birthdays": [birthday.full_name for birthday in await client.get_birthday_events(children, START, END)],
                "overviews": await client.get_daily_overviews([profile]),
                "events": await client.get_calendar_events(profile.institution_profiles, START, END),
                "threads": await client.get_message_threads(),
                "notifications": await client.get_notifications(children),
                "plans": await client.get_weekly_plans(children, START, END),
                "easyiq": await client.get_easyiq_weekly_plans(children, START, END),
                "newsletters": await client.get_newsletters(children, START, END),
            }
            return reads

    reads = asyncio.run(run())
    assert reads == {
        "version": SimulatedAulaApi.VERSION + 1,
        "widgets": [True, False],
        "birthdays": ["Bo"],
        "overviews": [],
        "events": [],
        "threads": [],
        "notifications": [],
        "plans": [],
        "easyiq": [],
        "newsletters": [],
    }
