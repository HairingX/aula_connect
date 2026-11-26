"""The methods Aula's own web app asks, read from its scripts, against the catalog.

Aula's web app at https://www.aula.dk/portal/ loads its scripts from `/static/js/`, public and
without a login; each asks a method as `<verb>("?method=<name>"`, or names one by `url:"?method=<name>"`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .methods import METHODS

PORTAL = "https://www.aula.dk/portal/"
"""The page of Aula's web app that loads its scripts."""

_SCRIPT = re.compile(r'src="(/static/js/[^"]+\.js)"')
_ASKED = re.compile(r'\.(get|post|put|delete)\(\s*"\?method=([A-Za-z]+\.[A-Za-z]+)')
_NAMED = re.compile(r'"\?method=([A-Za-z]+\.[A-Za-z]+)')


def scripts(page: str) -> list[str]:
    """The paths of the scripts of Aula's web app that `page` loads, in its order."""
    return _SCRIPT.findall(page)


def methods(sources: Iterable[str]) -> dict[str, set[str]]:
    """Each method the scripts ask, by its name as they spell it, with the verbs they ask it with;
    none where they only name it."""
    found: dict[str, set[str]] = {}
    for source in sources:
        for verb, name in _ASKED.findall(source):
            found.setdefault(name, set()).add(verb.upper())
        for name in _NAMED.findall(source):
            found.setdefault(name, set())
    return found


def _admin(name: str) -> bool:
    return name.split(".")[0].lower().endswith("admin")


def differences(found: Mapping[str, set[str]]) -> list[str]:
    """What the catalog says otherwise than Aula's web app, a line each: a name spelt otherwise, a
    verb otherwise, a method the web app does not ask, and one it asks that the catalog lacks, but
    for an administrator's."""
    lower = {name.lower(): name for name in found}
    lines: list[str] = []
    for name, method in METHODS.items():
        spelt = lower.get(name.lower())
        if spelt is None:
            lines.append(f"not in the web app: {name}")
        elif spelt != name:
            lines.append(f"spelt otherwise: {name} is {spelt} in the web app")
        elif found[spelt] and method.verb not in found[spelt]:
            lines.append(f"asked otherwise: {name} with {method.verb}, the web app with {'/'.join(sorted(found[spelt]))}")
    known = {name.lower() for name in METHODS}
    for name in sorted(found, key=str.lower):
        if name.lower() not in known and not _admin(name):
            lines.append(f"not in the catalog: {name} {'/'.join(sorted(found[name])) or '?'}")
    return lines
