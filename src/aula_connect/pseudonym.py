"""Aula's answers with all they say replaced, but how they are built: each value always by the
same other value of its length, so that what belongs together still does, and the text still
fills as much.

Every word of every text is replaced by a made-up word as long, with capitals where it has them;
the same word always by the same one. Ids and contact details, found by their keys or their form,
are replaced by others of their kinds of characters, inside every text too, and so is the site of
a link but for Aula's and its widgets'. Secrets and tokens become as many "x".
What tells how an answer is built is kept: the keys, the values of a kind such as a message's
type or a notification's area, names in code such as "NewMessagePrivateInbox", HTML's tags,
dates and times, and numbers that are no ids.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable, Collection, Iterable
from typing import Any, cast
from urllib.parse import unquote

from .capture import Exchange

_CONSONANTS = "bdfghjklmnprstv"
_VOWELS = "aeiouy"

_SECRET = re.compile(r"token|password|secret|csrf|cookie|signature|authorization|apikey|jwt|bearer", re.IGNORECASE)
# A token Aula or a widget gives, wherever it stands: a JSON web token, or one sent as a bearer.
_TOKEN = r"eyJ[\w-]+\.[\w-]+\.[\w-]*|(?i:bearer)\s+[\w.~+/=-]+"
_ID_KEYS = {"id", "ids", "institutioncode", "unilogin", "userid", "key", "bucket"}
# Keys whose values are of a kind Aula names, never who someone is or what they wrote.
_KIND_KEYS = ("type", "status", "role", "mode", "area", "module", "method", "scope", "placement", "supplier", "version")
_KIND_NAMES = {"icon", "iconemployee", "iconhover", "pluginname"}
# A value that is a name in code: "NewMessagePrivateInbox", "presence.getDailyOverview", "ADMIN_ROLE".
_CODE = re.compile(r"[a-z]+(?:[A-Z][a-z0-9]{2,})+|(?:[A-Z][a-z0-9]{2,}){2,}|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[a-z]+\.[a-z]+[A-Za-z]*")
# The sites of Aula, of its widgets, and the names reserved for examples, kept in a link.
_KEPT_SITES = re.compile(
    r"(?:.+\.)?(?:aula\.dk|minuddannelse\.net|meebook\.com|systematic-momo\.dk|easyiqcloud\.dk"
    r"|example\.(?:com|org|net)|[^.]+\.(?:example|invalid|test))",
    re.IGNORECASE,
)
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
    # A widget is asked for its children and institutions by their ids, as a filter; an
    # institution and a municipality are named by a code.
    return key.lower() in _ID_KEYS or key.endswith(("Id", "Ids", "ID", "_id", "Filter", "Code", "Codes"))


def _is_kind_key(key: str) -> bool:
    lower = key.lower()
    return lower.endswith(_KIND_KEYS) or lower in _KIND_NAMES


def _hidden(value: str) -> str:
    return "x" * len(value)


def hidden(value: Any) -> Any:
    """`value` with every text as many "x" and every digit a 9, each in its place."""
    if isinstance(value, dict):
        return {name: hidden(item) for name, item in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [hidden(item) for item in cast(list[Any], value)]
    if isinstance(value, str):
        return _hidden(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return int(re.sub(r"\d", "9", str(value)))
    return value


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

    def __init__(self, key: bytes, secrets: Iterable[str] = (), reveal: bool | Collection[str] = False) -> None:
        """Replace with `key`, and every one of `secrets` anywhere by as many "x".

        `reveal` keeps the values under the keys it names as they are, or every value where it is
        True; a secret and a token are hidden all the same.
        """
        self._key = key
        self._reveal_all = reveal is True
        self._revealed = frozenset(reveal) if not isinstance(reveal, bool) else frozenset[str]()
        self._secrets = [secret for secret in secrets if secret]
        self._ids: dict[str, str] = {}
        self._known_ids: set[str] = set()
        self._taken: set[str] = set()
        self._words: dict[str, str] = {}
        self._contacts: dict[str, str] = {}
        self._in_text: dict[str, Callable[[str], str]] = {}
        self._pattern: re.Pattern[str] | None = None
        for secret in secrets:
            if secret:
                self._in_text[secret] = _hidden

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
        # Words as a text has them, letters only, so that "2A" in a name is replaced as in a text.
        return re.sub(r"[^\W\d_]+", lambda match: self._word(match.group()), value)

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

    def text(self, value: str, words: bool = True) -> str:
        """A text with every word, and the ids, contact details and links learnt or found in it,
        replaced; HTML's tags, and a date or a time alone, are kept.

        Without `words`, the words are kept, for a text of the library's or of HTTP's own, such as
        an error or an API's path, which says nothing of anyone but by the ids in it.
        """
        if _DATE.fullmatch(value):
            return value
        if self._pattern is None:
            known = "|".join(re.escape(text) for text in sorted(self._in_text, key=len, reverse=True))
            alternatives = [f"(?P<token>{_TOKEN})", f"(?P<link>{_LINK})", r"(?P<tag><[^<>]*>)", r"(?P<entity>&#?\w+;)"]
            alternatives += [f"(?P<known>(?<!\\w)(?:{known})(?!\\w))"] if known else []
            alternatives += [f"(?P<email>{_EMAIL})", f"(?P<cpr>{_CPR})", f"(?P<phone>{_PHONE})", r"(?P<word>[^\W\d_]+)"]
            self._pattern = re.compile("|".join(alternatives))

        def replace(match: re.Match[str]) -> str:
            text = match.group()
            match match.lastgroup:
                case "token":
                    return _hidden(text)
                case "link":
                    return self.url(text)
                case "tag":
                    return self._tag(text)
                case "entity":
                    return text
                case "known":
                    return self._in_text[text](text)
                case "word":
                    return self._word(text) if words else text
                case _:
                    return self._contact(text)

        return self._pattern.sub(replace, value)

    def _tag(self, tag: str) -> str:
        """An HTML tag with the text of its attributes replaced, but for its style and class."""

        def attribute(match: re.Match[str]) -> str:
            name, quote, text = match.group(1), match.group(2), match.group(3)
            kept = name.lower() in ("style", "class")
            return f"{name}={quote}{text if kept else self.text(text)}{quote}"

        return re.sub(r"([\w-]+)=([\"'])(.*?)\2", attribute, tag)

    def _site(self, site: str) -> str:
        """The site of a link with each part of its host but the last replaced, unless it is Aula's,
        a widget's, or one reserved for examples."""
        parts = re.fullmatch(r"(?P<scheme>[a-z]+://)(?P<host>[^/:]*)(?P<port>:\d+)?", site, re.IGNORECASE)
        if parts is None or _KEPT_SITES.fullmatch(parts.group("host")):
            return site
        *labels, last = parts.group("host").split(".")
        host = ".".join([*(self._word(label) for label in labels), last])
        return f"{parts.group('scheme')}{host}{parts.group('port') or ''}"

    def url(self, value: str, request: bool = False) -> str:
        """A link with its site, unless it is Aula's or a widget's, and the words, ids and contact
        details of its path replaced, each in its place.

        The path and the values of a request's query are kept but for their ids; every value of
        another link's query is replaced, as it can sign the link.
        """
        parts = _LINK_PARTS.fullmatch(value)
        assert parts is not None

        def param(match: re.Match[str]) -> str:
            name, item = match.group(1), match.group(3)
            plain = unquote(name).removesuffix("[]")
            if _SECRET.search(plain):
                item = _hidden(item)
            elif request and _is_id_key(plain):
                item = self._id(item)
            elif request:
                item = self.text(item, words=False)
            else:
                item = self._shaped("query", item)
            return f"{name}{match.group(2)}{item}"

        query = re.sub(r"([^&=]+)(=?)([^&]*)", param, parts.group("query") or "")
        site = self._site(parts.group("site"))
        path = re.sub(r"[^/]+", lambda segment: self.text(segment.group(), not request), parts.group("path"))
        return f"{site}{path}{query}{parts.group('rest') or ''}"

    def value(self, value: Any, key: str = "", words: bool = True) -> Any:
        """`value`, found under `key`, with what tells who someone is replaced.

        Without `words`, the words of a text that is no name are kept, for what the library itself
        sends, such as a request's body.
        """
        if self._reveal_all or key in self._revealed:
            return self._bare(value, key)
        if key == "status" or (_is_kind_key(key) and isinstance(value, str)):
            return value
        if isinstance(value, dict):
            mapping = cast(dict[object, Any], value)
            return {self._dict_key(str(name)): self.value(item, str(name), words) for name, item in mapping.items()}
        if isinstance(value, list):
            return [self.value(item, key, words) for item in cast(list[Any], value)]
        if isinstance(value, bool) or not isinstance(value, str | int):
            return value
        if _SECRET.search(key):
            return hidden(value)
        if isinstance(value, int):
            text = str(value)
            known = len(text) >= _MIN_ID_ELSEWHERE and text in self._known_ids
            return int(self._id(text)) if _is_id_key(key) or known else value
        if _is_id_key(key):
            return self._id(value)
        if _CODE.fullmatch(value):
            return value
        if _is_name_key(key):
            return self._name(value)
        if _CONTACT.search(key):
            return self._contact(value) if value.strip() else value
        if _URL.match(value):
            return self.url(value)
        return self.text(value, words)

    def _bare(self, value: Any, key: str) -> Any:
        """`value` as it is, but for its secrets and tokens, as many "x"."""
        if _SECRET.search(key):
            return hidden(value)
        if isinstance(value, dict):
            return {name: self._bare(item, str(name)) for name, item in cast(dict[object, Any], value).items()}
        if isinstance(value, list):
            return [self._bare(item, key) for item in cast(list[Any], value)]
        if isinstance(value, str):
            secrets = "|".join(re.escape(secret) for secret in sorted(self._secrets, key=len, reverse=True))
            pattern = f"{_TOKEN}|{secrets}" if secrets else _TOKEN
            return re.sub(pattern, lambda match: _hidden(match.group()), value)
        return value

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


def pseudonymised(
    exchanges: Iterable[Exchange], key: bytes, secrets: Iterable[str] = (), reveal: bool | Collection[str] = False
) -> list[dict[str, Any]]:
    """The exchanges, each with what tells who someone is replaced, one key making the same, and
    each of `secrets` hidden wherever it is. What a request for a token answers is hidden whole.

    `reveal` keeps what the request sent and Aula answered under the keys it names, or all of it
    where it is True, as it is but for its secrets and tokens.
    """
    kept = list(exchanges)
    pseudonymiser = Pseudonymiser(key, secrets, reveal)
    for exchange in kept:
        pseudonymiser.learn(exchange.request)
        pseudonymiser.learn(exchange.response)
    return [
        {
            "at": exchange.at.isoformat(),
            "endpoint": pseudonymiser.text(exchange.endpoint, words=False),
            "method": exchange.method,
            "url": pseudonymiser.url(exchange.url, request=True),
            "request": pseudonymiser.value(exchange.request, words=False),
            "status": exchange.status,
            "headers": {
                name: hidden(text) if _SECRET.search(name) else pseudonymiser.text(text, words=False)
                for name, text in exchange.headers.items()
            },
            "error": None if exchange.error is None else pseudonymiser.text(exchange.error, words=False),
            "response": _answer(pseudonymiser, exchange),
        }
        for exchange in kept
    ]


def _answer(pseudonymiser: Pseudonymiser, exchange: Exchange) -> Any:
    answer: Any = pseudonymiser.value(exchange.response)
    fields = _fields(answer)
    if "token" in exchange.endpoint.lower() and fields is not None and "data" in fields:
        return {**fields, "data": hidden(fields["data"])}
    return answer


def _fields(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None
