"""What of the catalog is asked once, and with what."""

import dataclasses
import datetime

from aula_connect.catalog_read import FOLLOWED, ITEMS, NO_VALUES, Account, plan, readable, then
from aula_connect.methods import METHODS, Kind

ACCOUNT = Account(children=[11], own=[21], profiles=[11, 21], institutions=["S1"], groups=[], start=datetime.date(2026, 11, 2), end=datetime.date(2026, 11, 16))


def test_only_methods_that_only_read_are_planned_or_followed_and_none_for_staff() -> None:
    planned = {method for method, _ in plan(dataclasses.replace(ACCOUNT, groups=[1]))}
    assert planned | FOLLOWED <= set(readable())
    assert not [name for name in planned | FOLLOWED if METHODS[name].kind is Kind.STAFF]
    assert set(NO_VALUES) <= set(readable())


def test_a_child_without_a_main_group_asks_nothing_of_a_group() -> None:
    assert not [method for method, params in plan(ACCOUNT) if any(name.lower() == "groupid" for name, _ in params)]


def test_the_first_items_of_a_list_are_read_one_by_one_and_nothing_of_no_list() -> None:
    posts = then("posts.getAllPosts", {"posts": [{"id": number} for number in range(5)]}, ACCOUNT)
    assert [params for method, params in posts if method == "posts.getById"] == [(("id", str(number)),) for number in range(ITEMS)]
    assert then("posts.getAllPosts", {"posts": None}, ACCOUNT) == []
    assert then("gallery.getAlbums", None, ACCOUNT) == []
    assert then("gallery.getMedia", {"results": [{"id": 1}, "x", {"no": "id"}]}, ACCOUNT) == [("gallery.getMediaById", (("id", "1"),))]


def test_the_first_vacation_requests_are_read_one_by_one() -> None:
    answer = [{"vacationRegistrations": [{"responseId": 5}, {"no": "id"}, "x"]}, "y"]
    assert then("presence.getVacationRegistrationsByChildren", answer, ACCOUNT) == [
        ("presence.getVacationRegistrationResponse", (("vacationRegistrationResponseId", "5"),))
    ]
    assert then("presence.getVacationRegistrationsByChildren", {"no": "list"}, ACCOUNT) == []
