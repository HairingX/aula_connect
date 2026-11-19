"""The shape of each of Aula's answers as Aula was seen to send it: the type at each place.

A shape holds the names Aula gives its fields and the type of each, never a value. It is kept as
a reference, so that an answer Aula sends otherwise is told apart from the one known.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from importlib.resources import files
from typing import Any, cast

from .pseudonym import shapes

Shape = Mapping[str, list[str]]
"""The types at each place of an answer, by the place, such as "data[].id"."""

KNOWN: Mapping[str, Shape] = json.loads(files(__package__).joinpath("shapes.json").read_text(encoding="utf-8"))
"""The shape of each answer seen, by its request: the verb and what was asked for, such as
"GET calendar.getEventById" or "GET /aulaapi/relatedweekplan/all"."""


def unknown(request: str, answer: Any) -> list[str]:
    """The places in `answer` to `request` that tell its shape changed, each with its type.

    A place tells it where it is a field the known shape lacks in an object it knows, or where it
    has a type other than null the known shape does not give it, though it gives it another. What
    lies under a place the known shape saw only as null is not known, and tells nothing. A request
    with no known shape has none.
    """
    known = KNOWN.get(request)
    if known is None:
        return []
    found: list[str] = []
    for at, types in shapes(answer).items():
        if at in known:
            seen = set(known[at]) - {"null"}
            found.extend(f"{at} ({kind})" for kind in types if seen and kind not in seen and kind != "null")
        elif not at.endswith("[]") and "object" in known.get(_parent(at), ()):
            found.extend(f"{at} ({kind})" for kind in types)
    return found


def _parent(at: str) -> str:
    """The object that holds the field `at`: "data" holds "data.id", and "data[]" holds "data[].id"."""
    head, dot, _ = at.rpartition(".")
    return head if dot else "."


def merged(reference: Mapping[str, Shape], answers: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """`reference` with the shape of each of `answers` added, as `responses` lists them.

    Only an answer of status 200 is added, by its method and endpoint.
    """
    result = {request: {at: set(types) for at, types in shape.items()} for request, shape in reference.items()}
    for answer in answers:
        if answer.get("status") != 200:
            continue
        shape = result.setdefault(f"{answer['method']} {answer['endpoint']}", {})
        for at, types in shapes(answer.get("response")).items():
            shape.setdefault(at, set()).update(types)
    return {request: {at: sorted(types) for at, types in sorted(shape.items())} for request, shape in sorted(result.items())}


def main(paths: list[str], reference: str) -> None:
    """Add the answers in the diagnostics at `paths` to the reference file at `reference`."""
    answers: list[Mapping[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as file:
            diagnostics = cast(dict[str, Any], json.load(file))
        answers.extend(diagnostics["data"]["aula"]["exchanges"])
    with open(reference, encoding="utf-8") as file:
        known = cast(dict[str, Shape], json.load(file))
    with open(reference, "w", encoding="utf-8") as file:
        json.dump(merged(known, answers), file, indent=1, sort_keys=True)
        file.write("\n")
