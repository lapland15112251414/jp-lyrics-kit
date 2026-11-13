"""Standard song.json schema, validation, audio duration probing, and card themes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

DEFAULT_POS_COLORS: dict[str, dict[str, str]] = {
    "noun": {"hex": "#059669", "name": "名词/代词", "bg": "rgba(5,150,105,0.08)"},
    "verb": {"hex": "#0284c7", "name": "动词活用", "bg": "rgba(2,132,199,0.08)"},
    "particle": {"hex": "#e11d48", "name": "助词情态", "bg": "rgba(225,29,72,0.08)"},
    "adj": {"hex": "#d97706", "name": "形容词", "bg": "rgba(217,119,6,0.08)"},
    "adv": {"hex": "#db2777", "name": "副词修饰", "bg": "rgba(219,39,119,0.08)"},
    "prenoun": {"hex": "#ca8a04", "name": "连体词", "bg": "rgba(202,138,4,0.08)"},
    "aux": {"hex": "#9333ea", "name": "助动词/感叹", "bg": "rgba(147,51,234,0.08)"},
}

REQUIRED_TOKEN_FIELDS = ("romaji", "kana", "word", "pos", "gloss", "type")


@dataclass(frozen=True)
class CardTheme:
    """Visual styling tokens for active/buffer 5+1 study cards."""

    name: str
    active_bg: tuple[int, int, int, int]
    active_border: tuple[int, int, int, int]
    active_badge_bg: tuple[int, int, int, int]
    active_badge_text: tuple[int, int, int, int]
    buffer_bg: tuple[int, int, int, int]
    buffer_border: tuple[int, int, int, int]
    buffer_badge_bg: tuple[int, int, int, int]
    buffer_badge_text: tuple[int, int, int, int]
    cell_bg: tuple[int, int, int, int]
    header_bg: tuple[int, int, int, int]
    grid_border: tuple[int, int, int, int]
    romaji_color: tuple[int, int, int, int]
    kana_color: tuple[int, int, int, int]
    pos_color: tuple[int, int, int, int]
    gloss_color: tuple[int, int, int, int]
    trans_color: tuple[int, int, int, int]
    muted_color: tuple[int, int, int, int]


THEMES: dict[str, CardTheme] = {
    "classic_blue": CardTheme(
        name="classic_blue",
        active_bg=(255, 255, 255, 248),
        active_border=(203, 213, 225, 255),
        active_badge_bg=(37, 99, 235, 255),
        active_badge_text=(255, 255, 255, 255),
        buffer_bg=(248, 250, 252, 235),
        buffer_border=(203, 213, 225, 200),
        buffer_badge_bg=(100, 116, 139, 255),
        buffer_badge_text=(255, 255, 255, 255),
        cell_bg=(255, 255, 255, 255),
        header_bg=(241, 245, 249, 255),
        grid_border=(226, 232, 240, 255),
        romaji_color=(148, 163, 184, 255),
        kana_color=(71, 85, 105, 255),
        pos_color=(100, 116, 139, 255),
        gloss_color=(30, 41, 59, 255),
        trans_color=(30, 41, 59, 255),
        muted_color=(100, 116, 139, 255),
    ),
    "kalk_crimson": CardTheme(
        name="kalk_crimson",
        active_bg=(255, 255, 255, 248),
        active_border=(212, 175, 55, 255),
        active_badge_bg=(159, 18, 57, 255),
        active_badge_text=(255, 255, 255, 255),
        buffer_bg=(248, 250, 252, 235),
        buffer_border=(203, 213, 225, 200),
        buffer_badge_bg=(100, 116, 139, 255),
        buffer_badge_text=(255, 255, 255, 255),
        cell_bg=(255, 255, 255, 255),
        header_bg=(241, 245, 249, 255),
        grid_border=(226, 232, 240, 255),
        romaji_color=(148, 163, 184, 255),
        kana_color=(71, 85, 105, 255),
        pos_color=(100, 116, 139, 255),
        gloss_color=(30, 41, 59, 255),
        trans_color=(30, 41, 59, 255),
        muted_color=(100, 116, 139, 255),
    ),
    "dark_museum": CardTheme(
        name="dark_museum",
        active_bg=(18, 18, 24, 242),
        active_border=(205, 178, 122, 235),
        active_badge_bg=(185, 48, 68, 255),
        active_badge_text=(255, 255, 255, 255),
        buffer_bg=(24, 24, 32, 224),
        buffer_border=(100, 116, 139, 170),
        buffer_badge_bg=(71, 85, 105, 255),
        buffer_badge_text=(241, 245, 249, 255),
        cell_bg=(26, 26, 36, 240),
        header_bg=(34, 34, 46, 255),
        grid_border=(58, 62, 78, 255),
        romaji_color=(165, 168, 182, 255),
        kana_color=(212, 214, 224, 255),
        pos_color=(156, 163, 175, 255),
        gloss_color=(236, 234, 228, 255),
        trans_color=(244, 240, 232, 255),
        muted_color=(168, 164, 156, 255),
    ),
}


def hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Convert '#rrggbb' or '#rgb' into an RGBA tuple."""
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex color: {hex_str!r}")
    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return (r, g, b, alpha)


def resolve_pos_palette(song_data: dict[str, Any]) -> dict[str, tuple[int, int, int, int]]:
    """Build POS RGBA palette from song_data['colors'] merged over defaults."""
    palette = {k: hex_to_rgba(v["hex"]) for k, v in DEFAULT_POS_COLORS.items()}
    custom = song_data.get("colors") or {}
    for k, entry in custom.items():
        if isinstance(entry, dict) and isinstance(entry.get("hex"), str):
            palette[k] = hex_to_rgba(entry["hex"])
        elif isinstance(entry, str) and entry.startswith("#"):
            palette[k] = hex_to_rgba(entry)
    return palette


def ensure_binary(name: str) -> str:
    """Locate an external CLI binary (e.g., `ffmpeg`, `ffprobe`) or raise an actionable error."""
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise RuntimeError(
        f"Required binary '{name}' was not found on PATH. "
        "Install FFmpeg first — Windows: `winget install Gyan.FFmpeg`, "
        "macOS: `brew install ffmpeg`, Ubuntu/Debian: `sudo apt install ffmpeg`."
    )


def probe_audio_duration(audio_path: str) -> float:
    """Return media duration in seconds using ffprobe, or mutagen as fallback."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())

    try:
        import mutagen

        audio = mutagen.File(audio_path)
        if audio is not None and getattr(audio, "info", None) is not None:
            return float(audio.info.length)
    except Exception:
        pass

    if not ffprobe_bin:
        ensure_binary("ffprobe")
    raise RuntimeError(f"Unable to determine duration for audio: {audio_path}")


def normalize_song_data(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure top-level keys exist with consistent defaults without mutating caller data."""
    normalized = dict(data)
    meta = dict(normalized.get("meta") or {})
    meta.setdefault("title", "Untitled")
    meta.setdefault("artist", "Unknown")
    meta.setdefault("album", "")
    meta.setdefault("style", "5+1 Dual-Buffer Morpheme Breakdown")
    normalized["meta"] = meta

    colors = dict(DEFAULT_POS_COLORS)
    if isinstance(normalized.get("colors"), dict):
        for key, val in normalized["colors"].items():
            if isinstance(val, dict):
                merged = dict(colors.get(key, {}))
                merged.update(val)
                colors[key] = merged
    normalized["colors"] = colors

    sentences = []
    for idx, sent in enumerate(normalized.get("sentences") or [], start=1):
        s_copy = dict(sent)
        s_copy.setdefault("id", idx)
        sentences.append(s_copy)
    normalized["sentences"] = sentences
    return normalized


def load_song_data(path: str) -> dict[str, Any]:
    """Load and normalize a song JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_song_data(raw)


def save_song_data(data: dict[str, Any], path: str) -> None:
    """Save formatted song JSON with UTF-8 encoding."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def validate_song_data(data: dict[str, Any], strict: bool = False) -> tuple[list[str], list[str]]:
    """
    Validate song_data against the 5+1 schema.
    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("Missing or invalid 'meta' object.")
    else:
        for req in ("title", "artist", "duration"):
            if req not in meta:
                errors.append(f"meta.{req} is required.")
        dur = meta.get("duration")
        if dur is not None and (not isinstance(dur, (int, float)) or dur <= 0):
            errors.append(f"meta.duration must be > 0, got {dur!r}.")

    sentences = data.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        errors.append("'sentences' must be a non-empty list.")
        return errors, warnings

    valid_types = set((data.get("colors") or DEFAULT_POS_COLORS).keys()) | set(DEFAULT_POS_COLORS.keys())
    prev_start = -1.0
    prev_end = 0.0
    seen_ids: set[int] = set()

    for idx, sent in enumerate(sentences):
        prefix = f"sentences[{idx}]"
        if not isinstance(sent, dict):
            errors.append(f"{prefix} must be an object.")
            continue

        sid = sent.get("id")
        if not isinstance(sid, int) or sid <= 0:
            errors.append(f"{prefix}.id must be a positive integer, got {sid!r}.")
        elif sid in seen_ids:
            errors.append(f"Duplicate sentence id: {sid}.")
        else:
            seen_ids.add(sid)

        start = sent.get("start")
        end = sent.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"{prefix} (id={sid}) must have numeric 'start' and 'end'.")
        else:
            if start < 0:
                errors.append(f"{prefix} (id={sid}) start < 0: {start}.")
            if end < start:
                errors.append(f"{prefix} (id={sid}) end ({end}) < start ({start}).")
            if start < prev_start:
                errors.append(f"{prefix} (id={sid}) start ({start}) < previous start ({prev_start}).")
            elif start < prev_end - 0.05:
                warnings.append(f"{prefix} (id={sid}) start ({start:.2f}s) overlaps previous end ({prev_end:.2f}s).")
            if isinstance(meta, dict) and isinstance(meta.get("duration"), (int, float)) and end > meta["duration"] + 0.5:
                warnings.append(f"{prefix} (id={sid}) end ({end:.2f}s) exceeds meta.duration ({meta['duration']:.2f}s).")
            prev_start = float(start)
            prev_end = float(end)

        trans = sent.get("trans")
        if not isinstance(trans, str) or not trans.strip():
            msg = f"{prefix} (id={sid}) has empty 'trans'."
            (errors if strict else warnings).append(msg)
        elif "[待意译]" in trans:
            (errors if strict else warnings).append(f"{prefix} (id={sid}) translation is still a draft placeholder.")

        tokens = sent.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            errors.append(f"{prefix} (id={sid}) must have a non-empty 'tokens' list.")
            continue

        if len(tokens) > 12:
            warnings.append(f"{prefix} (id={sid}) has {len(tokens)} tokens; auto font-shrinking will apply.")

        for t_idx, tok in enumerate(tokens):
            t_pre = f"{prefix}.tokens[{t_idx}]"
            if not isinstance(tok, dict):
                errors.append(f"{t_pre} must be an object.")
                continue
            for field in REQUIRED_TOKEN_FIELDS:
                val = tok.get(field)
                if not isinstance(val, str) or not val.strip():
                    errors.append(f"{t_pre}.{field} must be a non-empty string.")
            tok_type = tok.get("type")
            if tok_type not in valid_types:
                errors.append(f"{t_pre}.type={tok_type!r} is not in {sorted(valid_types)}.")
            if tok.get("needs_review") or "[待释义]" in str(tok.get("gloss", "")):
                msg = f"{t_pre} ({tok.get('word', '')}) still flagged for review."
                (errors if strict else warnings).append(msg)

    return errors, warnings
