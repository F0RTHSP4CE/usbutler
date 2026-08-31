"""Utility functions for the application."""

from .masking import mask_identifier
from .time import utcnow

__all__ = ["mask_identifier", "utcnow"]
