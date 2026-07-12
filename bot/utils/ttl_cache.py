from __future__ import annotations

from collections import OrderedDict
from time import monotonic
from typing import Generic, TypeVar


T = TypeVar("T")


class TTLCache(Generic[T]):
    """Невеликий обмежений TTL-кеш без зовнішніх залежностей.

    Кеш не росте нескінченно: прострочені записи очищаються, а при
    перевищенні ``max_size`` видаляються найстаріші значення.
    """

    def __init__(self, *, ttl_seconds: float, max_size: int = 5_000) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds має бути більше нуля")
        if max_size <= 0:
            raise ValueError("max_size має бути більше нуля")
        self._ttl = float(ttl_seconds)
        self._max_size = int(max_size)
        self._values: OrderedDict[T, float] = OrderedDict()

    def add(self, value: T) -> None:
        now = monotonic()
        self._purge(now)
        self._values.pop(value, None)
        self._values[value] = now + self._ttl
        while len(self._values) > self._max_size:
            self._values.popitem(last=False)

    def contains(self, value: T) -> bool:
        now = monotonic()
        expires_at = self._values.get(value)
        if expires_at is None:
            self._purge(now)
            return False
        if expires_at <= now:
            self._values.pop(value, None)
            return False
        self._values.move_to_end(value)
        return True

    def discard(self, value: T) -> None:
        self._values.pop(value, None)

    def _purge(self, now: float) -> None:
        expired = [
            value for value, expires_at in self._values.items() if expires_at <= now
        ]
        for value in expired:
            self._values.pop(value, None)
