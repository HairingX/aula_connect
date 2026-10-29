"""Tests of the HTTP session the login and the API client send their requests on."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aula_connect.http import MAX_REDIRECTS, HttpSession


def test_a_redirect_without_end_is_followed_only_so_far() -> None:
    requests: list[str] = []

    async def redirect_to_itself(request: web.Request) -> web.StreamResponse:
        requests.append(request.path_qs)
        raise web.HTTPFound(f"/loop?hop={len(requests)}")

    async def run() -> None:
        app = web.Application()
        app.router.add_get("/loop", redirect_to_itself)
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            await HttpSession(session).get(str(server.make_url("/loop")))

    with pytest.raises(aiohttp.TooManyRedirects):
        asyncio.run(run())
    assert len(requests) == MAX_REDIRECTS + 1


def test_a_cookie_the_session_does_not_have_reads_as_the_default() -> None:
    async def run() -> tuple[str, str]:
        async with aiohttp.ClientSession() as session:
            cookies = HttpSession(session).cookies
            return cookies.get("SessionUuid"), cookies.get("SessionUuid", "none")

    assert asyncio.run(run()) == ("", "none")
