"""16:9 and 4:3 museum-grade video cover generator with sample 5+1 breakdown."""

from __future__ import annotations

import os
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .card_renderer import (
    CN_BOLD_CANDIDATES,
    CN_REG_CANDIDATES,
    JP_BOLD_CANDIDATES,
    JP_REG_CANDIDATES,
    FontPack,
    _fit_text,
    find_font,
)

SERIF_CN_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/NotoSerifSC-VF.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    # macOS
    "/System/Library/Fonts/Songti.ttc",
    "/System/Library/Fonts/STSong.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Bold.ttc",
) + CN_BOLD_CANDIDATES
MINCHO_R_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/yumin.ttf",
    # macOS
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc",
) + JP_REG_CANDIDATES
MINCHO_DB_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/yumindb.ttf",
    "C:/Windows/Fonts/yumin.ttf",
    # macOS
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Bold.ttc",
) + JP_BOLD_CANDIDATES
SERIF_EN_CANDIDATES = (
    # Windows
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/arial.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
) + JP_REG_CANDIDATES + CN_REG_CANDIDATES

COVER_STYLES = {
    "dark_museum": {
        "bg": (16, 16, 18, 255),
        "border": (195, 172, 120, 85),
        "ivory": (242, 238, 230, 255),
        "accent": (205, 178, 122, 255),
        "muted": (155, 152, 148, 255),
        "tag_bar": (185, 48, 68, 255),
    },
    "crimson_gold": {
        "bg": (28, 10, 16, 255),
        "border": (212, 175, 55, 110),
        "ivory": (250, 244, 236, 255),
        "accent": (228, 188, 110, 255),
        "muted": (190, 165, 170, 255),
        "tag_bar": (225, 29, 72, 255),
    },
    "classic_slate": {
        "bg": (15, 23, 42, 255),
        "border": (148, 163, 184, 95),
        "ivory": (248, 250, 252, 255),
        "accent": (96, 165, 250, 255),
        "muted": (148, 163, 184, 255),
        "tag_bar": (37, 99, 235, 255),
    },
}


def _feather_cover_art(art_path: str, target_h: int) -> Image.Image:
    src = Image.open(art_path).convert("RGB")
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    src = src.crop((left, top, left + side, top + side))

    arr = np.array(src, dtype=np.float32)
    yy, xx = np.mgrid[0:side, 0:side]
    cx, cy = side * 0.5, side * 0.5
    dist = np.sqrt(((xx - cx) / (side * 0.46)) ** 2 + ((yy - cy) / (side * 0.46)) ** 2)
    alpha = np.clip(1.0 - np.clip((dist - 0.70) / 0.30, 0.0, 1.0) ** 1.6, 0.0, 1.0)

    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(arr, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA").resize((target_h, target_h), Image.Resampling.LANCZOS)


def _pick_highlight_sentence(song_data: dict[str, Any], sentence_id: int | None) -> dict[str, Any]:
    sentences = song_data["sentences"]
    if sentence_id is not None:
        for s in sentences:
            if int(s["id"]) == sentence_id:
                return s
    # Pick a clean 3..6 token sentence for uncluttered cover typography
    for s in sentences:
        if 3 <= len(s["tokens"]) <= 6:
            return s
    return sentences[0]


def _render_cover_canvas(
    width: int,
    height: int,
    song_data: dict[str, Any],
    art_path: str | None,
    sent: dict[str, Any],
    palette: dict[str, tuple[int, int, int, int]],
    fonts: FontPack | None = None,
) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), palette["bg"])
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 2.0, (height, width, 1)).astype(np.int16)
    base_rgb = np.clip(np.array(canvas)[:, :, :3].astype(np.int16) + noise, 0, 255).astype(np.uint8)
    canvas = Image.fromarray(base_rgb, mode="RGB").convert("RGBA")

    has_art = bool(art_path and os.path.exists(art_path))
    if has_art:
        art_sz = int(height * (0.85 if width >= 1800 else 0.70))
        art_img = _feather_cover_art(art_path, art_sz)  # type: ignore[arg-type]
        art_cx = int(width * (0.28 if width >= 1800 else 0.26))
        canvas.alpha_composite(art_img, (art_cx - art_sz // 2, height // 2 - art_sz // 2))
        rx = int(width * (0.54 if width >= 1800 else 0.48))
    else:
        rx = int(width * 0.08)

    right_edge = width - 80
    avail_w = max(400, right_edge - rx)

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([44, 42, width - 44, height - 42], outline=palette["border"], width=1)

    if fonts is not None:
        fnt_serif_cn = fonts.cn_bold
        fnt_mincho_r = fonts.jp_reg
        fnt_mincho_db = fonts.jp_bold
        fnt_en = find_font(
            SERIF_EN_CANDIDATES,
            fc_pattern=":lang=en:family=serif",
            name_hints=("georgia", "dejavuserif", "liberationserif", "notoserif"),
            role="cover English serif",
        )
    else:
        fnt_serif_cn = find_font(
            SERIF_CN_CANDIDATES,
            env_vars=("JP_LYRICS_KIT_FONT_CN_BOLD", "JP_LYRICS_KIT_FONT_CN"),
            fc_pattern=":lang=zh-cn:family=serif",
            name_hints=("notoserifsc", "notoserifcjk", "songti", "simsun", "msyhbd", "notosanscjk"),
            role="cover Chinese serif",
        )
        fnt_mincho_r = find_font(
            MINCHO_R_CANDIDATES,
            env_vars=("JP_LYRICS_KIT_FONT_JP_REG", "JP_LYRICS_KIT_FONT_JP"),
            fc_pattern=":lang=ja:family=serif",
            name_hints=("yumin", "hiragino", "notoserifcjk", "meiryo", "notosanscjk"),
            role="cover Japanese regular",
        )
        fnt_mincho_db = find_font(
            MINCHO_DB_CANDIDATES,
            env_vars=("JP_LYRICS_KIT_FONT_JP_BOLD", "JP_LYRICS_KIT_FONT_JP"),
            fc_pattern=":lang=ja:family=serif:weight=bold",
            name_hints=("yumindb", "yumin", "hiragino", "notoserifcjk", "meiryob", "notosanscjk"),
            role="cover Japanese bold",
        )
        fnt_en = find_font(
            SERIF_EN_CANDIDATES,
            fc_pattern=":lang=en:family=serif",
            name_hints=("georgia", "dejavuserif", "liberationserif", "notoserif", "meiryo", "noto"),
            role="cover English serif",
        )

    meta = song_data["meta"]
    title = str(meta.get("title", ""))
    artist = str(meta.get("artist", ""))
    album = str(meta.get("album", ""))

    f_en_lbl = ImageFont.truetype(fnt_en, 18)
    draw.text((rx + 2, 165), f"{artist.upper()}  //  5+1 MORPHEME STUDY", font=f_en_lbl, fill=palette["accent"])

    f_title, fitted_title, tw_title, th_title = _fit_text(draw, title, fnt_serif_cn, 118, avail_w * 0.62, min_size=44)
    draw.text((rx, 205), fitted_title, font=f_title, fill=palette["ivory"])

    meta_x = min(rx + int(tw_title) + 28, right_edge - 240)
    f_artist = ImageFont.truetype(fnt_serif_cn, 30)
    f_album = ImageFont.truetype(fnt_mincho_r, 20)
    if meta_x > rx + 40:
        draw.text((meta_x, 228), artist, font=f_artist, fill=palette["ivory"])
        if album:
            draw.text((meta_x, 272), album[:24], font=f_album, fill=palette["muted"])

    div_y = max(395, 225 + int(th_title) + 32)
    draw.line([(rx, div_y), (right_edge, div_y)], fill=palette["border"], width=1)

    tokens = sent["tokens"][:5]
    n_tok = max(1, len(tokens))
    col_w = avail_w // n_tok
    table_y = div_y + 34
    row_ys = [0, 28, 60, 108, 138]

    for c_i, tok in enumerate(tokens):
        cx_col = rx + c_i * col_w + col_w // 2
        if c_i > 0:
            draw.line([(rx + c_i * col_w, table_y + 4), (rx + c_i * col_w, table_y + 165)], fill=(255, 255, 255, 24), width=1)
        specs = [
            (row_ys[0], str(tok["romaji"]), fnt_en, 15, palette["muted"]),
            (row_ys[1], str(tok["kana"]), fnt_mincho_r, 18, palette["ivory"]),
            (row_ys[2], str(tok["word"]), fnt_mincho_db, 28, palette["accent"] if c_i == n_tok - 1 else palette["ivory"]),
            (row_ys[3], str(tok["pos"]), fnt_serif_cn, 14, palette["muted"]),
            (row_ys[4], str(tok["gloss"]), fnt_serif_cn, 17, palette["ivory"]),
        ]
        for r_y, txt, fpath, b_sz, clr in specs:
            fnt, f_txt, tw, _ = _fit_text(draw, txt, fpath, b_sz, max(40.0, col_w - 14.0), min_size=10)
            draw.text((cx_col - tw / 2, table_y + r_y), f_txt, font=fnt, fill=clr)

    bot_y = table_y + 195
    draw.line([(rx, bot_y), (right_edge, bot_y)], fill=palette["border"], width=1)
    f_trans, f_tr_txt, _, _ = _fit_text(draw, str(sent.get("trans", "")), fnt_serif_cn, 21, avail_w, min_size=14)
    draw.text((rx, bot_y + 24), f_tr_txt, font=f_trans, fill=palette["ivory"])

    foot_y = bot_y + 108
    draw.rectangle([rx, foot_y, rx + 8, foot_y + 24], fill=palette["tag_bar"])
    f_tag = ImageFont.truetype(fnt_serif_cn, 18)
    draw.text((rx + 22, foot_y), "日语歌词「5+1」形态素精解  ｜  双卡无缝接力  ｜  中日对照", font=f_tag, fill=palette["accent"])
    return canvas


def generate_covers(
    song_data: dict[str, Any],
    out_16x9: str,
    out_4x3: str | None = None,
    art_path: str | None = None,
    sentence_id: int | None = None,
    style: str = "dark_museum",
    fonts: FontPack | None = None,
) -> list[str]:
    """Generate 16:9 (1920x1080) and optional 4:3 (1440x1080) cover PNGs."""
    palette = COVER_STYLES.get(style, COVER_STYLES["dark_museum"])
    sent = _pick_highlight_sentence(song_data, sentence_id)
    outputs: list[str] = []

    for path, (w, h) in [(out_16x9, (1920, 1080)), (out_4x3, (1440, 1080))]:
        if not path:
            continue
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        img = _render_cover_canvas(w, h, song_data, art_path, sent, palette, fonts=fonts)
        img.convert("RGB").save(path, quality=98)
        outputs.append(path)

    return outputs
