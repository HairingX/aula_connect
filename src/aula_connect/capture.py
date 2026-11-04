"""The newest answers Aula gave, and the newest failures, kept in memory to show what Aula sends."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from yarl import URL

from .http import HttpResponse
from .redact import redact

MAX_EXCHANGES = 200
"""How many requests a recorder keeps the newest answer to."""

MAX_FAILURES = 50
"""How many requests a recorder keeps the newest failure of, besides."""


@dataclass(frozen=True)
class Exchange:
    """A request to Aula and its answer, or the error that came in its place, as sent and read
    but for the access token and the request's headers."""

    method: str
    url: str
    request: Any
    """The JSON the request sent; None without one."""
    status: int
    """The answer's status; 0 where no answer came."""
    response: Any
    """The answer as JSON, or as text where it is none."""
    at: datetime
    """When the answer, or the error, came."""
    headers: dict[str, str] = field(default_factory=lambda: {})
    """The answer's headers, those of one name joined by ", "."""
    error: str | None = None
    """What went wrong where no answer came, with every secret in it redacted."""

    @property
    def endpoint(self) -> str:
        """What was asked for: the Aula API method, or the path of a widget's request."""
        parts = urlsplit(self.url)
        method = dict(parse_qsl(parts.query)).get("method")
        return method or parts.path

    @property
    def failed(self) -> bool:
        """Whether no answer came, or one with an error's status."""
        return self.error is not None or self.status >= 400


class Recorder:
    """The newest answer to each request, and the newest failure of each that failed, the
    oldest forgotten first beyond `limit` and `failures`; a failure stays when a later answer
    to the same request succeeds."""

    def __init__(self, limit: int = MAX_EXCHANGES, failures: int = MAX_FAILURES) -> None:
        self.limit = limit
        self.failures = failures
        self._latest: OrderedDict[str, Exchange] = OrderedDict()
        self._failed: OrderedDict[str, Exchange] = OrderedDict()

    def record(
        self, method: str, url: str, params: Mapping[str, str] | None, request: Any, response: HttpResponse
    ) -> None:
        """Keep `response` as the newest answer to the request."""
        headers: dict[str, str] = {}
        for name, value in response.headers.items():
            headers[name] = f"{headers[name]}, {value}" if name in headers else value
        self._keep(
            Exchange(method, _url(url, params), request, response.status_code, _body(response), _now(), headers)
        )

    def record_error(
        self, method: str, url: str, params: Mapping[str, str] | None, request: Any, error: BaseException
    ) -> None:
        """Keep `error` as what came in place of an answer to the request."""
        text = f"{type(error).__name__}: {redact(error)}"
        self._keep(Exchange(method, _url(url, params), request, 0, None, _now(), error=text))

    def _keep(self, exchange: Exchange) -> None:
        key = f"{exchange.method} {exchange.url}"
        for kept, limit, keep in ((self._latest, self.limit, True), (self._failed, self.failures, exchange.failed)):
            if keep:
                kept.pop(key, None)
                kept[key] = exchange
                while len(kept) > limit:
                    kept.popitem(last=False)

    def exchanges(self) -> list[Exchange]:
        """The answers and failures kept, the oldest first."""
        latest = list(self._latest.values())
        failed = [exchange for exchange in self._failed.values() if exchange not in latest]
        return sorted(latest + failed, key=lambda exchange: exchange.at)

    def clear(self) -> None:
        """Forget every answer and failure kept."""
        self._latest.clear()
        self._failed.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _url(url: str, params: Mapping[str, str] | None) -> str:
    return url if params is None else str(URL(url, encoded=True).update_query(params))


def _body(response: HttpResponse) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
