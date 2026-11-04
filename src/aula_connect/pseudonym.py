"""Aula's answers with what tells who someone is replaced: each value always by the same other
value of its length, so that what belongs together still does, and the text still fills as much.

Ids, names, contact details and links are found by the keys Aula gives them under; a name, an
id or a contact detail found so is replaced inside every text too. Secrets become as many "x".
A token, whatever key it is under or text it is in, becomes as many "x" too.
Dates and times, numbers that are no ids, and the rest of a text are kept as they are: a name
the answers give under no key of a name, such as another child's in a message, stays.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable, Iterable
from typing import Any, cast
from urllib.parse import unquote

from .capture import Exchange

_CONSONANTS = "bdfghjklmnprstv"
_VOWELS = "aeiouy"

_SECRET = re.compile(r"token|password|secret|csrf|cookie|signature|authorization|apikey|jwt|bearer", re.IGNORECASE)
# A token Aula or a widget gives, wherever it stands: a JSON web token, or one sent as a bearer.
_TOKEN = r"eyJ[\w-]+\.[\w-]+\.[\w-]*|(?i:bearer)\s+[\w.~+/=-]+"
_ID_KEYS = {"id", "ids", "institutioncode", "unilogin", "userid", "key", "bucket"}
# Keys whose text is who someone is, besides those ending in "name": the one who fetches a child,
# the author of a task, the institution a notification is from.
_NAME_KEYS = {
    "alias",
    "author",
    "creator",
    "exitwith",
    "group",
    "initials",
    "institution",
    "relatedinstitution",
    "sender",
    "teacherinitials",
}
_CONTACT = re.compile(r"e?mail|phone|mobil|telefon|address|adresse|street|zip|postal|cpr", re.IGNORECASE)

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_URL = re.compile(r"https?://", re.IGNORECASE)
_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
_CPR = r"(?<!\d)\d{6}-\d{4}(?!\d)"
_PHONE = r"(?<![\d+])(?:\+45 ?)?\d{2} ?\d{2} ?\d{2} ?\d{2}(?!\d)"
_LINK = r"https?://[^\s\"'<>]+"
_LINK_PARTS = re.compile(r"(?P<site>(?:[a-z]+://[^/?#]*)?)(?P<path>[^?#]*)(?P<query>\?[^#]*)?(?P<rest>#.*)?", re.IGNORECASE | re.DOTALL)
_ATTEMPTS = 100
_MIN_ID_IN_TEXT = 5
"""The shortest id replaced inside a text: a shorter one could be a year, a page or a room."""
_MIN_ID_ELSEWHERE = 4
"""The shortest id replaced as a number under a key of no id, such as a list of profiles: a
shorter one could be a count or a status."""


def _is_id_key(key: str) -> bool:
    # A widget is asked for its children and institutions by their ids, as a filter.
    return key.lower() in _ID_KEYS or key.endswith(("Id", "Ids", "ID", "_id", "Filter"))


def _letter(index: int, byte: int) -> str:
    # Consonants and vowels in turn, so that a made-up name can be read as one.
    pool = _CONSONANTS if index % 2 == 0 else _VOWELS
    return pool[byte % len(pool)]


def _is_name_key(key: str) -> bool:
    lower = key.lower()
    return lower.endswith(("name", "navn")) or lower in _NAME_KEYS


class Pseudonymiser:
    """Replaces what tells who someone is, keyed by `key`: one key gives the same replacements.

    `learn` everything first, then replace it: a name learnt from one answer is replaced in all.
    """

    def __init__(self, key: bytes) -> None:
        self._key = key
        self._ids: dict[str, str] = {}
        self._known_ids: set[str] = set()
        self._taken: set[str] = set()
        self._words: dict[str, str] = {}
        self._contacts: dict[str, str] = {}
        self._in_text: dict[str, Callable[[str], str]] = {}
        self._pattern: re.Pattern[str] | None = None

    def _stream(self, kind: str, value: str, size: int, attempt: int = 0) -> bytes:
        stream = b""
        block = 0
        while len(stream) < size:
            message = f"{kind}\0{attempt}\0{block}\0{value}".encode()
            stream += hmac.new(self._key, message, hashlib.sha256).digest()
            block += 1
        return stream

    def _shaped(self, kind: str, value: str, attempt: int = 0) -> str:
        """`value` with each digit and letter replaced by another of its kind, the rest kept."""
        stream = self._stream(kind, value, len(value), attempt)
        out: list[str] = []
        for index, char in enumerate(value):
            byte = stream[index]
            if char.isdigit():
                leading = index == 0 and char != "0" and len(value) > 1
                out.append("123456789"[byte % 9] if leading else "0123456789"[byte % 10])
            elif char.isalpha():
                letter = "abcdefghijklmnopqrstuvwxyz"[byte % 26]
                out.append(letter.upper() if char.isupper() else letter)
            else:
                out.append(char)
        return "".join(out)

    def _word(self, word: str) -> str:
        """A made-up word for a word of a name, as long, with capitals where it has them."""
        known = self._words.get(word)
        if known is None:
            stream = self._stream("word", word, len(word))
            letters = [_letter(index, byte) for index, byte in enumerate(stream[: len(word)])]
            known = "".join(
                (letter.upper() if char.isupper() else letter) if char.isalpha() else char
                for letter, char in zip(letters, word)
            )
            self._words[word] = known
        return known

    def _id(self, value: str) -> str:
        known = self._ids.get(value)
        if known is None:
            known = self._shaped("id", value)
            # Ids as short as one digit run out of others: past the attempts, two may share one.
            for attempt in range(1, _ATTEMPTS):
                if known not in self._taken and (known != value or not any(c.isalnum() for c in value)):
                    break
                known = self._shaped("id", value, attempt)
            self._taken.add(known)
            self._ids[value] = known
        return known

    def _contact(self, value: str) -> str:
        known = self._contacts.get(value)
        if known is None:
            known = self._shaped("contact", value)
            self._contacts[value] = known
        return known

    def _name(self, value: str) -> str:
        return re.sub(r"\w+", lambda match: self._word(match.group()), value)

    def learn(self, value: Any, key: str = "") -> None:
        """Take note of the ids, names and contact details in `value`, found under `key`."""
        self._pattern = None
        if isinstance(value, dict):
            for name, item in cast(dict[object, Any], value).items():
                self.learn(item, str(name))
        elif isinstance(value, list):
            for item in cast(list[Any], value):
                self.learn(item, key)
        elif isinstance(value, str | int) and not isinstance(value, bool) and not _SECRET.search(key):
            text = str(value)
            if _is_id_key(key):
                self._known_ids.add(text)
                if len(text) >= _MIN_ID_IN_TEXT:
                    self._in_text[text] = self._id
            elif _is_name_key(key) and isinstance(value, str):
                for word in re.findall(r"\w+", value):
                    if len(word) >= 2 and word[0].isupper():
                        self._in_text[word] = self._word
            elif _CONTACT.search(key) and isinstance(value, str) and value.strip():
                self._in_text[value] = self._contact

    def text(self, value: str) -> str:
        """A text with the ids, names, contact details and links learnt, and any contact detail or
        link it holds, replaced; a date or a time alone is kept."""
        if _DATE.fullmatch(value):
            return value
        if self._pattern is None:
            known = "|".join(re.escape(text) for text in sorted(self._in_text, key=len, reverse=True))
            alternatives = [f"(?P<token>{_TOKEN})", f"(?P<link>{_LINK})"]
            alternatives += [f"(?P<known>(?<!\\w)(?:{known})(?!\\w))"] if known else []
            alternatives += [f"(?P<email>{_EMAIL})", f"(?P<cpr>{_CPR})", f"(?P<phone>{_PHONE})"]
            self._pattern = re.compile("|".join(alternatives))

        def replace(match: re.Match[str]) -> str:
            text = match.group()
            if match.lastgroup == "token":
                return "x" * len(text)
            if match.lastgroup == "link":
                return self.url(text)
            if match.lastgroup == "known":
                return self._in_text[text](text)
            return self._contact(text)

        return self._pattern.sub(replace, value)

    def url(self, value: str, request: bool = False) -> str:
        """A link with the ids, names and contact details in its path replaced, each in its place.

        The values of a request's query are kept but for its ids; every value of another link's
        query is replaced, as it can sign the link.
        """
        parts = _LINK_PARTS.fullmatch(value)
        assert parts is not None

        def param(match: re.Match[str]) -> str:
            name, item = match.group(1), match.group(3)
            plain = unquote(name).removesuffix("[]")
            if _SECRET.search(plain):
                item = "x" * len(item)
            elif request and _is_id_key(plain):
                item = self._id(item)
            elif request:
                item = self.text(item)
            else:
                item = self._shaped("query", item)
            return f"{name}{match.group(2)}{item}"

        query = re.sub(r"([^&=]+)(=?)([^&]*)", param, parts.group("query") or "")
        return f"{parts.group('site')}{self.text(parts.group('path'))}{query}{parts.group('rest') or ''}"

    def value(self, value: Any, key: str = "") -> Any:
        """`value`, found under `key`, with what tells who someone is replaced."""
        if isinstance(value, dict):
            mapping = cast(dict[object, Any], value)
            return {self._dict_key(str(name)): self.value(item, str(name)) for name, item in mapping.items()}
        if isinstance(value, list):
            return [self.value(item, key) for item in cast(list[Any], value)]
        if isinstance(value, bool) or not isinstance(value, str | int):
            return value
        if isinstance(value, int):
            text = str(value)
            if _SECRET.search(key):
                return int(re.sub(r"\d", "9", text))
            known = len(text) >= _MIN_ID_ELSEWHERE and text in self._known_ids
            return int(self._id(text)) if _is_id_key(key) or known else value
        if _SECRET.search(key):
            return "x" * len(value)
        if _is_id_key(key):
            return self._id(value)
        if _is_name_key(key):
            return self._name(value)
        if _CONTACT.search(key):
            return self._contact(value) if value.strip() else value
        if _URL.match(value):
            return self.url(value)
        return self.text(value)

    def _dict_key(self, name: str) -> str:
        return self._id(name) if name.isdigit() else name


def shapes(value: Any, path: str = "") -> dict[str, list[str]]:
    """The type of what is at each place in `value`: "data[].id" is an int, for one."""
    found: dict[str, set[str]] = {}

    def walk(item: Any, at: str) -> None:
        if isinstance(item, dict):
            found.setdefault(at or ".", set()).add("object")
            for name, inner in cast(dict[object, Any], item).items():
                walk(inner, f"{at}.{name}" if at else str(name))
        elif isinstance(item, list):
            found.setdefault(at or ".", set()).add("list")
            for inner in cast(list[Any], item):
                walk(inner, f"{at}[]")
        else:
            found.setdefault(at or ".", set()).add("null" if item is None else type(item).__name__)

    walk(value, path)
    return {at: sorted(kinds) for at, kinds in sorted(found.items())}


def pseudonymised(exchanges: Iterable[Exchange], key: bytes) -> list[dict[str, Any]]:
    """The exchanges, each with what tells who someone is replaced, one key making the same."""
    kept = list(exchanges)
    pseudonymiser = Pseudonymiser(key)
    for exchange in kept:
        pseudonymiser.learn(exchange.request)
        pseudonymiser.learn(exchange.response)
    return [
        {
            "endpoint": pseudonymiser.text(exchange.endpoint),
            "method": exchange.method,
            "url": pseudonymiser.url(exchange.url, request=True),
            "request": pseudonymiser.value(exchange.request),
            "status": exchange.status,
            "response": pseudonymiser.value(exchange.response),
        }
        for exchange in kept
    ]
