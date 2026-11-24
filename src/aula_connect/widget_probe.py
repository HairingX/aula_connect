"""A read-only probe of the services Aula's widgets log a guardian in to, and of what they load and answer.

For each widget that logs in to a service of its own, it follows the login chain a browser
follows from Aula - redirects, the forms a page submits by itself, a meta refresh and a script's
plain redirect - on any host but the logins of Aula, MitID and UniLogin themselves. At the page
the chain ends at, it reads the scripts the page loads, finds in them the addresses the service's
own code names, and reads those with GET, but for any whose name tells of a change; then the
addresses it is asked to read. It tells how each step is built, never a value: not of a token, a
cookie, a field or an assertion. A JSON answer is told by its shape and pseudonymised, as Aula's
answers are.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qsl, urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup, Tag

from .pseudonym import Pseudonymiser, shapes

_LOGGER = logging.getLogger(__name__)

VERSION = 4
"""The version of the probe, told in its report."""
NOT_FOLLOWED = ("aula.dk", "mitid.dk", "nemlog-in.dk", "unilogin.dk", "uni-login.dk", "stil.dk")
"""The domains of the logins the probe never follows into, with their subdomains."""
MAX_HOPS = 25
"""The most steps of a login chain followed."""
REQUEST_TIMEOUT = 30
"""Seconds a single request may take."""
MAX_SCRIPTS = 40
"""The most scripts read for each widget."""
MAX_SCRIPT_TEXT = 6_000_000
"""The most characters of scripts and other answers' text kept for each widget, all of them together."""
MAX_FOUND = 60
"""The most addresses found in a service's code read for each widget."""
MAX_FILLED = 20
"""The most addresses read with a placeholder filled from an earlier answer, for each widget."""
MAX_READS = 30
"""The most addresses asked read for each widget."""
MAX_SECONDS = 150
"""The most seconds a widget's probe takes before it reads no more."""
MAX_CANDIDATES = 500
"""The most addresses found in a service's code told."""
MAX_INLINE = 20_000
"""The most characters of each of a page's own scripts kept."""
MAX_INLINES = 20
"""The most of a page's own scripts kept."""
MAX_HEADINGS = 12
"""The most headings of a page kept."""
CHANGING = (
    "delete", "remove", "slet", "fjern", "cancel", "annuller", "logout", "logoff", "signout", "signoff", "logud",
    "update", "opdater", "create", "opret", "tilfoej", "register", "registrer", "meld", "approve", "godkend",
    "reject", "afvis", "submit", "upload", "rediger", "change", "aendr", "reset", "insert", "modify",
)
"""Beginnings of words in an address that tell of a change: such an address is never read unasked."""
CHANGING_WORDS = ("save", "gem", "add", "send", "post", "put", "set", "edit", "accept", "log off", "sign out", "log out")
"""Words in an address that tell of a change only as they are: such an address is never read unasked."""


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
    """A script the page the chain ended at loads, and its text where it was read: on any host but a login not followed."""
    address: ProbeAddress
    status: int
    """The answer's HTTP status; 0 where the script was not read."""
    text: str | None
    """Its text, with every long run of letters and digits replaced by its length; None where not read."""


@dataclass(frozen=True)
class ProbeRead:
    """An address read with GET, and how it was answered."""
    asked: str
    """The address as the service's code names it, or as it was asked, a placeholder filled told as `«name»`."""
    found: str
    """Where it came from: "code", "filled" from an earlier answer, or "asked"."""
    address: ProbeAddress | None
    """None where it was refused, being on no site the chain reached."""
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
class WidgetProbe:
    """What the probe found of one widget: its login chain, the scripts and addresses of its service, and their answers."""
    widget_id: str
    supplier: str
    start: ProbeAddress
    """The widget's address, posted to as Aula's portal does."""
    hops: tuple[ProbeHop, ...]
    ended: str
    """Why the chain ended."""
    stopped_at: str | None
    """The host of a login the probe does not follow, where the chain was stopped there."""
    hosts: tuple[str, ...]
    """The hosts the chain reached; scripts and addresses are read on these only."""
    scripts: tuple[ProbeScript, ...]
    cookies: tuple[ProbeCookie, ...]
    """The cookies held once the chain ended."""
    candidates: tuple[str, ...]
    """Every address the service's code names, as it names it, a query's values left out."""
    reads: tuple[ProbeRead, ...]
    skipped: int = 0
    """The addresses that would have been read but for the most reads or the most seconds."""


@dataclass(frozen=True)
class WidgetProbeReport:
    """What the probe found of each widget that logs in to a service of its own."""
    widgets: tuple[WidgetProbe, ...]
    version: int = VERSION

    def as_dict(self) -> dict[str, Any]:
        """The report as JSON's types."""
        return dataclasses.asdict(self)


def probe_session(connector: aiohttp.BaseConnector | None = None) -> aiohttp.ClientSession:
    """A session for the probe, with cookies of its own, sent back as they were set.

    A service such as Tabulex's portal sets its session in base64 cookies, which aiohttp's
    default jar would send back quoted, and the service fails to read.
    """
    return aiohttp.ClientSession(connector=connector, cookie_jar=aiohttp.CookieJar(quote_cookie=False))


def under(host: str, domains: Sequence[str]) -> bool:
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


_FOUND = re.compile(r"""["'`]((?:https?://[A-Za-z0-9.-]+(?::\d+)?)?/?[A-Za-z0-9_.~{}:$-]+(?:/[A-Za-z0-9_.~{}:$-]*)+(?:\?[^"'`\s<>]*)?)["'`]""")
_KINDS = ("application/", "text/", "image/", "audio/", "video/", "font/", "multipart/", "model/")
_ASSETS = (".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".mp3", ".mp4", ".webp", ".pdf")
_PLACEHOLDER = re.compile(r"\{(\w+)\}|(?<=/):(\w+)")
_FIRST = ("api", "service", "rest", "odata", "handler", ".ashx", ".asmx", ".svc", "json", "data")


def found_in(code: str) -> list[str]:
    """The addresses `code` names: strings with a path, not a media type nor an asset, a query's values left out."""
    found: dict[str, None] = {}
    for match in _FOUND.finditer(code):
        text = match.group(1)
        path = urlsplit(text).path if text.startswith("http") else text.partition("?")[0]
        if text.startswith(_KINDS) or path.lower().endswith(_ASSETS) or path.strip("/.") == "":
            continue
        query = ProbeAddress.of("http://x/?" + text.partition("?")[2]).query_names if "?" in text else ()
        found[text.partition("?")[0] + ("?" + "&".join(query) if query else "")] = None
    return list(found)


def _changes(address: str) -> bool:
    """Whether `address` names a change, by a word of its path, as it is written or in its parts."""
    path = urlsplit(address).path
    whole = re.findall(r"[a-z]+", path.lower())
    parts = re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", path).lower())
    spaced = " " + " ".join(parts) + " "
    return any(word.startswith(CHANGING) for word in (*whole, *parts)) or any(
        f" {word} " in spaced or word.replace(" ", "") in whole for word in CHANGING_WORDS
    )


def _order(candidates: Sequence[str]) -> list[str]:
    """`candidates` that may be read unasked: no change named, no placeholder; those like an API's first."""
    readable = [found for found in candidates if not _changes(found) and not _PLACEHOLDER.search(found) and "$" not in found]
    return sorted(readable, key=lambda found: not any(word in found.lower() for word in _FIRST))


def _filled(candidates: Sequence[str], values: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Each candidate a key of an earlier answer fills, as told and as filled.

    A placeholder in its path, at most one, must be filled; each name of its query is given the
    first value of a key of its name, and left out without one. A candidate is filled where
    anything in it is.
    """
    filled: list[tuple[str, str]] = []
    for found in candidates:
        path, _, query = found.partition("?")
        names = [first or second for first, second in _PLACEHOLDER.findall(path)]
        if _changes(found) or len(names) > 1 or any(name.lower() not in values for name in names):
            continue
        given = [name for name in query.split("&") if name and name.lower() in values]
        if not names and not given:
            continue
        told = _PLACEHOLDER.sub(lambda match: f"«{match.group(1) or match.group(2)}»", path)
        made = _PLACEHOLDER.sub(lambda match: values[(match.group(1) or match.group(2)).lower()][0], path)
        if given:
            told += "?" + "&".join(f"{name}=«{name}»" for name in given)
            made += "?" + "&".join(f"{name}={values[name.lower()][0]}" for name in given)
        filled.append((told, made))
    return filled


def _bases(candidates: Sequence[str], hosts: _Hosts) -> list[str]:
    """The candidates that are a base of an API: whole addresses on a site the chain reached, ending in a slash."""
    return [found for found in candidates if found.startswith("http") and found.endswith("/") and hosts.reach(ProbeAddress.of(found).host)]


def _targets(address: str, base: str, bases: Sequence[str]) -> list[str]:
    """Where `address` is read: against the page's base, and a relative one against each base of an API too."""
    first = urljoin(base, address)
    if address.startswith(("http", "/")):
        return [first]
    return list(dict.fromkeys([first, *(urljoin(other, address) for other in bases)]))


def _values(value: Any, into: dict[str, list[str]], key: str = "") -> None:
    """Note each text and whole number in `value` under its key, in lower case."""
    if isinstance(value, dict):
        for name, item in cast(dict[str, Any], value).items():
            _values(item, into, str(name))
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            _values(item, into, key)
    elif isinstance(value, str | int) and not isinstance(value, bool) and key:
        into.setdefault(key.lower(), []).append(str(value))


_TOKENS = ("access_token", "accesstoken", "id_token", "token", "bearer", "jwt")


def _token(answer: dict[str, Any]) -> str | None:
    """A token `answer` hands out at its top, by a key that names one; None where it hands out none."""
    return next((value for name, value in answer.items() if name.lower() in _TOKENS and isinstance(value, str) and value), None)


class _Hosts:
    """The hosts a chain reached, and whether it may go on to another."""

    def __init__(self, not_followed: Sequence[str]) -> None:
        self.not_followed = tuple(not_followed)
        self.reached: dict[str, None] = {}

    def admit(self, host: str) -> bool:
        """Whether the chain may go on to `host`; noted as reached where it may."""
        if not host or under(host, self.not_followed):
            return False
        self.reached[host.lower().rstrip(".")] = None
        return True

    def reach(self, host: str) -> bool:
        """Whether `host` is of a site the chain reached: under the same domain as a host it reached."""
        return bool(host) and not under(host, self.not_followed) and _site(host) in {_site(reached) for reached in self.reached}

    def load(self, host: str) -> bool:
        """Whether a script on `host` may be loaded, as a browser loads one from anywhere but a login not followed."""
        return bool(host) and not under(host, self.not_followed)


def _site(host: str) -> str:
    """The domain `host` is under, as its last two labels."""
    return ".".join(host.lower().rstrip(".").split(".")[-2:])


@dataclass(frozen=True)
class _Chain:
    hops: tuple[ProbeHop, ...]
    ended: str
    stopped_at: str | None
    url: str
    """The address of the last step."""
    sources: tuple[str, ...] = ()
    """The addresses, in full, of the scripts the page that ended the chain loads."""
    inline: tuple[str, ...] = ()
    """The code of that page's own scripts, as it is."""
    base: str = ""
    """The address the page's own relative addresses are resolved against."""


def _content_type(response: aiohttp.ClientResponse) -> str | None:
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower() or None


async def _follow(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    data: dict[str, str] | None,
    hosts: _Hosts,
    timeout: aiohttp.ClientTimeout,
) -> _Chain:
    """Follow a login chain from `url` as a browser does, but into a login the probe does not follow."""
    hops: list[ProbeHop] = []
    for _ in range(MAX_HOPS):
        address = ProbeAddress.of(url)
        if not hosts.admit(address.host):
            return _Chain(tuple(hops), "a login the probe does not follow", address.host, url)
        try:
            async with session.request(method, url, data=data, allow_redirects=False, timeout=timeout) as response:
                status, location, kind = response.status, response.headers.get("Location"), _content_type(response)
                cookies = _cookies(response, address.host)
                body = await response.text(errors="replace") if kind is not None and "html" in kind else ""
        except (aiohttp.ClientError, TimeoutError) as error:
            hops.append(ProbeHop(method, address, 0, error=type(error).__name__))
            return _Chain(tuple(hops), "an error", None, url)
        _LOGGER.debug("Widget probe: %s %s%s answered HTTP %s", method, address.host, address.path, status)
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
        scripts = _tags(page, "script")
        sources = tuple(urljoin(url, _attribute(script, "src")) for script in scripts if _attribute(script, "src"))
        inline = tuple(script.get_text() for script in scripts if not _attribute(script, "src"))
        ended = "a page a browser stays on" if status == HTTPStatus.OK and body else f"an answer of HTTP {status}"
        base = next((urljoin(url, _attribute(tag, "href")) for tag in _tags(page, "base") if _attribute(tag, "href")), url)
        return _Chain(tuple(hops), ended, None, url, sources, inline, base)
    return _Chain(tuple(hops), f"{MAX_HOPS} steps", None, url)


class _Room:
    """How many characters of text may still be kept."""

    def __init__(self) -> None:
        self.left = MAX_SCRIPT_TEXT

    def keep(self, text: str) -> str:
        kept = masked_script(text)[: max(self.left, 0)]
        self.left -= len(kept)
        return kept


async def _read_scripts(
    session: aiohttp.ClientSession, sources: Sequence[str], hosts: _Hosts, timeout: aiohttp.ClientTimeout, room: _Room
) -> tuple[tuple[ProbeScript, ...], list[str]]:
    """The scripts at `sources`, read from any host but a login not followed; and their texts as they are."""
    scripts: list[ProbeScript] = []
    texts: list[str] = []
    for source in list(dict.fromkeys(sources))[:MAX_SCRIPTS]:
        script = ProbeAddress.of(source)
        if not hosts.load(script.host):
            scripts.append(ProbeScript(script, 0, None))
            continue
        try:
            async with session.get(source, allow_redirects=False, timeout=timeout) as response:
                text = await response.text(errors="replace") if response.status == HTTPStatus.OK else None
        except (aiohttp.ClientError, TimeoutError):
            scripts.append(ProbeScript(script, 0, None))
            continue
        if text is not None:
            texts.append(text)
        scripts.append(ProbeScript(script, response.status, None if text is None else room.keep(text)))
    return tuple(scripts), texts


async def _read(
    session: aiohttp.ClientSession,
    url: str,
    asked: str,
    found: str,
    shown: str,
    hosts: _Hosts,
    timeout: aiohttp.ClientTimeout,
    pseudonymiser_key: bytes,
    room: _Room,
    values: dict[str, list[str]],
    bearer: list[str],
) -> ProbeRead:
    """Read `url` with GET, without following a redirect, and tell how it was answered, its address as `shown`."""
    address = ProbeAddress.of(shown)
    if urlsplit(url).scheme not in ("http", "https") or not hosts.reach(ProbeAddress.of(url).host):
        return ProbeRead(asked, found, None, 0, error="on no site the chain reached")
    headers = {"Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer[0]}"
    try:
        async with session.get(url, allow_redirects=False, timeout=timeout, headers=headers) as response:
            status, kind, location = response.status, _content_type(response), response.headers.get("Location")
            body = await response.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as error:
        return ProbeRead(asked, found, address, 0, error=type(error).__name__)
    moved = ProbeAddress.of(urljoin(url, location)) if location is not None and 300 <= status < 400 else None
    if kind is not None and "json" in kind or body.lstrip()[:1] in ("{", "["):
        try:
            value = json.loads(body)
        except ValueError:
            value = None
        else:
            _values(value, values)
            if not bearer and isinstance(value, dict) and (token := _token(cast(dict[str, Any], value))):
                bearer.append(token)
            pseudonymiser = Pseudonymiser(pseudonymiser_key)
            pseudonymiser.learn(value)
            return ProbeRead(asked, found, address, status, kind, moved, shapes(value), pseudonymiser.value(value), length=len(body))
    if kind is not None and "html" in kind:
        page = _page(BeautifulSoup(body, "html.parser"), url)
        return ProbeRead(asked, found, address, status, kind, moved, page=page, length=len(body))
    if kind is not None and "javascript" in kind:
        return ProbeRead(asked, found, address, status, kind, moved, text=room.keep(body), length=len(body))
    return ProbeRead(asked, found, address, status, kind, moved, length=len(body))


async def probe(
    session: aiohttp.ClientSession,
    widget_id: str,
    supplier: str,
    url: str,
    fields: dict[str, str],
    reads: Sequence[str] = (),
    not_followed: Sequence[str] = NOT_FOLLOWED,
) -> WidgetProbe:
    """POST `fields` to the widget's `url` as Aula's portal does, follow its login, and read what its service loads and names.

    The chain is followed as a browser follows it - through redirects, forms a page submits by
    itself, a meta refresh and a script's plain redirect - at most MAX_HOPS steps, but never
    into a host under `not_followed`; it stops at a page a browser stays on, and at an error.
    Then the scripts that page loads are read, from any host but those, and the addresses
    the page's and scripts' code names: those without a placeholder, at most MAX_FOUND, those
    like an API's first; then those with one placeholder a key of an earlier JSON answer fills;
    then each of `reads`, resolved against the page. Every read is a GET, sent as an app's own
    request is, of an address whose path names no change, unless asked, on a site the chain
    reached; once an answer hands out a token, the reads after it send it as a bearer token, as
    an app does. Nothing is ever logged but how the steps went.
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    clock = asyncio.get_running_loop()
    deadline = clock.time() + MAX_SECONDS
    hosts = _Hosts(not_followed)
    room = _Room()
    chain = await _follow(session, url, "POST", fields, hosts, timeout)
    scripts, texts = await _read_scripts(session, chain.sources, hosts, timeout, room)
    candidates: dict[str, None] = {}
    for code in (*chain.inline, *texts):
        candidates.update(dict.fromkeys(found_in(code)))
    named = list(candidates)
    key = secrets.token_bytes(32)
    values: dict[str, list[str]] = {}
    bearer: list[str] = []
    found: list[ProbeRead] = []
    skipped = 0

    async def read_all(plan: list[tuple[str, str, str, str]], most: int) -> None:
        nonlocal skipped
        skipped += max(len(plan) - most, 0)
        for asked, kind, target, shown in plan[:most]:
            if clock.time() > deadline:
                skipped += 1
                continue
            found.append(await _read(session, target, asked, kind, shown, hosts, timeout, key, room, values, bearer))

    base = chain.base or chain.url
    if chain.ended == "a page a browser stays on":
        bases = _bases(named, hosts)
        await read_all([(address, "code", target, target) for address in _order(named) for target in _targets(address, base, bases)], MAX_FOUND)
        filled = [
            (told, "filled", target, shown)
            for told, address in _filled(named, values)
            for target, shown in zip(_targets(address, base, bases), _targets(told, base, bases), strict=True)
        ]
        await read_all(filled, MAX_FILLED)
    await read_all([(asked, "asked", urljoin(base, asked), urljoin(base, asked)) for asked in reads], MAX_READS)
    held = sorted({ProbeCookie(cookie.key, cookie["domain"]) for cookie in session.cookie_jar}, key=lambda cookie: (cookie.domain, cookie.name))
    return WidgetProbe(
        widget_id,
        supplier,
        ProbeAddress.of(url),
        chain.hops,
        chain.ended,
        chain.stopped_at,
        tuple(hosts.reached),
        scripts,
        tuple(held),
        tuple(named[:MAX_CANDIDATES]),
        tuple(found),
        skipped,
    )
