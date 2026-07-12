from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.utils.callbacks import answer_callback_safely


class RateLimitMiddleware(BaseMiddleware):
    """Простий захист від флуду з автоматичним очищенням пам'яті."""

    def __init__(self, *, limit: int, period: float) -> None:
        self._limit = max(1, int(limit))
        self._period = max(0.5, float(period))
        self._requests: dict[int, deque[float]] = defaultdict(deque)
        self._last_cleanup = monotonic()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = monotonic()
        history = self._requests[user.id]
        threshold = now - self._period
        while history and history[0] <= threshold:
            history.popleft()

        if len(history) >= self._limit:
            if isinstance(event, CallbackQuery):
                await answer_callback_safely(
                    event,
                    "Забагато дій. Зачекайте кілька секунд.",
                )
            elif isinstance(event, Message):
                await event.answer(
                    "Забагато повідомлень. Спробуйте через кілька секунд."
                )
            return None

        history.append(now)
        if now - self._last_cleanup >= 60:
            self._cleanup(now)
            self._last_cleanup = now

        return await handler(event, data)

    def _cleanup(self, now: float) -> None:
        threshold = now - self._period
        empty_users: list[int] = []
        for user_id, history in self._requests.items():
            while history and history[0] <= threshold:
                history.popleft()
            if not history:
                empty_users.append(user_id)
        for user_id in empty_users:
            self._requests.pop(user_id, None)
