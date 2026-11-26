"""The catalog of Aula's API methods."""

from aula_connect.methods import METHODS, Kind, alike, known


def test_a_name_is_known_only_as_aula_spells_it_and_alike_in_any_case() -> None:
    assert known("presence.getdailyoverview") is None
    assert alike("presence.getdailyoverview") is METHODS["presence.getDailyOverview"]
    assert known("calendar.getNothing") is None and alike("calendar.getNothing") is None


def test_only_a_method_that_only_gets_and_nothing_sensitive_is_readable() -> None:
    assert {method.readable for method in METHODS.values() if method.kind is Kind.READ} == {True}
    assert {method.readable for method in METHODS.values() if method.kind is not Kind.READ} == {False}


def test_a_method_sends_a_body_only_with_post() -> None:
    assert all(not method.body for method in METHODS.values() if method.verb == "GET")


def test_a_method_is_spelt_as_aula_s_own_web_app_spells_it() -> None:
    assert known("Documents.getSecureDocuments") is not None
    assert known("Notifications.getNotificationSettingsForActiveProfile") is not None
    assert known("notifications.getNotificationsForActiveProfile") is not None
