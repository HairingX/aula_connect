"""HTTP on an aiohttp session, answering with whole responses the way the login flows read them."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp.abc import AbstractCookieJar
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from .redact import redact

DEFAULT_TIMEOUT = 30.0
"""Seconds a single request may take."""

MAX_REDIRECTS = 30
REDIRECTS = (301, 302, 303, 307, 308)


@dataclass(frozen=True, repr=False)
class SentRequest:
    """What was sent, for logs: the method and the URL."""

    method: str
    url: str

    def __repr__(self) -> str:
        return f"<SentRequest {self.method} {redact(self.url)}>"


@dataclass(repr=False)
class HttpResponse:
    """A response read in full."""

    status_code: int
    reason: str
    url: str
    headers: CIMultiDictProxy[str]
    content: bytes
    encoding: str
    request: SentRequest
    history: list[HttpResponse] = field(default_factory=lambda: [])

    def __repr__(self) -> str:
        # Aula's URLs carry the access token, and its answers the children's data.
        return f"<HttpResponse {self.status_code} {self.request.method} {redact(self.url)}>"

    @property
    def ok(self) -> bool:
        """Whether the status is below 400."""
        return self.status_code < 400

    @property
    def text(self) -> str:
        """The body as text, in the response's charset."""
        return self.content.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        """The body as JSON.

        Raises:
            ValueError: the body is no JSON.
        """
        return json.loads(self.content)


@dataclass(frozen=True)
class Cookie:
    """A cookie in the session's jar."""

    name: str
    value: str
    domain: str


class Cookies:
    """The cookies of a session, read by name or one by one."""

    def __init__(self, jar: AbstractCookieJar) -> None:
        self._jar = jar

    def __iter__(self) -> Iterator[Cookie]:
        for morsel in self._jar:
            yield Cookie(morsel.key, morsel.value, str(morsel["domain"]))

    def get(self, name: str, default: str = "") -> str:
        """The value of the cookie `name`, `default` when there is none."""
        for cookie in self:
            if cookie.name == name:
                return cookie.value
        return default

    def get_dict(self) -> dict[str, str]:
        """Every cookie's value, by name."""
        return {cookie.name: cookie.value for cookie in self}


class HttpSession:
    """Requests on an aiohttp session, with the headers given sent on each.

    Redirects are followed here, not by aiohttp, so that a URL a server redirects to is requested
    exactly as it was given: login flows carry signed parameters a re-quoted URL would break.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.session = session
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.cookies = Cookies(session.cookie_jar)

    def clear_cookies(self) -> None:
        """Forget every cookie, as a new browser session would."""
        self.session.cookie_jar.clear()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | str | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> HttpResponse:
        """Send a request, follow its redirects when asked to, and give the last response.

        Raises:
            aiohttp.ClientError: the request could not be sent or answered.
            TimeoutError: it took longer than the timeout.
        """
        sent: CIMultiDict[str] = CIMultiDict(self.headers)
        sent.update(headers or {})
        history: list[HttpResponse] = []
        target = url if params is None else str(URL(url, encoded=True).update_query(params))
        while True:
            response = await self._send(method, target, data, json, sent, timeout)
            if not allow_redirects or response.status_code not in REDIRECTS or "Location" not in response.headers:
                response.history = history
                return response
            if len(history) >= MAX_REDIRECTS:
                raise aiohttp.TooManyRedirects(
                    aiohttp.RequestInfo(URL(target, encoded=True), method, CIMultiDictProxy(sent)), ()
                )
            history.append(response)
            target = str(URL(target, encoded=True).join(URL(response.headers["Location"], encoded=True)))
            if response.status_code in (301, 302, 303) and method != "HEAD":
                method, data, json = "GET", None, None
                for name in ("Content-Type", "Content-Length"):
                    sent.popall(name, None)

    async def _send(
        self,
        method: str,
        url: str,
        data: Mapping[str, str] | str | None,
        payload: Any,
        headers: CIMultiDict[str],
        timeout: float | None,
    ) -> HttpResponse:
        async with self.session.request(
            method,
            URL(url, encoded=True),
            data=data,
            json=payload,
            headers=headers,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=timeout if timeout is not None else self.timeout),
        ) as response:
            content = await response.read()
            return HttpResponse(
                status_code=response.status,
                reason=response.reason or "",
                url=str(response.url),
                headers=response.headers,
                content=content,
                encoding=response.get_encoding() if content else "utf-8",
                request=SentRequest(method, url),
            )

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """Send a GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> HttpResponse:
        """Send a POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> HttpResponse:
        """Send a PUT request."""
        return await self.request("PUT", url, **kwargs)
