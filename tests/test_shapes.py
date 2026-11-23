"""The known shape of Aula's answers, and what tells an answer's shape changed."""

import json
from pathlib import Path
from typing import Any

import pytest

from aula_connect.shapes import KNOWN, main, merged, unknown

EVENT = "GET calendar.getEventById"


def _event(**data: Any) -> dict[str, Any]:
    return {"status": {"code": 0, "message": "OK"}, "data": {"id": 1, "title": "Meeting", **data}}


def test_an_answer_in_the_known_shape_tells_nothing() -> None:
    assert unknown(EVENT, _event(lesson=None, description={"html": "<p>x</p>"})) == []


def test_a_field_new_to_an_object_known_is_told_with_its_type() -> None:
    assert unknown(EVENT, _event(newField="x")) == ["data.newField (str)"]
    assert unknown(EVENT, {"newTop": 1}) == ["newTop (int)"]


def test_a_type_other_than_the_one_known_is_told_but_not_null() -> None:
    assert unknown(EVENT, _event(id="1")) == ["data.id (str)"]
    assert unknown(EVENT, _event(title=None)) == []


def test_what_lies_under_a_place_seen_only_as_null_tells_nothing() -> None:
    assert unknown(EVENT, _event(lesson={"lessonId": "x"})) == []


def test_a_request_with_no_known_shape_tells_nothing() -> None:
    assert unknown("GET calendar.getNothing", {"anything": 1}) == []


def test_the_answers_of_diagnostics_are_added_to_a_reference_but_a_failure() -> None:
    answers = [
        {"method": "GET", "endpoint": "calendar.getNothing", "status": 200, "response": {"data": [1]}},
        {"method": "GET", "endpoint": "calendar.getNothing", "status": 200, "response": {"data": [None]}},
        {"method": "GET", "endpoint": "calendar.getFailure", "status": 404, "response": {"status": {"code": 10}}},
    ]
    assert merged({"GET x.getY": {".": ["object"]}}, answers) == {
        "GET calendar.getNothing": {".": ["object"], "data": ["list"], "data[]": ["int", "null"]},
        "GET x.getY": {".": ["object"]},
    }


def test_the_reference_file_takes_the_answers_of_diagnostics_files(tmp_path: Path) -> None:
    reference = tmp_path / "shapes.json"
    reference.write_text(json.dumps({"GET x.getY": {".": ["object"]}}), encoding="utf-8")
    diagnostics = tmp_path / "diagnostics.json"
    exchange = {"method": "GET", "endpoint": "x.getZ", "status": 200, "response": {"id": 1}}
    diagnostics.write_text(json.dumps({"data": {"aula": {"exchanges": [exchange]}}}), encoding="utf-8")
    main([str(diagnostics)], str(reference))
    assert json.loads(reference.read_text(encoding="utf-8")) == {
        "GET x.getY": {".": ["object"]},
        "GET x.getZ": {".": ["object"], "id": ["int"]},
    }
    assert reference.read_text(encoding="utf-8").endswith("}\n")


@pytest.mark.parametrize("request_", sorted(KNOWN))
def test_the_known_shapes_name_fields_and_types_and_never_a_value(request_: str) -> None:
    for at, types in KNOWN[request_].items():
        assert at == "." or all(part.isidentifier() for part in at.replace("[]", ".").split(".") if part), at
        assert set(types) <= {"object", "list", "str", "int", "float", "bool", "null"}, (at, types)


def test_a_notification_of_a_post_is_a_known_shape() -> None:
    post = {"postId": 1, "postTitle": "Juleklip", "groupId": None, "groupName": None}
    assert unknown("GET notifications.getNotificationsForActiveProfile", {"data": [post]}) == []
