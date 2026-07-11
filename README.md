# CrystalStoreBot — український Telegram-каталог

Безкоштовна версія для Render Web Service + Turso.

Повна інструкція: `RENDER_FREE_SETUP_UA.md`.

## Змінні середовища

- `BOT_TOKEN`
- `ADMIN_IDS`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `WEBHOOK_SECRET (необов’язково)`

Render автоматично надає `RENDER_EXTERNAL_URL` і `PORT`.


## Виправлення кнопки 18+

У цій версії підтвердження віку обробляється одразу, індикатор кнопки не зависає,
а доступ відкривається навіть під час короткого пробудження бази Turso.
