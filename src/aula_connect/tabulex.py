"""IST's Tabulex parent portal, logged in to through Aula's widget: the children, their absence, and reporting one sick.

The portal is an AngularJS app on an ASP.NET API: its children are known by their CPR number, a
credential here, never logged nor told. A report is sent once and never again, and cannot be
taken back: Tabulex itself says so.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import urlsplit

import aiohttp

from .api.models.aula_profile_models import AulaChildProfile
from .capture import Recorder
from .http import HttpResponse, HttpSession
from .widget_probe import NOT_FOLLOWED, app_headers, log_in

_LOGGER = logging.getLogger(__name__)

PORTAL = "https://foraeldre.tabulex.net"
"""The parent portal, where the login from Aula ends."""
SICK = "Sygdom"
"""The reason Tabulex gives an absence for sickness."""


class TabulexError(Exception):
    """Tabulex could not be logged in to, or refused or failed a request; the text holds none of its data."""


@dataclass(frozen=True)
class TabulexChild:
    """A child the guardian has access to in Tabulex."""
    cpr: str = field(repr=False)
    """The child's CPR number, by which Tabulex knows it: a credential, never logged nor told."""
    first_name: str
    last_name: str
    school_code: str | None = None
    school_name: str | None = None
    class_name: str | None = None
    school_absence: bool | None = None
    """Whether the guardian may see and report the child's absence from school."""


@dataclass(frozen=True)
class TabulexDay:
    """What Tabulex has of a child's absence on a day."""
    day: Any = None
    """The day of the absence, as Tabulex gives it; None where it has none."""
    reason: str | None = None
    half_days: bool = False
    """Whether the school registers absence by half days, by first and last lesson."""
    grade: int | None = None
    first_lesson_reason: str | None = None
    last_lesson_reason: str | None = None

    @property
    def sick(self) -> bool:
        """Whether the child is reported sick, as the portal itself tells it.

        By half days, a child below 7th grade is sick for its first lesson, one from 7th grade
        for both its first and last; otherwise the day's reason is sickness.
        """
        if self.half_days:
            if self.grade is not None and self.grade > 6:
                return self.first_lesson_reason == SICK and self.last_lesson_reason == SICK
            return self.first_lesson_reason == SICK
        return self.day is not None and self.reason == SICK


@dataclass(frozen=True)
class TabulexSchoolDay:
    """Whether a date is a school day for a child."""
    date: datetime.date
    school_day: bool


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def parse_children(answer: Any) -> list[TabulexChild]:
    """The children of `/api/PersonsAdgangTilBoern`'s answer; one without a CPR number or a first name is left out."""
    children: list[TabulexChild] = []
    for item in cast(list[Any], answer) if isinstance(answer, list) else []:
        if not isinstance(item, dict):
            continue
        child = cast(dict[str, Any], item)
        cpr, first = child.get("Cpr"), child.get("Fornavn")
        if not isinstance(cpr, str) or not cpr or not isinstance(first, str):
            continue
        access = child.get("SkoleFravaerAdgang")
        children.append(
            TabulexChild(
                cpr,
                first,
                _text(child.get("Efternavn")) or "",
                None if child.get("SkoleKode") is None else str(child.get("SkoleKode")),
                _text(child.get("SkoleNavn")),
                None if child.get("Klasse") is None else str(child.get("Klasse")),
                access if isinstance(access, bool) else None,
            )
        )
    return children


def parse_day(answer: Any) -> TabulexDay | None:
    """The absence of `/api/Fravaer/Idag/` or `/Imorgen/`'s answer; None where it has none."""
    if not isinstance(answer, dict):
        return None
    day = cast(dict[str, Any], answer)
    grade = day.get("Trin")
    return TabulexDay(
        day.get("Dag"),
        _text(day.get("Aarsag")),
        day.get("HarHalvdagsFravaerSetting") is True,
        grade if isinstance(grade, int) and not isinstance(grade, bool) else None,
        _text(day.get("FoersteLektionAarsag")),
        _text(day.get("SidsteLektionAarsag")),
    )


def parse_school_days(answer: Any) -> list[TabulexSchoolDay]:
    """The days of `/api/Fravaer/skoledage/`'s answer; one without a date it can read is left out."""
    days: list[TabulexSchoolDay] = []
    for item in cast(list[Any], answer) if isinstance(answer, list) else []:
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        text = entry.get("Dato")
        try:
            date = datetime.date.fromisoformat(text[:10]) if isinstance(text, str) else None
        except ValueError:
            date = None
        if date is not None:
            days.append(TabulexSchoolDay(date, entry.get("SkoleDag") is True))
    return days


def _words(text: str) -> str:
    return " ".join(text.casefold().split())


def named(child: AulaChildProfile, children: list[TabulexChild]) -> list[TabulexChild]:
    """The children of `children` of Aula's `child`'s name: its whole name, else its first name.

    Tabulex's first name holds every given name, as "Milas Peter", where Aula's holds the first.
    """
    whole = [found for found in children if _words(f"{found.first_name} {found.last_name}") == _words(child.name)]
    if whole:
        return whole
    return [found for found in children if _words(found.first_name).split(" ")[0] == _words(child.first_name)]


def match(child: AulaChildProfile, children: list[TabulexChild]) -> TabulexChild | None:
    """The child of `children` that is Aula's `child`: the one of its name at the institution Aula has it at.

    Tabulex's school code is Aula's institution code. None where no child, or more than one, is.
    """
    found = [item for item in named(child, children) if item.school_code == child.institution_code]
    return found[0] if len(found) == 1 else None


class _RecordingSession(HttpSession):
    """A session that records each answer, as the Aula client records its own."""

    recorder: Recorder | None = None

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        """Send a request and record its answer, or the error in its place."""
        try:
            response = await super().request(method, url, **kwargs)
        except Exception as error:
            if self.recorder is not None:
                self.recorder.record_error(method, url, None, kwargs.get("json"), error)
            raise
        if self.recorder is not None:
            self.recorder.record(method, url, None, kwargs.get("json"), response)
        return response


class TabulexClient:
    """Tabulex's parent portal on a session of its own, logged in to through Aula's widget."""

    def __init__(self, session: aiohttp.ClientSession, portal: str = PORTAL, recorder: Recorder | None = None) -> None:
        """A client of `portal` on `session`, which holds Tabulex's cookies alone, sent back as they were set.

        Each answer is kept in `recorder`, where one is given.
        """
        self._session = session
        self._portal = portal.rstrip("/")
        self._http = _RecordingSession(session)
        self._http.recorder = recorder
        self._cprs: set[str] = set()

    def secrets(self) -> list[str]:
        """The CPR numbers this client has met, and the portal's XSRF token: to be hidden wherever they are."""
        found = [*self._cprs]
        token = app_headers(self._session, urlsplit(self._portal).hostname or "").get("X-XSRF-TOKEN")
        return [*found, token] if token else found

    async def log_in(self, url: str, fields: Mapping[str, str], not_followed: tuple[str, ...] = NOT_FOLLOWED) -> None:
        """POST Aula's widget's `fields` to its `url`, and follow the login to the portal as a browser does.

        Raises:
            TabulexError: The login did not end at the portal's page.
        """
        ended_at, why = await log_in(self._session, url, dict(fields), not_followed)
        parts, portal = urlsplit(ended_at), urlsplit(self._portal)
        if parts.hostname != portal.hostname or why != "a page a browser stays on":
            raise TabulexError(f"The login to Tabulex ended at {parts.hostname}{parts.path}: {why}")

    def _headers(self) -> dict[str, str]:
        # The portal's own requests are sent so, uncached, with the XSRF token the API wants.
        headers = app_headers(self._session, urlsplit(self._portal).hostname or "")
        return {**headers, "If-Modified-Since": "Mon, 26 Jul 1997 05:00:00 GMT", "Cache-Control": "no-cache", "Pragma": "no-cache"}

    async def _get(self, what: str, path: str) -> Any:
        try:
            response = await self._http.get(f"{self._portal}{path}", headers=self._headers(), allow_redirects=False)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise TabulexError(f"Tabulex could not be reached for {what}: {type(error).__name__}") from None
        if response.status_code != HTTPStatus.OK:
            raise TabulexError(f"Tabulex answered HTTP {response.status_code} for {what}")
        try:
            return response.json()
        except ValueError:
            raise TabulexError(f"Tabulex answered no JSON for {what}") from None

    async def children(self) -> list[TabulexChild]:
        """The children the guardian has access to in Tabulex."""
        children = parse_children(await self._get("the children", "/api/PersonsAdgangTilBoern"))
        self._cprs.update(child.cpr for child in children)
        return children

    async def today(self, child: TabulexChild) -> TabulexDay | None:
        """What Tabulex has of the child's absence today."""
        return parse_day(await self._get("today's absence", f"/api/Fravaer/Idag/{child.cpr}"))

    async def tomorrow(self, child: TabulexChild) -> TabulexDay | None:
        """What Tabulex has of the child's absence tomorrow."""
        return parse_day(await self._get("tomorrow's absence", f"/api/Fravaer/Imorgen/{child.cpr}"))

    async def school_days(self, child: TabulexChild) -> list[TabulexSchoolDay]:
        """Whether each day of the child's week in Tabulex is a school day."""
        return parse_school_days(await self._get("the school days", f"/api/Fravaer/skoledage/{child.cpr}"))

    async def report_sick_today(self, child: TabulexChild) -> None:
        """Report the child sick today, once: never sent again, and it cannot be taken back.

        Raises:
            TabulexError: Tabulex refused it, or could not be reached; where no answer came, it
                may or may not have registered it.
        """
        try:
            response = await self._http.request(
                "PUT", f"{self._portal}/api/Fravaer/MeldSygIdag/", json={"Cpr": child.cpr}, headers=self._headers(), allow_redirects=False
            )
        except (aiohttp.ClientError, TimeoutError) as error:
            raise TabulexError(f"Tabulex gave no answer to the sick report, and may or may not have registered it: {type(error).__name__}") from None
        if response.status_code not in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
            raise TabulexError(f"Tabulex answered HTTP {response.status_code} to the sick report")
        _LOGGER.debug("Tabulex took a sick report")
