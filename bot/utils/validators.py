from __future__ import annotations

import re


_PRICE_RE = re.compile(r"^(?:0|[1-9]\d{0,7})(?:[.,]\d{1,2})?$")


def normalize_price(value: str) -> str | None:
    """Перевіряє й нормалізує ціну без зміни старої схеми Turso."""

    cleaned = value.strip().replace(" ", "").replace(",", ".")
    if not _PRICE_RE.fullmatch(cleaned):
        return None
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned
