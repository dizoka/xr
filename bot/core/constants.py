DEFAULT_SETTINGS: dict[str, str] = {
    "store_name": "CrystalStore | Ковель",
    "welcome_text": (
        "Ласкаво просимо до каталогу CrystalStore.\n\n"
        "Оберіть потрібний розділ нижче."
    ),
    "address_schedule": (
        "📍 Ковель\n"
        "🕒 Пн–Нд: 12:00–19:00\n\n"
        "Точну адресу уточнюйте у продавця."
    ),
    "contact_url": "https://t.me/USERNAME",
    "currency": "грн",
    "age_warning": (
        "🔞 Каталог призначений лише для повнолітніх користувачів.\n\n"
        "Натискаючи кнопку нижче, ви підтверджуєте, що вам уже виповнилося 18 років."
    ),
}

DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("POD-системи", "💨"),
    ("Картриджі", "🧩"),
    ("Рідини", "💧"),
    ("Акції", "🔥"),
)

PRODUCTS_PER_PAGE = 6
