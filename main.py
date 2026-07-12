from __future__ import annotations

import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.core.config import ConfigError, Settings
from bot.db.database import Database
from bot.handlers.admin import AdminHandlers
from bot.handlers.errors import global_error_handler
from bot.handlers.user import UserHandlers
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.storage import TursoStorage


logger = logging.getLogger(__name__)
WEBHOOK_PATH = "/telegram/webhook"


def build_application(settings: Settings) -> web.Application:
    database = Database(settings.turso_database_url, settings.turso_auth_token)
    catalog_repository = CatalogRepository(database)
    inquiry_repository = InquiryRepository(database)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=TursoStorage(database))
    dispatcher.errors.register(global_error_handler)

    dispatcher.include_router(
        UserHandlers(
            catalog=catalog_repository,
            inquiries=inquiry_repository,
            admin_ids=settings.admin_ids,
            bot=bot,
        ).router
    )
    dispatcher.include_router(
        AdminHandlers(
            catalog=catalog_repository,
            inquiries=inquiry_repository,
            admin_ids=settings.admin_ids,
        ).router
    )

    async def on_startup(bot: Bot) -> None:
        await database.connect()
        await database.initialize()

        public_commands = [
            BotCommand(command="start", description="Відкрити головне меню"),
            BotCommand(command="catalog", description="Каталог товарів"),
            BotCommand(command="help", description="Допомога"),
            BotCommand(command="id", description="Показати мій Telegram ID"),
        ]
        await bot.set_my_commands(public_commands)

        admin_commands = [
            *public_commands,
            BotCommand(command="admin", description="Адмін-панель"),
            BotCommand(command="addadmin", description="Додати адміністратора"),
            BotCommand(command="deladmin", description="Забрати адміністратора"),
            BotCommand(command="admins", description="Список адміністраторів"),
        ]
        staff_commands = [
            *public_commands,
            BotCommand(command="admin", description="Адмін-панель"),
        ]

        for admin_id in settings.admin_ids:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        for staff_id in await catalog_repository.list_staff_admins():
            await bot.set_my_commands(
                staff_commands,
                scope=BotCommandScopeChat(chat_id=staff_id),
            )

        webhook_url = f"{settings.webhook_base_url}{WEBHOOK_PATH}"
        await bot.set_webhook(
            webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
        logger.info("Webhook встановлено: %s", webhook_url)
        logger.info("CrystalStoreBot готовий до роботи")

    async def on_shutdown() -> None:
        # Webhook не видаляємо: Telegram зможе розбудити Render після сну.
        await database.close()

    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    app = web.Application()

    async def live(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "CrystalStoreBot"})

    async def ready(_: web.Request) -> web.Response:
        is_ready = await database.ping()
        return web.json_response(
            {
                "status": "ok" if is_ready else "unavailable",
                "service": "CrystalStoreBot",
                "database": "ok" if is_ready else "error",
            },
            status=200 if is_ready else 503,
        )

    app.router.add_get("/", live)
    app.router.add_get("/health/live", live)
    app.router.add_get("/health", ready)
    app.router.add_get("/health/ready", ready)

    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
        # Для замовлень важливіше завершити запис у Turso до відповіді Telegram.
        handle_in_background=False,
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
        logger.critical("ПОМИЛКА НАЛАШТУВАННЯ: %s", exc)
        sys.exit(1)
    except Exception:
        logger.critical("Бот не вдалося запустити", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
