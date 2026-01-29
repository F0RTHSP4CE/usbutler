"""Utility functions for masking sensitive data."""


def mask_identifier(value: str | None, visible_bytes: int = 1) -> str:
    """
    Mask an identifier (UID or PAN) showing only first and last bytes.

    For hex strings (UIDs), each byte is 2 characters.
    For PANs, shows first and last digits.

    Args:
        value: The identifier value to mask
        visible_bytes: Number of bytes to show at start and end (default: 1)

    Returns:
        Masked string like "AB..CD" or original if too short to mask
    """
    if not value:
        return ""

    # Clean up the value (remove spaces, uppercase)
    clean = value.replace(" ", "").upper()

    # Determine characters per "byte" based on content
    # Hex strings (UIDs): 2 chars per byte
    # Numeric strings (PANs): 1 char per digit
    if all(c in "0123456789ABCDEF" for c in clean) and len(clean) % 2 == 0:
        # Looks like hex (UID) - 2 chars per byte
        chars_per_unit = 2
    else:
        # Treat as numeric/text - 1 char per unit
        chars_per_unit = 1

    visible_chars = visible_bytes * chars_per_unit
    min_length = visible_chars * 2 + 2  # Need at least something to mask

    if len(clean) < min_length:
        # Too short to meaningfully mask
        return clean

    start = clean[:visible_chars]
    end = clean[-visible_chars:]

    return f"{start}..{end}"
