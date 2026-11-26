"""What of the catalog is asked once, and with what."""

import dataclasses
import datetime

from aula_connect.catalog_read import ITEMS, NO_VALUES, Account, plan, readable, then

ACCOUNT = Account(children=[11], profiles=[11, 21], institutions=["S1"], groups=[], start=datetime.date(2026, 11, 2), end=datetime.date(2026, 11, 16))


def test_every_method_that_only_reads_is_planned_followed_or_said_why_not() -> None:
    planned = {method for method, _ in plan(dataclasses.replace(ACCOUNT, groups=[1]))}
    followed = {"posts.getById", "comments.getComments", "gallery.getMedia", "gallery.getMediaById", "presence.getPresenceRegistrationDetail"}
    already = {
        "calendar.getBirthdayEventsForInstitutions", "calendar.getEventById", "calendar.getEventsByProfileIdsAndResourceIds",
        "notifications.getNotificationsForActiveProfile", "presence.getDailyOverview", "profiles.getProfileContext",
        "profiles.getProfileMasterData", "profiles.getProfilesByLogin",
    }
    assert set(readable()) == planned | followed | already | set(NO_VALUES)


def test_a_child_without_a_main_group_asks_nothing_of_a_group() -> None:
    assert not [method for method, params in plan(ACCOUNT) if any(name.lower() == "groupid" for name, _ in params)]


def test_the_first_items_of_a_list_are_read_one_by_one_and_nothing_of_no_list() -> None:
    posts = then("posts.getAllPosts", {"posts": [{"id": number} for number in range(5)]}, ACCOUNT)
    assert [params for method, params in posts if method == "posts.getById"] == [(("id", str(number)),) for number in range(ITEMS)]
    assert then("posts.getAllPosts", {"posts": None}, ACCOUNT) == []
    assert then("gallery.getAlbums", None, ACCOUNT) == []
    assert then("presence.getPresenceRegistrations", [{"id": 1}, "x", {"no": "id"}], ACCOUNT) == [
        ("presence.getPresenceRegistrationDetail", (("id", "1"),))
    ]
