"""Reading the methods Aula's own web app asks, against the catalog."""

from aula_connect.web_methods import differences, methods, scripts

PAGE = '<script src="/static/script/IE.js"></script><script src="/static/js/0.abc.js"></script><script src="/static/js/app.def.js"></script>'
SOURCE = (
    'A.b.get("?method=posts.getAllPosts",{params:r});'
    'u.b.post("?method=Documents.getSecureDocuments",t.params,r);'
    'T.b.get("?method=presence.getClosedDays",{params:t});'
    'x.get("?method=calendar.getEventsByProfileIdsAndResourceIds");'
    'url:"?method=galleryAdmin.getAlbums"'
)


def test_the_scripts_of_aula_s_web_app_are_those_under_static_js() -> None:
    assert scripts(PAGE) == ["/static/js/0.abc.js", "/static/js/app.def.js"]


def test_a_method_is_found_with_the_verbs_it_is_asked_with_and_none_where_only_named() -> None:
    assert methods([SOURCE]) == {
        "posts.getAllPosts": {"GET"},
        "Documents.getSecureDocuments": {"POST"},
        "presence.getClosedDays": {"GET"},
        "calendar.getEventsByProfileIdsAndResourceIds": {"GET"},
        "galleryAdmin.getAlbums": set(),
    }


def test_what_the_catalog_says_otherwise_is_named_but_an_administrator_s_method() -> None:
    found = methods([SOURCE])
    lines = differences({**found, "x.y": set()})
    assert "not in the catalog: presence.getClosedDays GET" in lines
    assert "not in the catalog: x.y ?" in lines
    assert "asked otherwise: calendar.getEventsByProfileIdsAndResourceIds with POST, the web app with GET" in lines
    assert "not in the web app: aulaToken.getAulaToken" in lines
    assert not any("posts.getAllPosts" in line or "galleryAdmin" in line or "Documents" in line for line in lines)


def test_a_name_spelt_otherwise_in_the_web_app_is_named() -> None:
    assert "spelt otherwise: posts.getAllPosts is Posts.getAllPosts in the web app" in differences({"Posts.getAllPosts": {"GET"}})
