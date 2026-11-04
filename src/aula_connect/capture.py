"""The newest answers Aula gave, kept in memory to show what Aula sends."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from yarl import URL

from .http import HttpResponse

MAX_EXCHANGES = 200
"""How many requests a recorder keeps the answer to."""


@dataclass(frozen=True)
class Exchange:
    """A request to Aula and its answer, as sent and read but for the access token."""

    method: str
    url: str
    request: Any
    """The JSON the request sent; None without one."""
    status: int
    response: Any
    """The answer as JSON, or as text where it is none."""

    @property
    def endpoint(self) -> str:
        """What was asked for: the Aula API method, or the path of a widget's request."""
        parts = urlsplit(self.url)
        method = dict(parse_qsl(parts.query)).get("method")
        return method or parts.path


class Recorder:
    """The newest answer to each request, the oldest request forgotten first beyond `limit`.

    A request for a token is never kept, nor are the headers of any.
    """

    def __init__(self, limit: int = MAX_EXCHANGES) -> None:
        self.limit = limit
        self._exchanges: OrderedDict[str, Exchange] = OrderedDict()

    def record(
        self, method: str, url: str, params: Mapping[str, str] | None, request: Any, response: HttpResponse
    ) -> None:
        """Keep `response` as the answer to the request, in place of an earlier one to the same."""
        if params is not None:
            url = str(URL(url, encoded=True).update_query(params))
        exchange = Exchange(method, url, request, response.status_code, _body(response))
        if "token" in exchange.endpoint.lower():
            return
        key = f"{method} {url}"
        self._exchanges.pop(key, None)
        self._exchanges[key] = exchange
        while len(self._exchanges) > self.limit:
            self._exchanges.popitem(last=False)

    def exchanges(self) -> list[Exchange]:
        """The requests kept and their answers, the oldest first."""
        return list(self._exchanges.values())

    def clear(self) -> None:
        """Forget every answer kept."""
        self._exchanges.clear()


def _body(response: HttpResponse) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
