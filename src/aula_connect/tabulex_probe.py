"""A read-only probe of how IST's Tabulex logs a guardian in from Aula, and what its parent portal loads.

It follows the login chain a browser follows from Aula's Tabulex widget - redirects, and the
forms a page submits by itself - on the hosts of IST and Tabulex only, then reads the portal's
page and its scripts. It tells how each step is built, never a value: not of a token, a cookie,
a field, an assertion, nor any text of a page.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)

TABULEX_DOMAINS = ("ist.dk", "tabulex.dk", "tabulex.net")
"""The domains the probe follows the login chain on, with their subdomains."""
TABULEX_PORTAL = "https://foraeldre.tabulex.net/"
"""The parent portal read at the end of the chain."""
MAX_HOPS = 15
"""The most steps of the login chain followed."""
REQUEST_TIMEOUT = 30
"""Seconds a single request may take."""
MAX_SCRIPTS = 30
"""The most scripts of the portal's page read."""


@dataclass(frozen=True)
class ProbeAddress:
    """Where a request went: its host and path, and the names of its query's parameters, without their values."""
    host: str
    path: str
    query_names: tuple[str, ...]

    @staticmethod
    def of(url: str) -> ProbeAddress:
        """The address of `url`."""
        parts = urlsplit(url)
        names = tuple(dict.fromkeys(name for name, _ in parse_qsl(parts.query, keep_blank_values=True)))
        return ProbeAddress(parts.hostname or "", parts.path or "/", names)


@dataclass(frozen=True)
class ProbeCookie:
    """A cookie a step set, by its name and domain, without its value."""
    name: str
    domain: str


@dataclass(frozen=True)
class ProbeForm:
    """A form on a page: where it posts, how, and the names and types of its fields, without their values."""
    action: ProbeAddress | None
    method: str
    fields: tuple[tuple[str, str], ...]
    """Each field's name and type."""


@dataclass(frozen=True)
class ProbePage:
    """How a page is built, without any of its text or values.

    Its scripts' own code is kept with every string replaced: an address by its host and path, as
    `ProbeAddress` tells it, anything else by its length; and every long run of letters and
    digits by its length, as it may be a token.
    """
    forms: tuple[ProbeForm, ...] = ()
    scripts: tuple[ProbeAddress, ...] = ()
    """The scripts it loads."""
    inline: tuple[str, ...] = ()
    """Its scripts' own code, every string replaced."""
    refresh: ProbeAddress | None = None
    """Where a meta refresh sends on to."""


@dataclass(frozen=True)
class ProbeHop:
    """One step of the login chain: the request, and how it was answered."""
    method: str
    address: ProbeAddress
    status: int
    """The answer's HTTP status; 0 where none came."""
    location: ProbeAddress | None = None
    """Where a redirect sent on to."""
    form_action: ProbeAddress | None = None
    """Where the page's form, submitted by the page itself, posts to."""
    form_fields: tuple[str, ...] = ()
    """The names of that form's fields."""
    cookies: tuple[ProbeCookie, ...] = ()
    needs_javascript: bool = False
    """Whether the page seemed to need JavaScript beyond submitting a form by itself."""
    page: ProbePage | None = None
    """How the page that ended the chain is built."""
    error: str | None = None
    """The kind of error that came in place of an answer."""


@dataclass(frozen=True)
class ProbeScript:
    """A script the portal's page loads, and its text where it was read: on the portal's own site."""
    address: ProbeAddress
    status: int
    """The answer's HTTP status; 0 where the script was not read."""
    text: str | None


@dataclass(frozen=True)
class TabulexProbeReport:
    """What the probe found: the login chain from Aula, the portal's own login chain, and the portal's scripts."""
    widget_id: str
    hops: tuple[ProbeHop, ...]
    ended: str
    """Why the chain from Aula ended."""
    stopped_at: str | None
    """The host outside the domains followed where the chain from Aula was stopped; None where it was not."""
    portal_hops: tuple[ProbeHop, ...]
    """The portal's own login chain, followed with what the chain from Aula left; empty where its host is outside the domains followed."""
    portal_ended: str
    """Why the portal's chain ended."""
    scripts: tuple[ProbeScript, ...]
    """The scripts of the page the portal's chain ended at, on the portal's own site."""

    def as_dict(self) -> dict[str, Any]:
        """The report as JSON's types."""
        return dataclasses.asdict(self)


def allowed(host: str, domains: tuple[str, ...]) -> bool:
    """Whether `host` is one of `domains` or under one."""
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _cookies(response: aiohttp.ClientResponse, host: str) -> tuple[ProbeCookie, ...]:
    return tuple(ProbeCookie(name, morsel["domain"] or host) for name, morsel in response.cookies.items())


def _tags(node: Tag, name: str | None = None, having: str | None = None) -> list[Tag]:
    """The elements under `node` named `name`, or having the attribute `having`, leaving out text."""
    found = node.find_all(name) if having is None else node.find_all(attrs={having: True})
    return [element for element in found if isinstance(element, Tag)]


def _attribute(tag: Tag, name: str) -> str:
    """The value of the attribute `name`, empty where it is missing."""
    value = tag.get(name)
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


def _auto_form(page: BeautifulSoup) -> Tag | None:
    """The form the page submits by itself: all its fields hidden, and submitted on load or by a script."""
    loading = " ".join(_attribute(element, "onload") for element in _tags(page, having="onload"))
    scripts = " ".join(script.get_text() for script in _tags(page, "script"))
    if not any(call in loading + scripts for call in ("submit(", ".click(")):
        return None
    for form in _tags(page, "form"):
        fields = [field for field in _tags(form, "input") if (_attribute(field, "type") or "text").lower() not in ("submit", "button")]
        if fields and all(_attribute(field, "type").lower() == "hidden" for field in fields):
            return form
    return None


def _needs_javascript(page: BeautifulSoup) -> bool:
    return bool(page.find("script") or page.find("noscript"))


_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
_ADDRESS = re.compile(r"""^(?:https?://[^\s"'`<>]+|/[A-Za-z0-9._~%/-]*(?:\?[^\s"'`<>]*)?)$""")
_RUN = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
MAX_INLINE = 20_000
"""The most characters of each of a page's own scripts kept."""
MAX_INLINES = 20
"""The most of a page's own scripts kept."""


def _string(match: re.Match[str]) -> str:
    quote, text = match.group(1), match.group(2)
    if _ADDRESS.match(text):
        address = ProbeAddress.of(text if text.startswith("http") else "relative:" + text)
        query = "?" + "&".join(address.query_names) if address.query_names else ""
        host = address.host if text.startswith("http") else ""
        return f"{quote}{host}{address.path}{query}{quote}"
    return f"{quote}«{len(text)}»{quote}"


def masked(code: str) -> str:
    """`code` with every string replaced: an address by its host, path and query's names, anything
    else by its length; and every run of letters and digits long enough to be a token by its
    length."""
    return _RUN.sub(lambda run: f"«{len(run.group(0))}»", _STRING.sub(_string, code[:MAX_INLINE]))


def _page(page: BeautifulSoup, url: str) -> ProbePage:
    """How `page`, read at `url`, is built: its forms, the scripts it loads, its own scripts masked, and a meta refresh."""
    forms = tuple(
        ProbeForm(
            ProbeAddress.of(urljoin(url, _attribute(form, "action"))) if _attribute(form, "action") else None,
            (_attribute(form, "method") or "GET").upper(),
            tuple(
                (_attribute(field, "name"), (_attribute(field, "type") or field.name).lower())
                for field in _tags(form) if field.name in ("input", "select", "textarea", "button")
            ),
        )
        for form in _tags(page, "form")
    )
    scripts = _tags(page, "script")
    loaded = tuple(ProbeAddress.of(urljoin(url, _attribute(script, "src"))) for script in scripts if _attribute(script, "src"))
    inline = tuple(masked(script.get_text()) for script in scripts if not _attribute(script, "src") and script.get_text().strip())
    refresh = next((meta for meta in _tags(page, "meta") if _attribute(meta, "http-equiv").lower() == "refresh"), None)
    target = _attribute(refresh, "content").partition("url=")[2] if refresh is not None else ""
    return ProbePage(forms, loaded, inline[:MAX_INLINES], ProbeAddress.of(urljoin(url, target.strip("'\" "))) if target else None)


@dataclass(frozen=True)
class _Chain:
    hops: tuple[ProbeHop, ...]
    ended: str
    stopped_at: str | None
    url: str
    """The address of the last step."""
    sources: tuple[str, ...] = ()
    """The addresses, in full, of the scripts the page that ended the chain loads."""


async def _follow(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    data: dict[str, str] | None,
    domains: tuple[str, ...],
    timeout: aiohttp.ClientTimeout,
) -> _Chain:
    """Follow a login chain from `url` through redirects and forms a page submits by itself."""
    hops: list[ProbeHop] = []
    ended, stopped_at = f"{MAX_HOPS} steps", None
    for _ in range(MAX_HOPS):
        address = ProbeAddress.of(url)
        if not allowed(address.host, domains):
            ended, stopped_at = "a host outside the domains followed", address.host
            break
        try:
            async with session.request(method, url, data=data, allow_redirects=False, timeout=timeout) as response:
                status, location = response.status, response.headers.get("Location")
                cookies = _cookies(response, address.host)
                body = await response.text(errors="replace") if "html" in response.headers.get("Content-Type", "") else ""
        except (aiohttp.ClientError, TimeoutError) as error:
            hops.append(ProbeHop(method, address, 0, error=type(error).__name__))
            ended = "an error"
            break
        _LOGGER.debug("Tabulex probe: %s %s%s answered HTTP %s", method, address.host, address.path, status)
        if location is not None and 300 <= status < 400:
            url = urljoin(url, location)
            hops.append(ProbeHop(method, address, status, location=ProbeAddress.of(url), cookies=cookies))
            method, data = "GET", None
            continue
        page = BeautifulSoup(body, "html.parser")
        form = _auto_form(page) if status == HTTPStatus.OK else None
        if form is None:
            needs = status == HTTPStatus.OK and _needs_javascript(page)
            hops.append(ProbeHop(method, address, status, cookies=cookies, needs_javascript=needs, page=_page(page, url) if body else None))
            ended = "a page that needs JavaScript" if needs else f"an answer of HTTP {status}"
            sources = tuple(urljoin(url, _attribute(script, "src")) for script in _tags(page, "script") if _attribute(script, "src"))
            return _Chain(tuple(hops), ended, stopped_at, url, sources)
        inputs = [field for field in _tags(form, "input") if _attribute(field, "name")]
        action = urljoin(url, _attribute(form, "action") or url)
        names = tuple(_attribute(field, "name") for field in inputs)
        hops.append(ProbeHop(method, address, status, form_action=ProbeAddress.of(action), form_fields=names, cookies=cookies))
        url, method = action, (_attribute(form, "method") or "GET").upper()
        data = {_attribute(field, "name"): _attribute(field, "value") for field in inputs}
    return _Chain(tuple(hops), ended, stopped_at, url)


async def follow(
    session: aiohttp.ClientSession,
    widget_id: str,
    url: str,
    fields: dict[str, str],
    domains: tuple[str, ...] = TABULEX_DOMAINS,
    portal: str = TABULEX_PORTAL,
) -> TabulexProbeReport:
    """POST `fields` to the widget's `url` as Aula's portal does, follow the login chain, then the portal's own.

    Each chain is followed through redirects and through forms a page submits by itself, at most
    MAX_HOPS steps, and only on `domains`; it stops at a host elsewhere, at a page that is no
    such form, and at an error. The portal's chain starts at `portal` with what the first chain
    left in `session`; each script of the page it ends at, on the portal's own site, is read.
    Nothing is ever logged but how the steps went.
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    aula = await _follow(session, url, "POST", fields, domains, timeout)
    portal_chain = _Chain((), "a host outside the domains followed", ProbeAddress.of(portal).host, portal)
    scripts: tuple[ProbeScript, ...] = ()
    if allowed(ProbeAddress.of(portal).host, domains):
        portal_chain = await _follow(session, portal, "GET", None, domains, timeout)
        if ProbeAddress.of(portal_chain.url).host == ProbeAddress.of(portal).host:
            scripts = await _read_scripts(session, portal_chain.url, portal_chain.sources, timeout)
    return TabulexProbeReport(
        widget_id, aula.hops, aula.ended, aula.stopped_at, portal_chain.hops, portal_chain.ended, scripts
    )


async def _read_scripts(
    session: aiohttp.ClientSession, url: str, sources: tuple[str, ...], timeout: aiohttp.ClientTimeout
) -> tuple[ProbeScript, ...]:
    """The scripts at `sources`, loaded by the page at `url`, read where on its own site."""
    host = ProbeAddress.of(url).host
    scripts: list[ProbeScript] = []
    for source in list(dict.fromkeys(sources))[:MAX_SCRIPTS]:
        script = ProbeAddress.of(source)
        if script.host != host:
            scripts.append(ProbeScript(script, 0, None))
            continue
        try:
            async with session.get(source, allow_redirects=False, timeout=timeout) as response:
                text = await response.text(errors="replace") if response.status == HTTPStatus.OK else None
                scripts.append(ProbeScript(script, response.status, text))
        except (aiohttp.ClientError, TimeoutError):
            scripts.append(ProbeScript(script, 0, None))
    return tuple(scripts)
