from __future__ import annotations

import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.core.config import ConfigError, Settings
from bot.db.database import Database
from bot.handlers.admin import AdminHandlers
from bot.handlers.user import UserHandlers
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository


WEBHOOK_PATH = "/telegram/webhook"


def build_application(settings: Settings) -> web.Application:
    database = Database(
        settings.turso_database_url,
        settings.turso_auth_token,
    )
    catalog_repository = CatalogRepository(database)
    inquiry_repository = InquiryRepository(database)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())

    # Спочатку підключаємо користувацькі кнопки. Так u:* завжди
    # обробляються каталогом і не перетинаються з адмін-middleware.
    dispatcher.include_router(
        UserHandlers(
            catalog_repository,
            inquiry_repository,
            settings.admin_ids,
        ).router
    )
    dispatcher.include_router(
        AdminHandlers(
            catalog_repository,
            inquiry_repository,
            settings.admin_ids,
        ).router
    )

    async def on_startup(bot: Bot) -> None:
        await database.connect()
        await database.initialize()

        public_commands = [
            BotCommand(command="start", description="Відкрити каталог"),
            BotCommand(command="catalog", description="Каталог товарів"),
            BotCommand(command="id", description="Показати мій Telegram ID"),
        ]
        await bot.set_my_commands(public_commands)

        admin_commands = [
            *public_commands,
            BotCommand(command="admin", description="Адмін-панель"),
            BotCommand(command="addadmin", description="Додати працівника"),
            BotCommand(command="deladmin", description="Забрати доступ працівника"),
            BotCommand(command="admins", description="Список працівників"),
        ]
        for admin_id in settings.admin_ids:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )

        webhook_url = f"{settings.webhook_base_url}{WEBHOOK_PATH}"
        await bot.set_webhook(
            webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
        logging.info("Webhook встановлено: %s", webhook_url)
        logging.info("Бот CrystalStore запущено безкоштовно на Render")

    async def on_shutdown() -> None:
        # Webhook навмисно не видаляємо: він повинен будити безкоштовний Render.
        await database.close()

    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "CrystalStoreBot"})

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
        handle_in_background=True,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dispatcher, bot=bot)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )

    try:
        settings = Settings.from_env()
        app = build_application(settings)
        web.run_app(app, host="0.0.0.0", port=settings.port)
    except ConfigError as exc:
        logging.critical("ПОМИЛКА НАЛАШТУВАННЯ: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
