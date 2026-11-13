"""5+1 transparent PNG card renderer with adaptive cell font fitting and theme support."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .schema import THEMES, CardTheme, resolve_pos_palette

CANVAS_W = 1920
CANVAS_H = 1080
CARD_W = 1760
CARD_H = 230
CARD_X = (CANVAS_W - CARD_W) // 2  # 80
ACTIVE_Y = 535
BUFFER_Y = 785
STRIP_X = 75
STRIP_W = 1770
STRIP_H = 240
ACTIVE_STRIP_Y0 = 530
BUFFER_STRIP_Y0 = 780

JP_BOLD_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/NotoSansJP-VF.ttf",
    "C:/Windows/Fonts/msgothic.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Osaka.ttf",
    # Linux (Noto CJK / Source Han / system Japanese)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansJP-Bold.otf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
)
JP_REG_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/NotoSansJP-VF.ttf",
    "C:/Windows/Fonts/msgothic.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Osaka.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansJP-Regular.otf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
)
CN_REG_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)
CN_BOLD_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Bold.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)

_FONT_EXTENSIONS = (".ttf", ".ttc", ".otf")


@lru_cache(maxsize=None)
def _list_system_font_files() -> tuple[str, ...]:
    """Scan standard OS font directories once so fallback matching stays O(1) across calls."""
    roots = [
        "C:/Windows/Fonts",
        os.path.expandvars(r"%LOCALAPPDATA%/Microsoft/Windows/Fonts"),
        "/System/Library/Fonts",
        "/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.local/share/fonts"),
        os.path.expanduser("~/.fonts"),
    ]
    found: list[str] = []
    for root in roots:
        if not root or "%" in root or not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if name.lower().endswith(_FONT_EXTENSIONS):
                    found.append(os.path.join(dirpath, name))
    return tuple(found)


@lru_cache(maxsize=16)
def _fc_match_font(pattern: str) -> str | None:
    """Resolve a font via fontconfig (`fc-match`) on Linux/macOS if available."""
    fc_bin = shutil.which("fc-match")
    if not fc_bin or not pattern:
        return None
    try:
        res = subprocess.run([fc_bin, "-f", "%{file}", pattern], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            path = res.stdout.strip()
            if path and os.path.exists(path):
                return path
    except Exception:
        pass
    return None


def find_font(
    candidates: tuple[str, ...],
    *,
    override: str | None = None,
    env_vars: tuple[str, ...] = (),
    fc_pattern: str | None = None,
    name_hints: tuple[str, ...] = (),
    role: str = "font",
) -> str:
    """
    Resolve a usable TrueType/OpenType font across Windows, macOS, and Linux.
    Priority: explicit override -> env vars -> known candidate paths -> fc-match -> system font scan.
    """
    if override:
        if os.path.exists(override):
            return override
        raise FileNotFoundError(f"Requested {role} font path does not exist: {override}")

    for var in env_vars:
        env_path = os.environ.get(var, "").strip()
        if env_path:
            if os.path.exists(env_path):
                return env_path
            raise FileNotFoundError(f"Environment variable {var} points to missing font: {env_path}")

    for path in candidates:
        if os.path.exists(path):
            return path

    if fc_pattern:
        matched = _fc_match_font(fc_pattern)
        if matched:
            return matched

    if name_hints:
        files = _list_system_font_files()
        for hint in name_hints:
            h_low = hint.lower()
            for fpath in files:
                if h_low in os.path.basename(fpath).lower():
                    return fpath

    raise FileNotFoundError(
        f"No usable {role} font found. Checked {candidates[:3]}... "
        "Install Noto Sans CJK (e.g. `sudo apt install fonts-noto-cjk` on Linux) or pass "
        "`--font-jp-bold/--font-jp-reg/--font-cn-bold/--font-cn-reg` (or set `JP_LYRICS_KIT_FONT_*`)."
    )


def _pick_font(candidates: tuple[str, ...], override: str | None = None) -> str:
    return find_font(candidates, override=override)


@dataclass
class FontPack:
    """Loaded font paths used to instantiate scaled TrueType fonts on demand."""

    jp_bold: str
    jp_reg: str
    cn_reg: str
    cn_bold: str

    @classmethod
    def resolve(
        cls,
        jp_bold: str | None = None,
        jp_reg: str | None = None,
        cn_reg: str | None = None,
        cn_bold: str | None = None,
    ) -> "FontPack":
        return cls(
            jp_bold=find_font(
                JP_BOLD_CANDIDATES,
                override=jp_bold,
                env_vars=("JP_LYRICS_KIT_FONT_JP_BOLD", "JP_LYRICS_KIT_FONT_JP"),
                fc_pattern=":lang=ja:weight=bold",
                name_hints=("meiryob", "yugothb", "notosanscjk-bold", "notosansjp-bold", "hiragino", "noto"),
                role="Japanese bold",
            ),
            jp_reg=find_font(
                JP_REG_CANDIDATES,
                override=jp_reg,
                env_vars=("JP_LYRICS_KIT_FONT_JP_REG", "JP_LYRICS_KIT_FONT_JP"),
                fc_pattern=":lang=ja",
                name_hints=("meiryo", "yugoth", "notosanscjk-regular", "notosansjp", "hiragino", "noto"),
                role="Japanese regular",
            ),
            cn_reg=find_font(
                CN_REG_CANDIDATES,
                override=cn_reg,
                env_vars=("JP_LYRICS_KIT_FONT_CN_REG", "JP_LYRICS_KIT_FONT_CN"),
                fc_pattern=":lang=zh-cn",
                name_hints=("msyh", "pingfang", "notosanscjk-regular", "notosanssc", "wqy", "noto"),
                role="Chinese regular",
            ),
            cn_bold=find_font(
                CN_BOLD_CANDIDATES,
                override=cn_bold,
                env_vars=("JP_LYRICS_KIT_FONT_CN_BOLD", "JP_LYRICS_KIT_FONT_CN"),
                fc_pattern=":lang=zh-cn:weight=bold",
                name_hints=("msyhbd", "msyh", "pingfang", "notosanscjk-bold", "notosanssc-bold", "wqy", "noto"),
                role="Chinese bold",
            ),
        )


_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def _fmt_time(sec: float) -> str:
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    base_size: int,
    max_width: float,
    min_size: int = 10,
) -> tuple[ImageFont.FreeTypeFont, str, float, float]:
    """
    Shrink font size dynamically if `text` exceeds `max_width`,
    preventing cell overflow on dense 10+ token Japanese lines.
    """
    size = base_size
    while size >= min_size:
        fnt = _get_font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        if tw <= max_width:
            return fnt, text, tw, th
        size -= 1

    fnt = _get_font(font_path, min_size)
    trimmed = text
    while len(trimmed) > 1:
        candidate = trimmed + "…"
        bbox = draw.textbbox((0, 0), candidate, font=fnt)
        if bbox[2] - bbox[0] <= max_width:
            return fnt, candidate, bbox[2] - bbox[0], bbox[3] - bbox[1]
        trimmed = trimmed[:-1]
    bbox = draw.textbbox((0, 0), trimmed, font=fnt)
    return fnt, trimmed, bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_single_card(
    sent: dict[str, Any],
    pos_palette: dict[str, tuple[int, int, int, int]],
    slot_type: str = "active",
    theme: CardTheme | str = "kalk_crimson",
    fonts: FontPack | None = None,
    show_timestamps: bool = True,
) -> Image.Image:
    """Render one 1920x1080 transparent PNG containing either Slot A or Slot B card."""
    if isinstance(theme, str):
        theme = THEMES.get(theme, THEMES["classic_blue"])
    fonts = fonts or FontPack.resolve()

    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if slot_type == "active":
        card_y = ACTIVE_Y
        bg_color = theme.active_bg
        border_color = theme.active_border
        badge_bg = theme.active_badge_bg
        badge_text = theme.active_badge_text
    else:
        card_y = BUFFER_Y
        bg_color = theme.buffer_bg
        border_color = theme.buffer_border
        badge_bg = theme.buffer_badge_bg
        badge_text = theme.buffer_badge_text

    draw.rounded_rectangle(
        [CARD_X, card_y, CARD_X + CARD_W, card_y + CARD_H],
        radius=16,
        fill=bg_color,
        outline=border_color,
        width=2,
    )

    f_badge = _get_font(fonts.cn_bold, 17)
    f_time = _get_font(fonts.cn_reg, 16)
    f_th = _get_font(fonts.cn_reg, 18)

    badge_label = f"句 {sent['id']}" if slot_type == "active" else f"句 {sent['id']} (下句预读)"
    bb_badge = draw.textbbox((0, 0), badge_label, font=f_badge)
    badge_w = max(86 if slot_type == "active" else 155, (bb_badge[2] - bb_badge[0]) + 24)
    draw.rounded_rectangle(
        [CARD_X + 16, card_y + 11, CARD_X + 16 + badge_w, card_y + 36],
        radius=6,
        fill=badge_bg,
    )
    draw.text((CARD_X + 28, card_y + 13), badge_label, font=f_badge, fill=badge_text)

    if show_timestamps:
        time_str = (
            f"当前唱段 [{_fmt_time(float(sent['start']))} ~ {_fmt_time(float(sent['end']))}]"
            if slot_type == "active"
            else f"即将接力 [{_fmt_time(float(sent['start']))}]"
        )
        tb = draw.textbbox((0, 0), time_str, font=f_time)
        draw.text(
            (CARD_X + CARD_W - 20 - (tb[2] - tb[0]), card_y + 14),
            time_str,
            font=f_time,
            fill=theme.muted_color,
        )

    table_x = CARD_X + 16
    table_y = card_y + 44
    table_w = CARD_W - 32
    th_w = 80
    cells_w = table_w - th_w

    tokens = sent["tokens"]
    n = max(1, len(tokens))
    col_w = cells_w / n

    row_specs = [
        ("发音", "romaji", 24, fonts.jp_reg, 18, theme.romaji_color),
        ("假名", "kana", 25, fonts.jp_reg, 20, theme.kana_color),
        ("单词", "word", 32, fonts.jp_bold, 26, None),
        ("语法", "pos", 25, fonts.cn_reg, 16, theme.pos_color),
        ("字义", "gloss", 25, fonts.cn_reg, 19, theme.gloss_color),
    ]

    cur_y = table_y
    for label, _, rh, _, _, _ in row_specs:
        draw.rectangle(
            [table_x, cur_y, table_x + th_w, cur_y + rh],
            fill=theme.header_bg,
            outline=theme.grid_border,
            width=1,
        )
        bb = draw.textbbox((0, 0), label, font=f_th)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text(
            (table_x + (th_w - tw) / 2, cur_y + (rh - th) / 2 - 2),
            label,
            font=f_th,
            fill=theme.muted_color,
        )
        cur_y += rh

    max_cell_text_w = max(24.0, col_w - 10.0)
    for col_idx, tok in enumerate(tokens):
        col_x = table_x + th_w + col_idx * col_w
        cur_y = table_y
        word_clr = pos_palette.get(tok.get("type", "noun"), theme.gloss_color)

        for _, key, rh, font_path, base_sz, static_clr in row_specs:
            draw.rectangle(
                [col_x, cur_y, col_x + col_w, cur_y + rh],
                fill=theme.cell_bg,
                outline=theme.grid_border,
                width=1,
            )
            txt = str(tok.get(key, ""))
            clr = word_clr if static_clr is None else static_clr
            fnt, fitted_txt, tw, th = _fit_text(draw, txt, font_path, base_sz, max_cell_text_w, min_size=10)
            draw.text(
                (col_x + (col_w - tw) / 2, cur_y + (rh - th) / 2 - 2),
                fitted_txt,
                font=fnt,
                fill=clr,
            )
            cur_y += rh

    trans_y = card_y + CARD_H - 44
    draw.line([CARD_X + 16, trans_y, CARD_X + CARD_W - 16, trans_y], fill=theme.grid_border, width=1)
    draw.text((CARD_X + 24, trans_y + 8), "文学意译：", font=f_th, fill=theme.romaji_color)

    trans_max_w = CARD_W - 144
    f_trans, fitted_trans, _, _ = _fit_text(draw, str(sent.get("trans", "")), fonts.cn_reg, 23, trans_max_w, min_size=14)
    draw.text((CARD_X + 120, trans_y + 6), fitted_trans, font=f_trans, fill=theme.trans_color)

    return img


def batch_render_cards(
    song_data: dict[str, Any],
    output_dir: str,
    theme: CardTheme | str = "kalk_crimson",
    show_timestamps: bool = True,
    fonts: FontPack | None = None,
) -> dict[str, dict[int, str]]:
    """Batch render active and buffer 1080p transparent PNGs for every sentence."""
    os.makedirs(output_dir, exist_ok=True)
    pos_palette = resolve_pos_palette(song_data)
    fonts = fonts or FontPack.resolve()

    active_paths: dict[int, str] = {}
    buffer_paths: dict[int, str] = {}

    for sent in song_data["sentences"]:
        sid = int(sent["id"])
        pa = os.path.join(output_dir, f"card_{sid:02d}_active.png")
        pb = os.path.join(output_dir, f"card_{sid:02d}_buffer.png")
        render_single_card(sent, pos_palette, "active", theme, fonts, show_timestamps).save(pa)
        render_single_card(sent, pos_palette, "buffer", theme, fonts, show_timestamps).save(pb)
        active_paths[sid] = pa
        buffer_paths[sid] = pb

    return {"active": active_paths, "buffer": buffer_paths}


def render_card_strips(
    song_data: dict[str, Any],
    theme: CardTheme | str = "kalk_crimson",
    show_timestamps: bool = True,
    fonts: FontPack | None = None,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """
    Render cropped BGRA card strips in memory (`240x1770`) for fast 60fps overlay
    without requiring intermediate disk PNGs.
    """
    pos_palette = resolve_pos_palette(song_data)
    fonts = fonts or FontPack.resolve()

    active_strips: dict[int, np.ndarray] = {}
    buffer_strips: dict[int, np.ndarray] = {}

    for sent in song_data["sentences"]:
        sid = int(sent["id"])
        img_a = np.array(render_single_card(sent, pos_palette, "active", theme, fonts, show_timestamps))
        img_b = np.array(render_single_card(sent, pos_palette, "buffer", theme, fonts, show_timestamps))
        bgra_a = cv2.cvtColor(img_a, cv2.COLOR_RGBA2BGRA)
        bgra_b = cv2.cvtColor(img_b, cv2.COLOR_RGBA2BGRA)
        active_strips[sid] = bgra_a[ACTIVE_STRIP_Y0 : ACTIVE_STRIP_Y0 + STRIP_H, STRIP_X : STRIP_X + STRIP_W].copy()
        buffer_strips[sid] = bgra_b[BUFFER_STRIP_Y0 : BUFFER_STRIP_Y0 + STRIP_H, STRIP_X : STRIP_X + STRIP_W].copy()

    return active_strips, buffer_strips
