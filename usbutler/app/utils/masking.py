"""Utility functions for masking sensitive data."""


def mask_identifier(value: str | None, visible_bytes: int = 1) -> str:
    if not value:
        return ""
    clean = value.replace(" ", "").upper()
    chars_per_unit = (
        2 if all(c in "0123456789ABCDEF" for c in clean) and len(clean) % 2 == 0 else 1
    )
    visible_chars = visible_bytes * chars_per_unit
    if len(clean) < visible_chars * 2 + 2:
        return clean
    return f"{clean[:visible_chars]}..{clean[-visible_chars:]}"
