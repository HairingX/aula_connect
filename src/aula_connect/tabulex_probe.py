"""A read-only probe of how IST's Tabulex logs a guardian in from Aula, and what its parent portal loads and answers.

It follows the login chain a browser follows from Aula's Tabulex widget - redirects, the forms a
page submits by itself, a meta refresh and a script's plain redirect - on the hosts of IST and
Tabulex only; then the portal's own login with what that chain left; reads the scripts the pages
the chains end at load; and reads, with GET only, the addresses it is given. It tells how each
step is built, never a value: not of a token, a cookie, a field or an assertion. A JSON answer
is told by its shape and pseudonymised, as Aula's answers are.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup, Tag

from .pseudonym import Pseudonymiser, shapes

_LOGGER = logging.getLogger(__name__)

VERSION = 3
"""The version of the probe, told in its report."""
TABULEX_DOMAINS = ("ist.dk", "tabulex.dk", "tabulex.net")
"""The domains the probe follows the login chain on and reads from, with their subdomains."""
TABULEX_PORTAL = "https://foraeldre.tabulex.net/"
"""The parent portal."""
MAX_HOPS = 25
"""The most steps of a login chain followed."""
REQUEST_TIMEOUT = 30
"""Seconds a single request may take."""
MAX_SCRIPTS = 40
"""The most scripts read."""
MAX_SCRIPT_TEXT = 6_000_000
"""The most characters of scripts kept, all of them together."""
MAX_READS = 30
"""The most addresses read."""
MAX_INLINE = 20_000
"""The most characters of each of a page's own scripts kept."""
MAX_INLINES = 20
"""The most of a page's own scripts kept."""
MAX_HEADINGS = 12
"""The most headings of a page kept."""


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
    """A cookie, by its name and domain, without its value."""
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
    """How a page is built, without the values of its fields.

    Its title and headings are kept with every number of four digits or more, and every long run
    of letters and digits, replaced by its length. Its scripts' own code is kept with every string
    replaced: an address by its host and path, as `ProbeAddress` tells it, anything else by its
    length; and every long run of letters and digits by its length, as it may be a token.
    """
    title: str | None = None
    headings: tuple[str, ...] = ()
    forms: tuple[ProbeForm, ...] = ()
    scripts: tuple[ProbeAddress, ...] = ()
    """The scripts it loads."""
    inline: tuple[str, ...] = ()
    """Its scripts' own code, every string replaced."""
    refresh: ProbeAddress | None = None
    """Where a meta refresh sends on to."""
    redirect: ProbeAddress | None = None
    """Where a script of its own sends on to, by a plain address."""


@dataclass(frozen=True)
class ProbeHop:
    """One step of a login chain: the request, how it was answered, and how the next step was found."""
    method: str
    address: ProbeAddress
    status: int
    """The answer's HTTP status; 0 where none came."""
    content_type: str | None = None
    location: ProbeAddress | None = None
    """Where a redirect sent on to."""
    next: str | None = None
    """How the next step was found: "redirect", "form", "refresh" or "script"; None at the end."""
    form_action: ProbeAddress | None = None
    """Where the form the page submits by itself posts to."""
    form_fields: tuple[str, ...] = ()
    """The names of that form's fields."""
    cookies: tuple[ProbeCookie, ...] = ()
    """The cookies the answer set."""
    page: ProbePage | None = None
    """How the page is built, where the answer is one."""
    error: str | None = None
    """The kind of error that came in place of an answer."""


@dataclass(frozen=True)
class ProbeScript:
    """A script a page the chains ended at loads, and its text where it was read: on the domains followed."""
    address: ProbeAddress
    status: int
    """The answer's HTTP status; 0 where the script was not read."""
    text: str | None
    """Its text, with every long run of letters and digits replaced by its length; None where not read."""


@dataclass(frozen=True)
class ProbeRead:
    """An address read with GET, as asked, and how it was answered."""
    asked: str
    """The address as it was asked."""
    address: ProbeAddress | None
    """None where it was refused, being outside the domains followed."""
    status: int
    """The answer's HTTP status; 0 where none came."""
    content_type: str | None = None
    location: ProbeAddress | None = None
    """Where a redirect sent on to; it is not followed."""
    shape: dict[str, list[str]] | None = None
    """The type at each place of a JSON answer."""
    answer: Any = None
    """A JSON answer, with what tells who someone is replaced."""
    page: ProbePage | None = None
    """How an HTML answer is built."""
    text: str | None = None
    """A script's text, with every long run of letters and digits replaced by its length."""
    length: int = 0
    """The answer's length in characters."""
    error: str | None = None
    """The kind of error that came in place of an answer, or why it was not asked."""


@dataclass(frozen=True)
class TabulexProbeReport:
    """What the probe found: the login chain from Aula, the portal's own login chain, their scripts, and the reads asked."""
    widget_id: str
    hops: tuple[ProbeHop, ...]
    ended: str
    """Why the chain from Aula ended."""
    stopped_at: str | None
    """The host outside the domains followed where the chain from Aula was stopped; None where it was not."""
    portal_hops: tuple[ProbeHop, ...]
    """The portal's own login chain, followed with what the chain from Aula left."""
    portal_ended: str
    """Why the portal's chain ended."""
    portal_stopped_at: str | None
    scripts: tuple[ProbeScript, ...]
    """The scripts the pages the chains ended at load."""
    cookies: tuple[ProbeCookie, ...]
    """The cookies held once the chains ended."""
    reads: tuple[ProbeRead, ...] = ()
    version: int = VERSION

    def as_dict(self) -> dict[str, Any]:
        """The report as JSON's types."""
        return dataclasses.asdict(self)


def allowed(host: str, domains: tuple[str, ...]) -> bool:
    """Whether `host` is one of `domains` or under one."""
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _cookies(response: aiohttp.ClientResponse, host: str) -> tuple[ProbeCookie, ...]:
    return tuple(ProbeCookie(name, morsel["domain"] or host) for name, morsel in response.cookies.items())


def _tags(node: Tag, name: str | list[str] | None = None, having: str | None = None) -> list[Tag]:
    """The elements under `node` named `name`, or having the attribute `having`, leaving out text."""
    found = node.find_all(name) if having is None else node.find_all(attrs={having: True})
    return [element for element in found if isinstance(element, Tag)]


def _attribute(tag: Tag, name: str) -> str:
    """The value of the attribute `name`, empty where it is missing."""
    value = tag.get(name)
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


_BUTTONS = ("submit", "button", "image", "reset")


_SUBMITS = re.compile(r"\.(?:submit|click)\(\s*\)")


def _submits_itself(page: BeautifulSoup) -> bool:
    """Whether the page submits a form as it loads, as a browser running its scripts sees.

    By its body's `onload`; by an inline script that submits outside any function, which a
    page's button might call instead; or, as SimpleSAMLphp's and AD FS's pages do, by a script
    it loads, telling those without scripts in a `noscript` to press the button.
    """
    if any(_SUBMITS.search(_attribute(element, "onload")) for element in _tags(page, having="onload")):
        return True
    inline = [script.get_text() for script in _tags(page, "script") if not _attribute(script, "src")]
    if any(_SUBMITS.search(code) and "function" not in code for code in inline):
        return True
    return bool(page.find("noscript")) and bool(_tags(page, "script")) or bool(page.find(id="postLoginSubmitButton"))


def _auto_form(page: BeautifulSoup) -> Tag | None:
    """The form the page submits by itself: all its fields hidden, on a page that submits it as it loads."""
    if not _submits_itself(page):
        return None
    for form in _tags(page, "form"):
        fields = [
            element for element in _tags(form, ["input", "select", "textarea"])
            if (_attribute(element, "type") or "text").lower() not in _BUTTONS
        ]
        if fields and all(element.name == "input" and _attribute(element, "type").lower() == "hidden" for element in fields):
            return form
    return None


_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
_ADDRESS = re.compile(r"""^(?:https?://[^\s"'`<>]+|/[A-Za-z0-9._~%/-]*(?:\?[^\s"'`<>]*)?)$""")
_RUN = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
_NUMBER = re.compile(r"\d{4,}")
_REDIRECT = re.compile(
    r"""(?:location(?:\.href)?\s*=\s*|location\.(?:replace|assign)\(\s*)(["'])(?P<to>[^"'\s]+)\1"""
)


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


def masked_script(text: str) -> str:
    """A script's `text` with every run of letters and digits long enough to be a token replaced by its length."""
    return _LONG_RUN.sub(lambda run: f"«{len(run.group(0))}»", text)


def _text(text: str) -> str:
    """A title's or heading's `text` on one line, every long number and run replaced by its length."""
    line = " ".join(text.split())[:200]
    return _RUN.sub(lambda run: f"«{len(run.group(0))}»", _NUMBER.sub(lambda run: f"«{len(run.group(0))}»", line))


def _redirect(page: BeautifulSoup) -> str | None:
    """The plain address a script of the page's own sends the browser on to; None where none does."""
    for script in _tags(page, "script"):
        if not _attribute(script, "src") and (found := _REDIRECT.search(script.get_text())):
            return found.group("to")
    return None


def _refresh(page: BeautifulSoup) -> str | None:
    """The address a meta refresh sends on to; None where none does."""
    refresh = next((meta for meta in _tags(page, "meta") if _attribute(meta, "http-equiv").lower() == "refresh"), None)
    target = _attribute(refresh, "content").partition("url=")[2].strip("'\" ") if refresh is not None else ""
    return target or None


def _page(page: BeautifulSoup, url: str) -> ProbePage:
    """How `page`, read at `url`, is built."""
    forms = tuple(
        ProbeForm(
            ProbeAddress.of(urljoin(url, _attribute(form, "action"))) if _attribute(form, "action") else None,
            (_attribute(form, "method") or "GET").upper(),
            tuple(
                (_attribute(element, "name"), (_attribute(element, "type") or element.name or "").lower())
                for element in _tags(form, ["input", "select", "textarea", "button"])
            ),
        )
        for form in _tags(page, "form")
    )
    scripts = _tags(page, "script")
    loaded = tuple(ProbeAddress.of(urljoin(url, _attribute(script, "src"))) for script in scripts if _attribute(script, "src"))
    inline = tuple(masked(script.get_text()) for script in scripts if not _attribute(script, "src") and script.get_text().strip())
    title = page.find("title")
    headings = tuple(_text(heading.get_text()) for heading in _tags(page, ["h1", "h2", "h3", "h4"]) if heading.get_text().strip())
    refresh, redirect = _refresh(page), _redirect(page)
    return ProbePage(
        _text(title.get_text()) if title is not None else None,
        headings[:MAX_HEADINGS],
        forms,
        loaded,
        inline[:MAX_INLINES],
        ProbeAddress.of(urljoin(url, refresh)) if refresh else None,
        ProbeAddress.of(urljoin(url, redirect)) if redirect else None,
    )


@dataclass(frozen=True)
class _Chain:
    hops: tuple[ProbeHop, ...]
    ended: str
    stopped_at: str | None
    url: str
    """The address of the last step."""
    sources: tuple[str, ...] = field(default=())
    """The addresses, in full, of the scripts the page that ended the chain loads."""


def _content_type(response: aiohttp.ClientResponse) -> str | None:
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower() or None


async def _follow(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    data: dict[str, str] | None,
    domains: tuple[str, ...],
    timeout: aiohttp.ClientTimeout,
) -> _Chain:
    """Follow a login chain from `url` as a browser does, on `domains` only."""
    hops: list[ProbeHop] = []
    for _ in range(MAX_HOPS):
        address = ProbeAddress.of(url)
        if not allowed(address.host, domains):
            return _Chain(tuple(hops), "a host outside the domains followed", address.host, url)
        try:
            async with session.request(method, url, data=data, allow_redirects=False, timeout=timeout) as response:
                status, location, kind = response.status, response.headers.get("Location"), _content_type(response)
                cookies = _cookies(response, address.host)
                body = await response.text(errors="replace") if kind is not None and "html" in kind else ""
        except (aiohttp.ClientError, TimeoutError) as error:
            hops.append(ProbeHop(method, address, 0, error=type(error).__name__))
            return _Chain(tuple(hops), "an error", None, url)
        _LOGGER.debug("Tabulex probe: %s %s%s answered HTTP %s", method, address.host, address.path, status)
        if location is not None and 300 <= status < 400:
            url = urljoin(url, location)
            hops.append(ProbeHop(method, address, status, kind, ProbeAddress.of(url), "redirect", cookies=cookies))
            if status not in (HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT):
                method, data = "GET", None
            continue
        page = BeautifulSoup(body, "html.parser")
        summary = _page(page, url) if body else None
        form = _auto_form(page) if status == HTTPStatus.OK else None
        if form is not None:
            inputs = [element for element in _tags(form, "input") if _attribute(element, "name") and _attribute(element, "type").lower() == "hidden"]
            action = urljoin(url, _attribute(form, "action") or url)
            names = tuple(_attribute(element, "name") for element in inputs)
            hops.append(ProbeHop(method, address, status, kind, None, "form", ProbeAddress.of(action), names, cookies, summary))
            url, method = action, (_attribute(form, "method") or "GET").upper()
            data = {_attribute(element, "name"): _attribute(element, "value") for element in inputs}
            continue
        onward = (_refresh(page), "refresh") if status == HTTPStatus.OK else (None, "")
        if status == HTTPStatus.OK and onward[0] is None:
            onward = (_redirect(page), "script")
        if onward[0] is not None:
            hops.append(ProbeHop(method, address, status, kind, None, onward[1], cookies=cookies, page=summary))
            url, method, data = urljoin(url, onward[0]), "GET", None
            continue
        hops.append(ProbeHop(method, address, status, kind, cookies=cookies, page=summary))
        sources = tuple(urljoin(url, _attribute(script, "src")) for script in _tags(page, "script") if _attribute(script, "src"))
        ended = "a page a browser stays on" if status == HTTPStatus.OK and body else f"an answer of HTTP {status}"
        return _Chain(tuple(hops), ended, None, url, sources)
    return _Chain(tuple(hops), f"{MAX_HOPS} steps", None, url)


async def follow(
    session: aiohttp.ClientSession,
    widget_id: str,
    url: str,
    fields: dict[str, str],
    domains: tuple[str, ...] = TABULEX_DOMAINS,
    portal: str = TABULEX_PORTAL,
    reads: Sequence[str] = (),
) -> TabulexProbeReport:
    """POST `fields` to the widget's `url` as Aula's portal does, follow the login chain, then the portal's own.

    Each chain is followed as a browser follows it - through redirects, forms a page submits by
    itself, a meta refresh and a script's plain redirect - at most MAX_HOPS steps, and only on
    `domains`; it stops at a host elsewhere, at a page a browser stays on, and at an error. The
    portal's chain starts at `portal` with what the first chain left in `session`. Then each
    script the pages the chains ended at load is read, on `domains`, and each of `reads` with
    GET: an address on `domains`, or a path on the portal's site. Nothing is ever logged but how
    the steps went.
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    aula = await _follow(session, url, "POST", fields, domains, timeout)
    own = await _follow(session, portal, "GET", None, domains, timeout)
    scripts = await _read_scripts(session, aula.sources + own.sources, domains, timeout)
    key = secrets.token_bytes(32)
    found = [await _read(session, urljoin(portal, asked), asked, domains, timeout, key) for asked in reads[:MAX_READS]]
    held = tuple(sorted({ProbeCookie(cookie.key, cookie["domain"]) for cookie in session.cookie_jar}, key=lambda cookie: (cookie.domain, cookie.name)))
    return TabulexProbeReport(
        widget_id, aula.hops, aula.ended, aula.stopped_at, own.hops, own.ended, own.stopped_at, scripts, held, tuple(found)
    )


async def _read_scripts(
    session: aiohttp.ClientSession, sources: tuple[str, ...], domains: tuple[str, ...], timeout: aiohttp.ClientTimeout
) -> tuple[ProbeScript, ...]:
    """The scripts at `sources`, read where on `domains`, at most MAX_SCRIPT_TEXT characters of them together."""
    scripts: list[ProbeScript] = []
    room = MAX_SCRIPT_TEXT
    for source in list(dict.fromkeys(sources))[:MAX_SCRIPTS]:
        script = ProbeAddress.of(source)
        if not allowed(script.host, domains) or room <= 0:
            scripts.append(ProbeScript(script, 0, None))
            continue
        try:
            async with session.get(source, allow_redirects=False, timeout=timeout) as response:
                text = await response.text(errors="replace") if response.status == HTTPStatus.OK else None
        except (aiohttp.ClientError, TimeoutError):
            scripts.append(ProbeScript(script, 0, None))
            continue
        kept = masked_script(text)[:room] if text is not None else None
        room -= len(kept or "")
        scripts.append(ProbeScript(script, response.status, kept))
    return tuple(scripts)


async def _read(
    session: aiohttp.ClientSession,
    url: str,
    asked: str,
    domains: tuple[str, ...],
    timeout: aiohttp.ClientTimeout,
    key: bytes,
) -> ProbeRead:
    """Read `url` with GET, without following a redirect, and tell how it was answered."""
    address = ProbeAddress.of(url)
    if urlsplit(url).scheme not in ("http", "https") or not allowed(address.host, domains):
        return ProbeRead(asked, None, 0, error="outside the domains followed")
    try:
        async with session.get(url, allow_redirects=False, timeout=timeout) as response:
            status, kind, location = response.status, _content_type(response), response.headers.get("Location")
            body = await response.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as error:
        return ProbeRead(asked, address, 0, error=type(error).__name__)
    moved = ProbeAddress.of(urljoin(url, location)) if location is not None and 300 <= status < 400 else None
    if kind is not None and "json" in kind or body.lstrip()[:1] in ("{", "["):
        try:
            value = json.loads(body)
        except ValueError:
            value = None
        else:
            pseudonymiser = Pseudonymiser(key)
            pseudonymiser.learn(value)
            return ProbeRead(asked, address, status, kind, moved, shapes(value), pseudonymiser.value(value), length=len(body))
    if kind is not None and "html" in kind:
        return ProbeRead(asked, address, status, kind, moved, page=_page(BeautifulSoup(body, "html.parser"), url), length=len(body))
    if kind is not None and "javascript" in kind:
        return ProbeRead(asked, address, status, kind, moved, text=masked_script(body)[:MAX_SCRIPT_TEXT], length=len(body))
    return ProbeRead(asked, address, status, kind, moved, length=len(body))
