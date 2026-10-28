from datetime import date, datetime, time, timedelta, timezone

import pytest

from aula_connect.api.models.aula_parser import AulaParser, now, set_time_zone
from aula_connect.api.utils.list_utils import list_without_none


@pytest.mark.parametrize(
    ("value", "icon"),
    [
        (None, None),
        ("library-books", "mdi:library"),
        ("playground", "mdi:slide"),
        ("pets", "mdi:paw"),
        ("cykling", "mdi:bike"),
        ("sports-hall", "mdi:gymnastics"),
        ("theater", "mdi:theater"),
        ("walking", "mdi:walk"),
        ("skateboard", "mdi:skateboard"),
        ("hammer", "mdi:hammer"),
        ("scissors", "mdi:content-cut"),
        ("books", "mdi:bookshelf"),
        ("swim", "mdi:swim"),
        ("pens", "mdi:lead-pencil"),
        ("paint", "mdi:brush"),
        ("football", "mdi:soccer"),
        ("fire", "mdi:campfire"),
        ("ice", "mdi:skate"),
        ("unknown", None),
    ],
)
def test_an_icon_name_maps_to_the_first_matching_mdi_icon(value: str | None, icon: str | None) -> None:
    assert AulaParser._parse_nullable_icon_str(value) == icon


def test_bools_are_true_only_for_true_values() -> None:
    assert AulaParser._parse_bool(True) is True
    assert AulaParser._parse_bool(1) is True
    assert AulaParser._parse_bool("true") is False
    assert AulaParser._parse_bool(None) is False
    assert AulaParser._parse_nullable_bool(None) is None
    assert AulaParser._parse_nullable_bool(False) is False
    assert AulaParser._parse_nullable_bool(0) is False


def test_ints_parse_from_numbers_and_text() -> None:
    assert AulaParser._parse_int(None) == -1
    assert AulaParser._parse_int(7) == 7
    assert AulaParser._parse_int("8") == 8
    assert AulaParser._parse_nullable_int(None) is None
    assert AulaParser._parse_nullable_int("9") == 9
    assert AulaParser._parse_int_list([1, 2]) == [1, 2]
    assert AulaParser._parse_int_list(["1"]) == []
    assert AulaParser._parse_int_list(None) == []


def test_an_unsure_int_never_raises() -> None:
    assert AulaParser._parse_nullable_int_safe(None) is None
    assert AulaParser._parse_nullable_int_safe(True) is None
    assert AulaParser._parse_nullable_int_safe(3) == 3
    assert AulaParser._parse_nullable_int_safe("4") == 4
    assert AulaParser._parse_nullable_int_safe("x") is None


def test_strings_parse_from_anything() -> None:
    assert AulaParser._parse_str(None) == ""
    assert AulaParser._parse_str(5) == "5"
    assert AulaParser._parse_nullable_str(None) is None
    assert AulaParser._parse_nullable_str(5) == "5"


def test_dates_parse_from_text_with_or_without_a_time() -> None:
    assert AulaParser._parse_date(None) == date.min
    assert AulaParser._parse_date("2026-03-16") == date(2026, 3, 16)
    assert AulaParser._parse_date("2026-03-16T08:00:00+00:00") == date(2026, 3, 16)
    assert AulaParser._parse_nullable_date(date(2026, 1, 2)) == date(2026, 1, 2)


def test_times_parse_from_text_and_drop_the_date() -> None:
    assert AulaParser._parse_time(None, fix_timezone=False) == time.min
    assert AulaParser._parse_time("2026-03-16T08:15:00", fix_timezone=False) == time(8, 15)
    assert AulaParser._parse_nullable_time(time(9, 0), fix_timezone=False) == time(9, 0)
    assert AulaParser._parse_nullable_time(datetime(2026, 1, 1, 10, 30), fix_timezone=False) == time(10, 30)


def test_datetimes_parse_and_take_the_local_zone() -> None:
    assert AulaParser._parse_datetime(None, fix_timezone=False) == datetime.min
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert AulaParser._parse_nullable_datetime(aware, fix_timezone=False) is aware
    assert AulaParser._parse_nullable_datetime(date(2026, 1, 2), fix_timezone=False) == datetime(2026, 1, 2)
    assert AulaParser._parse_nullable_datetime("2026-01-02", fix_timezone=False) == datetime(2026, 1, 2)
    parsed = AulaParser._parse_datetime("2026-01-02T12:00:00+00:00", fix_timezone=False)
    assert parsed == aware + timedelta(days=1)


def test_a_time_aula_sends_as_utc_is_read_in_the_institutions_zone() -> None:
    copenhagen = timezone(timedelta(hours=1))
    set_time_zone(copenhagen)
    try:
        fixed = AulaParser._parse_datetime("2026-01-02T08:00:00+00:00", fix_timezone=True)
        assert (fixed.hour, fixed.utcoffset()) == (8, timedelta(hours=1))
        assert AulaParser._parse_time("08:00:00", fix_timezone=True) == time(8, 0)
        assert now().utcoffset() == timedelta(hours=1)
    finally:
        set_time_zone(None)
    assert now().tzinfo is not None


def test_none_is_left_out_of_a_list() -> None:
    assert list_without_none([1, None, 2]) == [1, 2]
