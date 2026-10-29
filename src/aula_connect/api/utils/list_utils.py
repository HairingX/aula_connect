"""Helpers for lists."""


from typing import Iterable, List, TypeVar

T = TypeVar('T')

def list_without_none(data: Iterable[T|None]) -> List[T]:
    """The items that are not None, in order."""
    return [d for d in data if d is not None ]