"""The marks of what the user has seen, read twice."""

from aula_connect.read_marks import WATCHED, compare

POSTS, THREADS, NOTIFICATIONS = WATCHED


def test_a_thread_counts_as_moved_once_read_or_read_further_not_when_a_message_comes() -> None:
    first = {"data": {"threads": [
        {"id": 1, "read": False, "lastReadMessageId": "a"},
        {"id": 2, "read": True, "lastReadMessageId": "b"},
        {"id": 3, "read": True, "lastReadMessageId": "c"},
        {"id": 4, "read": False, "lastReadMessageId": None},
        "not a thread",
    ]}}
    second = {"data": {"threads": [
        {"id": 1, "read": True, "lastReadMessageId": "a"},
        {"id": 2, "read": False, "lastReadMessageId": "b"},
        {"id": 4, "read": False, "lastReadMessageId": "d"},
    ]}}
    mark = compare(THREADS, first, second, 6.04)
    assert mark.as_dict() == {
        "method": "messaging.getThreads",
        "mark": "threads not read",
        "before": 2,
        "after": 2,
        "moved": 2,
        "seconds": 6.0,
    }


def test_a_notification_counts_as_moved_when_it_is_gone_not_when_another_comes() -> None:
    first = {"data": [{"notificationId": "a"}, {"notificationId": "b"}]}
    second = {"data": [{"notificationId": "b"}, {"notificationId": "c"}, {"notificationId": "d"}]}
    mark = compare(NOTIFICATIONS, first, second, 5)
    assert (mark.before, mark.after, mark.moved) == (2, 3, 1)


def test_an_answer_without_its_marks_tells_none() -> None:
    for watched in WATCHED:
        for answer in (None, "text", {"data": None}, {"data": "text"}):
            assert compare(watched, answer, answer, 0).moved == 0
    assert compare(POSTS, {"data": {}}, {"data": {"profileLastSeenPostDate": "x"}}, 0).moved == 1
