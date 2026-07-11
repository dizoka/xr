from __future__ import annotations

from dataclasses import dataclass
import os
import secrets

from dotenv import load_dotenv


load_dotenv()


class ConfigError(RuntimeError):
    """Виникає, коли обов’язкові налаштування відсутні або некоректні."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    turso_database_url: str
    turso_auth_token: str
    webhook_base_url: str
    webhook_secret: str
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or token == "PASTE_BOT_TOKEN_HERE":
            raise ConfigError("BOT_TOKEN не налаштовано.")

        raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
        if not raw_admin_ids or raw_admin_ids == "PASTE_YOUR_TELEGRAM_ID_HERE":
            raise ConfigError("ADMIN_IDS не налаштовано.")

        try:
            admin_ids = frozenset(
                int(value.strip())
                for value in raw_admin_ids.split(",")
                if value.strip()
            )
        except ValueError as exc:
            raise ConfigError("ADMIN_IDS має містити числові Telegram ID через кому.") from exc

        if not admin_ids:
            raise ConfigError("Потрібно вказати щонайменше один ADMIN_IDS.")

        database_url = os.getenv("TURSO_DATABASE_URL", "").strip()
        auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
        if not database_url:
            raise ConfigError("TURSO_DATABASE_URL не налаштовано.")
        if not auth_token:
            raise ConfigError("TURSO_AUTH_TOKEN не налаштовано.")

        base_url = (
            os.getenv("WEBHOOK_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        ).rstrip("/")
        if not base_url:
            raise ConfigError(
                "Не знайдено WEBHOOK_BASE_URL або автоматичну адресу Render."
            )
        if not base_url.startswith("https://"):
            raise ConfigError("Адреса webhook повинна починатися з https://")

        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if not webhook_secret:
            webhook_secret = secrets.token_urlsafe(32)

        try:
            port = int(os.getenv("PORT", "10000"))
        except ValueError as exc:
            raise ConfigError("PORT повинен бути числом.") from exc

        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            turso_database_url=database_url,
            turso_auth_token=auth_token,
            webhook_base_url=base_url,
            webhook_secret=webhook_secret,
            port=port,
        )
