"""Reusable 5+1 Japanese-Chinese dual-buffer lyrics study video toolchain."""

from .schema import (
    DEFAULT_POS_COLORS,
    THEMES,
    CardTheme,
    load_song_data,
    probe_audio_duration,
    save_song_data,
    validate_song_data,
)
from .timeline import TimelineSegment, build_timeline, card_visibility_at

__all__ = [
    "DEFAULT_POS_COLORS",
    "THEMES",
    "CardTheme",
    "TimelineSegment",
    "build_timeline",
    "card_visibility_at",
    "load_song_data",
    "probe_audio_duration",
    "save_song_data",
    "validate_song_data",
]
__version__ = "0.1.0"
