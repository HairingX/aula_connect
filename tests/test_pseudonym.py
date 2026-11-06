"""Tests of replacing what tells who someone is in Aula's answers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from aula_connect.capture import Exchange
from aula_connect.pseudonym import Pseudonymiser, pseudonymised, shapes

KEY = b"a key for the tests"
AT = datetime(2026, 12, 28, 8, tzinfo=timezone.utc)


def _replaced(value: object, key: str = "") -> Any:
    pseudonymiser = Pseudonymiser(KEY)
    pseudonymiser.learn(value, key)
    return pseudonymiser.value(value, key)


def test_a_secret_becomes_as_many_x_or_nines_and_is_never_learnt() -> None:
    replaced: dict[str, Any] = _replaced({"access_token": "abc123", "csrfpToken": "q", "pinPassword": 4821, "note": "abc123"})
    assert {key: value for key, value in replaced.items() if key != "note"} == {"access_token": "xxxxxx", "csrfpToken": "x", "pinPassword": 9999}
    assert replaced["note"] != "xxxxxx" and re.fullmatch(r"[a-z]{3}123", replaced["note"])


def test_an_id_keeps_its_length_type_and_kinds_of_characters() -> None:
    replaced: dict[str, Any] = _replaced({"id": 3301846, "userId": "alma-9921", "childIds": [12, 7], "code": 448})
    assert len(str(replaced["id"])) == 7 and replaced["id"] != 3301846
    user: str = replaced["userId"]
    assert user != "alma-9921"
    assert user[4] == "-" and user[:4].isalpha() and user[5:].isdigit()
    assert [len(str(child)) for child in replaced["childIds"]] == [2, 1]
    assert replaced["code"] == 448


def test_one_digit_ids_beyond_the_others_left_still_get_one() -> None:
    replaced: dict[str, Any] = _replaced({"ids": list(range(10)) + [10]})
    assert sorted(len(str(item)) for item in replaced["ids"]) == [1] * 10 + [2]


def test_a_name_keeps_the_length_and_capitals_of_each_word() -> None:
    replaced: dict[str, Any] = _replaced({"fullName": "Alma Marie Østergaard-Holm", "teacherInitials": "BH"})
    name: str = replaced["fullName"]
    assert [len(word) for word in name.replace("-", " ").split()] == [4, 5, 10, 4]
    assert name[0].isupper() and name[1:4].islower() and name[21] == "-"
    assert "Alma" not in name and len(replaced["teacherInitials"]) == 2


def test_every_word_of_every_text_is_replaced_the_same_wherever_it_is_keeping_its_shape() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    pseudonymiser.learn({"name": "Alma og Bo"})
    name = pseudonymiser.value("Alma og Bo", "name")
    text = pseudonymiser.value("Hej Alma og Bo, Almas bog", "text")
    note = pseudonymiser.value("Bo og Alma", "note")
    assert isinstance(name, str) and isinstance(text, str)
    alma, og, bo = name.split()
    hej, _, _, _, almas, bog = text.replace(",", "").split()
    assert text == f"{hej} {alma} {og} {bo}, {almas} {bog}" and note == f"{bo} {og} {alma}"
    assert (alma, og, bo) != ("Alma", "og", "Bo") and len(almas) == 5 and almas[0].isupper() and bog.islower()
    assert "Hej" not in text and "bog" not in text


def test_contact_details_are_replaced_in_their_keys_and_in_texts() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    contact = {"email": "pat@example.org", "mobilePhone": "+45 12 34 56 78", "homeAddress": "Vej 1", "workPhone": " "}
    pseudonymiser.learn(contact)
    replaced: dict[str, str] = pseudonymiser.value(contact)
    assert replaced["workPhone"] == " "
    assert all(replaced[key] != value and len(replaced[key]) == len(value) for key, value in contact.items() if value.strip())
    original = "Skriv til pat@example.org, ring 87 65 43 21 eller på Vej 1; cpr 010203-1234"
    text = pseudonymiser.value(original, "text")
    assert isinstance(text, str) and len(text) == len(original)
    for value in ("pat@example.org", "87 65 43 21", "Vej 1", "010203-1234"):
        assert value not in text
    assert replaced["email"] in text


def test_dates_numbers_and_short_ids_in_a_text_are_kept_and_its_words_replaced() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    pseudonymiser.learn({"id": 2026, "profileId": 2048194, "count": 12})
    assert pseudonymiser.value("2026-12-29T08:00:00+00:00", "start") == "2026-12-29T08:00:00+00:00"
    week = pseudonymiser.value("Uge 2026, side 12", "text")
    assert week != "Uge 2026, side 12" and re.fullmatch(r"[A-Z][a-z]{2} 2026, [a-z]{4} 12", week)
    assert pseudonymiser.value("Profil 2048194", "text") != "Profil 2048194"
    assert pseudonymiser.value({"count": 12, "share": 0.5, "none": None, "seen": True}) == {
        "count": 12,
        "share": 0.5,
        "none": None,
        "seen": True,
    }


def test_a_number_that_is_a_known_id_is_replaced_under_any_key() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    pseudonymiser.learn({"id": 3301846})
    replaced = pseudonymiser.value({"belongsToProfiles": [3301846, 7], "3301846": "child"})
    child = pseudonymiser.value(3301846, "id")
    assert replaced == {"belongsToProfiles": [child, 7], str(child): pseudonymiser.value("child")}


def test_a_link_keeps_a_site_reserved_for_examples_and_its_query_names_and_has_the_rest_replaced() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    pseudonymiser.learn({"id": 3301846})
    link = "https://files.example.org/3301846/foto.jpg?sig=Zm9v&exp=1&flag#top"
    replaced = pseudonymiser.value(link, "url")
    assert isinstance(replaced, str) and len(replaced) == len(link)
    assert replaced.startswith("https://files.example.org/") and replaced.endswith("&flag#top")
    assert "3301846" not in replaced and "Zm9v" not in replaced and "foto" not in replaced
    assert re.search(r"/[a-z]{4}\.[a-z]{3}\?sig=", replaced)


def test_a_request_keeps_its_query_but_for_its_ids_and_secrets() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    url = "https://aula.example/api/v23?method=calendar.get&instProfileIds%5B%5D=3301846&start=2026-12-28&token=abc"
    replaced = pseudonymiser.url(url, request=True)
    assert replaced.startswith("https://aula.example/api/v23?method=calendar.get&instProfileIds%5B%5D=")
    assert replaced.endswith("&start=2026-12-28&token=xxx") and "3301846" not in replaced
    assert len(replaced) == len(url)


def test_exchanges_are_replaced_after_learning_from_all_of_them() -> None:
    exchanges = [
        Exchange("GET", "https://aula.example/api?method=a", None, 200, "Alma er syg", AT),
        Exchange("POST", "https://aula.example/widget", {"childId": 3301846}, 200, {"name": "Alma"}, AT),
    ]
    first, second = pseudonymised(exchanges, KEY)
    alma: str = second["response"]["name"]
    response: str = first["response"]
    assert re.fullmatch(rf"{alma} [a-z]{{2}} [a-z]{{3}}", response) and response != f"{alma} er syg"
    assert {**first, "response": None} == {
        "at": "2026-12-28T08:00:00+00:00",
        "endpoint": "a",
        "method": "GET",
        "url": "https://aula.example/api?method=a",
        "request": None,
        "status": 200,
        "headers": {},
        "error": None,
        "response": None,
    }
    assert second["endpoint"] == "/widget" and second["request"] != {"childId": 3301846}


def test_shapes_name_the_types_at_each_place() -> None:
    assert shapes({"data": [{"id": 1, "name": None}, {"id": "2"}], "ok": True}) == {
        ".": ["object"],
        "data": ["list"],
        "data[]": ["object"],
        "data[].id": ["int", "str"],
        "data[].name": ["null"],
        "ok": ["bool"],
    }
    assert shapes([1]) == {".": ["list"], "[]": ["int"]}


def test_a_widget_s_filters_are_ids_however_short() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    body = {"childFilter": ["pat"], "institutionFilter": ["S1"], "userProfile": "guardian"}
    replaced: dict[str, Any] = pseudonymiser.value(body, words=False)
    assert replaced["childFilter"] != ["pat"] and len(replaced["childFilter"][0]) == 3
    assert replaced["institutionFilter"] != ["S1"] and replaced["userProfile"] == "guardian"
    url = pseudonymiser.url("https://widget.example/plans?childFilter[]=pat&institutionFilter[]=S1", request=True)
    assert url == f"https://widget.example/plans?childFilter[]={replaced['childFilter'][0]}&institutionFilter[]={replaced['institutionFilter'][0]}"


def test_the_endpoint_of_a_widget_s_path_has_its_ids_replaced() -> None:
    exchange = Exchange("GET", "https://widget.example/files/3301846", None, 200, {"childId": 3301846}, AT)
    [replaced] = pseudonymised([exchange], KEY)
    child = str(replaced["response"]["childId"])
    assert replaced["endpoint"] == f"/files/{child}"
    assert replaced["url"] == f"https://widget.example/files/{child}"


def test_a_token_becomes_as_many_x_wherever_it_stands() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
    replaced: dict[str, Any] = _replaced(
        {"value": jwt, "note": f"Brug {jwt} nu", "header": "Bearer abc.DEF-123", "bearerToken": 42, "jwt": "abc"}
    )
    assert re.fullmatch(rf"[A-Z][a-z]{{3}} {'x' * len(jwt)} [a-z]{{2}}", replaced["note"]) and not replaced["note"].startswith("Brug")
    assert replaced == {
        "value": "x" * len(jwt),
        "note": replaced["note"],
        "header": "x" * len("Bearer abc.DEF-123"),
        "bearerToken": 99,
        "jwt": "xxx",
    }


def test_what_a_request_for_a_token_answers_is_hidden_whole_but_its_status() -> None:
    answer = {"status": {"code": 0, "message": "OK"}, "data": "opaque-widget-token", "version": 23}
    exchange = Exchange("GET", "https://aula.example/api?method=aulaToken.getAulaToken&widgetId=0004", None, 200, answer, AT)
    [replaced] = pseudonymised([exchange], KEY)
    assert replaced["response"] == {**answer, "data": "x" * len("opaque-widget-token")}


def test_the_secrets_given_are_hidden_wherever_they_are() -> None:
    exchange = Exchange(
        "GET",
        "https://aula.example/api?method=a",
        None,
        0,
        None,
        AT,
        headers={"Set-Cookie": "Csrfp-Token=abc; path=/", "Content-Type": "application/json"},
        error="ClientError: logged in as parent-user with s3cr3t",
    )
    [replaced] = pseudonymised([exchange], KEY, ["parent-user", "s3cr3t", ""])
    assert replaced["error"] == "ClientError: logged in as xxxxxxxxxxx with xxxxxx"
    assert replaced["headers"] == {"Set-Cookie": "x" * len("Csrfp-Token=abc; path=/"), "Content-Type": "application/json"}


def test_hidden_keeps_each_value_s_type_and_length() -> None:
    from aula_connect.pseudonym import hidden

    assert hidden({"a": ["xy", 120, -7, 1.5, None, True]}) == {"a": ["xx", 999, -9, 1.5, None, True]}


def test_html_keeps_its_tags_entities_style_and_class_and_has_the_words_of_its_text_and_titles_replaced() -> None:
    html = '<p class="note" style="color:red" title="Til Alma">Hej&nbsp;Alma<br/></p>'
    replaced: str = _replaced(html, "html")
    assert re.fullmatch(r'<p class="note" style="color:red" title="[A-Z][a-z]{2} [A-Z][a-z]{3}">[A-Z][a-z]{2}&nbsp;[A-Z][a-z]{3}<br/></p>', replaced)
    assert "Alma" not in replaced and "Hej" not in replaced


def test_what_tells_how_an_answer_is_built_is_kept() -> None:
    answer = {
        "status": {"code": 0, "message": "OK"},
        "messageType": "RecipientsRemoved",
        "notificationArea": "Homework",
        "role": "guardian",
        "module": "presence",
        "event": "NewMessagePrivateInbox",
        "method": "presence.getDailyOverview",
        "level": "PRESENCE_ADMIN",
    }
    assert _replaced(answer) == answer


def test_who_someone_is_is_replaced_in_every_field_that_names_them_and_a_municipality_by_its_code() -> None:
    answer = {"leaverNames": ["Clara", "Oscar"], "metadata": "Benjamin 2A", "municipalityCode": "791", "gender": "Female"}
    replaced: dict[str, Any] = _replaced(answer)
    assert all(name not in json.dumps(replaced) for name in ("Clara", "Oscar", "Benjamin", "791", "Female"))
    assert re.fullmatch(r"[A-Z][a-z]{7} 2[A-Z]", replaced["metadata"]) and len(replaced["municipalityCode"]) == 3


def test_a_link_has_its_path_replaced_and_its_site_unless_aula_s_and_a_request_keeps_its_path() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    other = pseudonymiser.value("https://www.viborg.dk/skoler/alma?x=1", "url")
    aula = pseudonymiser.value("https://media-prod.aula.dk/profile-pictures/x.jpg", "url")
    assert re.fullmatch(r"https://[a-z]{3}\.[a-z]{6}\.dk/[a-z]{6}/[a-z]{4}\?x=\d", other) and "viborg" not in other
    assert re.fullmatch(r"https://media-prod\.aula\.dk/[a-z]{7}-[a-z]{8}/[a-z]\.[a-z]{3}", aula)
    assert "profile" not in aula
    request = pseudonymiser.url("https://www.aula.dk/api/v25/profiles?method=profiles.getProfileContext", request=True)
    assert request == "https://www.aula.dk/api/v25/profiles?method=profiles.getProfileContext"
