"""Offline Japanese morphological tokenization and timestamp drafting engine."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import jaconv
import pykakasi
import sudachipy

from .schema import DEFAULT_POS_COLORS, normalize_song_data, probe_audio_duration

LRC_LINE_RE = re.compile(r"^((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)\s*(.*)$")
LRC_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
RUBY_RE = re.compile(r"([\u4e00-\u9fff々〆ヵヶ]+)[（(]([ぁ-んァ-ヶー]+)[）)]")
KANJI_RE = re.compile(r"[\u4e00-\u9fff々]")
HISTORICAL_KANA_RE = re.compile(r"[ゐゑヰヱづぢ]|([あ-ん])ふ(?![あ-ん])")
META_LINE_RE = re.compile(
    r"^(作[词詞]|作[曲編]|編曲|编曲|演唱|歌|lyrics|music|arranger)\s*[:：]",
    re.IGNORECASE,
)


@dataclass
class LyricLine:
    """Intermediate parsed lyric line before tokenization."""

    start: float | None
    end: float | None
    text: str
    trans: str = ""


def _parse_lrc_timestamp(mm: str, ss: str, frac: str | None) -> float:
    sec = int(mm) * 60.0 + int(ss)
    if frac:
        sec += int(frac) / (10 ** len(frac))
    return round(sec, 3)


def parse_lrc(lrc_path: str) -> list[LyricLine]:
    """Parse LRC lines, filtering metadata credits and resolving duplicate timestamps."""
    with open(lrc_path, "r", encoding="utf-8-sig") as f:
        raw_lines = f.read().splitlines()

    items: list[tuple[float, str]] = []
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        m = LRC_LINE_RE.match(line)
        if not m:
            continue
        tags_str, text = m.group(1), m.group(2).strip()
        if not text or META_LINE_RE.match(text):
            continue
        for mm, ss, frac in LRC_TAG_RE.findall(tags_str):
            items.append((_parse_lrc_timestamp(mm, ss, frac), text))

    items.sort(key=lambda x: x[0])
    return [LyricLine(start=ts, end=None, text=txt) for ts, txt in items]


def parse_srt(srt_path: str) -> list[LyricLine]:
    """Parse SRT subtitle blocks into LyricLine objects."""
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read().replace("\r\n", "\n")

    blocks = re.split(r"\n{2,}", content.strip())
    lines: list[LyricLine] = []
    for blk in blocks:
        rows = [r.strip() for r in blk.split("\n") if r.strip()]
        if len(rows) < 2:
            continue
        t_idx = 0 if "-->" in rows[0] else 1
        if t_idx >= len(rows):
            continue
        m = SRT_TIME_RE.search(rows[t_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in m.groups())
        start = round(h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0, 3)
        end = round(h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0, 3)
        text = " ".join(rows[t_idx + 1 :]).strip()
        if text:
            lines.append(LyricLine(start=start, end=end, text=text))
    return lines


def parse_plain_text(txt_path: str) -> list[LyricLine]:
    """Parse plain-text lyric lines (without timestamps)."""
    with open(txt_path, "r", encoding="utf-8-sig") as f:
        raw_lines = f.read().splitlines()
    return [
        LyricLine(start=None, end=None, text=ln.strip())
        for ln in raw_lines
        if ln.strip() and not META_LINE_RE.match(ln.strip())
    ]


def merge_tlyric(lines: list[LyricLine], tlyric_path: str) -> None:
    """Attach translated lines from a NetEase-style tlyric LRC onto matching timestamps."""
    t_lines = parse_lrc(tlyric_path)
    if not t_lines:
        return
    t_pairs = [(tl.start or 0.0, tl.text) for tl in t_lines]
    for line in lines:
        if line.start is None or line.trans:
            continue
        best = min(t_pairs, key=lambda pair: abs(pair[0] - line.start))
        if abs(best[0] - line.start) <= 0.6:
            line.trans = best[1]


def _align_plain_lines_with_whisper(
    lines: list[LyricLine],
    audio_path: str,
    duration: float,
    model_size: str = "base",
) -> None:
    """Use faster-whisper segments to distribute rough start/end timestamps onto plain lines."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments_iter, _ = model.transcribe(audio_path, language="ja", vad_filter=True)
    seg_times = [(round(seg.start, 2), round(seg.end, 2)) for seg in segments_iter]

    if not seg_times:
        _assign_uniform_timestamps(lines, duration)
        return

    n = len(lines)
    m = len(seg_times)
    for idx, line in enumerate(lines):
        if line.start is not None:
            continue
        seg_idx = min(m - 1, int(round(idx * (m - 1) / max(1, n - 1)))) if n > 1 else 0
        s_t, e_t = seg_times[seg_idx]
        line.start = s_t
        line.end = max(s_t + 1.5, e_t)


def _assign_uniform_timestamps(lines: list[LyricLine], duration: float) -> None:
    """Fallback uniform spacing when neither LRC/SRT nor Whisper timestamps are available."""
    n = max(1, len(lines))
    span = max(duration - 10.0, n * 3.0)
    step = span / n
    for idx, line in enumerate(lines):
        if line.start is None:
            line.start = round(5.0 + idx * step, 2)
        if line.end is None:
            line.end = round(line.start + max(1.8, step * 0.85), 2)


def _fill_missing_end_times(lines: list[LyricLine], duration: float) -> None:
    """Fill missing `end` timestamps cleanly from consecutive `start` values."""
    for idx, line in enumerate(lines):
        if line.start is None:
            line.start = round(idx * 4.0, 2)
        if line.end is not None and line.end >= line.start:
            continue
        if idx + 1 < len(lines) and lines[idx + 1].start is not None:
            gap = lines[idx + 1].start - line.start
            line.end = round(line.start + max(1.0, min(gap - 0.15, 6.5)), 2)
        else:
            line.end = round(min(duration, line.start + 5.0), 2)


def _extract_inline_ruby(text: str) -> tuple[str, list[tuple[int, int, str, str]]]:
    """
    Strip inline `漢字（よみ）` ruby annotations and return `(clean_text, spans)`.
    Each span is `(clean_start, clean_end, base_kanji, reading)`.
    """
    clean_parts: list[str] = []
    spans: list[tuple[int, int, str, str]] = []
    cursor = 0
    clean_len = 0

    for match in RUBY_RE.finditer(text):
        if match.start() > cursor:
            seg = text[cursor : match.start()]
            clean_parts.append(seg)
            clean_len += len(seg)
        base = match.group(1)
        reading = match.group(2)
        clean_parts.append(base)
        spans.append((clean_len, clean_len + len(base), base, reading))
        clean_len += len(base)
        cursor = match.end()

    if cursor < len(text):
        clean_parts.append(text[cursor:])

    return "".join(clean_parts), spans


def _map_pos_type(pos_tuple: tuple[str, ...]) -> str:
    """Map Sudachi 6-tuple POS to the 7 standard card POS keys."""
    p0 = pos_tuple[0]
    if p0 in ("名詞", "代名詞", "接尾辞", "接頭辞"):
        return "noun"
    if p0 == "動詞":
        return "verb"
    if p0 == "助詞":
        return "particle"
    if p0 in ("形容詞", "形状詞"):
        return "adj"
    if p0 in ("副詞", "接続詞"):
        return "adv"
    if p0 == "連体詞":
        return "prenoun"
    if p0 in ("助動詞", "感動詞"):
        return "aux"
    return "noun"


def _format_pos_label(pos_tuple: tuple[str, ...], dict_form: str) -> str:
    """Create a concise Chinese grammar annotation from Sudachi POS tuple."""
    p0, p1, _, _, conj_type, conj_form = pos_tuple
    zh_major = {
        "名詞": "名词",
        "代名詞": "代词",
        "動詞": "动词",
        "助詞": "助词",
        "形容詞": "形1",
        "形状詞": "形2",
        "副詞": "副词",
        "接続詞": "接续词",
        "連体詞": "连体词",
        "助動詞": "助动词",
        "感動詞": "感叹词",
        "接頭辞": "接头词",
        "接尾辞": "接尾词",
        "記号": "符号",
        "補助記号": "标点",
    }.get(p0, p0)

    extras: list[str] = []
    if p0 in ("動詞", "形容詞", "助動詞") and dict_form and dict_form != "*":
        extras.append(dict_form)
    elif p1 and p1 != "*" and p1 not in ("一般",):
        extras.append(p1)
    if conj_form and conj_form != "*":
        short_form = conj_form.split("-")[0]
        extras.append(short_form)

    return f"{zh_major}[{'·'.join(extras)}]" if extras else zh_major


class JapaneseDrafter:
    """Offline SudachiPy + pykakasi morphological drafter."""

    def __init__(self, split_mode: str = "C") -> None:
        mode_map = {
            "A": sudachipy.SplitMode.A,
            "B": sudachipy.SplitMode.B,
            "C": sudachipy.SplitMode.C,
        }
        self._tokenizer = sudachipy.Dictionary().tokenizer(mode_map.get(split_mode.upper(), sudachipy.SplitMode.C))
        self._kakasi = pykakasi.kakasi()

    def _to_hiragana_and_romaji(self, text_kana_or_jp: str, preserve_katakana: bool = False) -> tuple[str, str]:
        hira = jaconv.kata2hira(text_kana_or_jp)
        converted = self._kakasi.convert(hira)
        hira_out = "".join(item.get("hira", "") for item in converted) or hira
        romaji_out = " ".join(item.get("hepburn", "").strip() for item in converted if item.get("hepburn", "").strip())
        kana_out = text_kana_or_jp if (preserve_katakana and re.fullmatch(r"[ァ-ヶー]+", text_kana_or_jp)) else hira_out
        return kana_out, (romaji_out or kana_out)

    def tokenize_line(self, raw_text: str) -> list[dict[str, Any]]:
        """Tokenize one Japanese lyric line into draft 5+1 token dicts."""
        clean_text, ruby_spans = _extract_inline_ruby(raw_text)
        morphemes = list(self._tokenizer.tokenize(clean_text))

        tokens: list[dict[str, Any]] = []
        idx = 0
        while idx < len(morphemes):
            m = morphemes[idx]
            surf = m.surface()
            pos = m.part_of_speech()
            begin = m.begin()
            end = m.end()
            reading = m.reading_form() or surf
            dict_form = m.dictionary_form()

            # Skip pure whitespace or punctuation tokens unless line has nothing else
            if pos[0] == "空白" or not surf.strip():
                idx += 1
                continue
            if pos[0] == "補助記号" and len(morphemes) > 1:
                idx += 1
                continue

            # Pedagogical merger: prefix (お/ご) + noun -> single noun token
            if pos[0] == "接頭辞" and idx + 1 < len(morphemes) and morphemes[idx + 1].part_of_speech()[0] == "名詞":
                nxt = morphemes[idx + 1]
                surf = surf + nxt.surface()
                pos = nxt.part_of_speech()
                end = nxt.end()
                reading = reading + (nxt.reading_form() or nxt.surface())
                dict_form = surf
                idx += 1

            # Pedagogical merger: 誰 + か / 何 + か -> single pronoun token
            elif surf in ("誰", "何", "いつ", "どこ") and idx + 1 < len(morphemes) and morphemes[idx + 1].surface() == "か":
                nxt = morphemes[idx + 1]
                surf = surf + "か"
                end = nxt.end()
                reading = reading + "カ"
                dict_form = surf
                idx += 1

            # Check inline ruby/ateji overlap
            ruby_note = ""
            has_ateji = False
            ruby_is_katakana = False
            for r_s, r_e, r_base, r_read in ruby_spans:
                if max(begin, r_s) < min(end, r_e):
                    has_ateji = True
                    ruby_is_katakana = bool(re.fullmatch(r"[ァ-ヶー]+", r_read))
                    if surf == r_base:
                        reading = r_read
                    else:
                        reading = surf.replace(r_base, r_read)
                    ruby_note = f"注音:{r_base}→{r_read}"
                    break

            surf_is_katakana = bool(re.fullmatch(r"[ァ-ヶー]+", surf))
            kana, romaji = self._to_hiragana_and_romaji(reading, preserve_katakana=(ruby_is_katakana or surf_is_katakana))
            tok_type = _map_pos_type(pos)
            pos_label = _format_pos_label(pos, dict_form)

            needs_review = bool(
                has_ateji
                or KANJI_RE.search(surf)
                or HISTORICAL_KANA_RE.search(surf)
                or pos[0] == "記号"
            )

            tok: dict[str, Any] = {
                "romaji": romaji,
                "kana": kana,
                "word": surf,
                "pos": pos_label,
                "gloss": "[待释义]",
                "type": tok_type,
                "needs_review": needs_review,
            }
            if ruby_note:
                tok["note"] = ruby_note
            tokens.append(tok)
            idx += 1

        if not tokens:
            kana, romaji = self._to_hiragana_and_romaji(clean_text)
            tokens.append(
                {
                    "romaji": romaji,
                    "kana": kana,
                    "word": clean_text,
                    "pos": "待标注",
                    "gloss": "[待释义]",
                    "type": "noun",
                    "needs_review": True,
                }
            )
        return tokens


def _detect_lyrics_format(lyrics_path: str) -> str:
    ext = os.path.splitext(lyrics_path)[1].lower()
    if ext in (".lrc", ".srt"):
        return ext[1:]
    with open(lyrics_path, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
    if SRT_TIME_RE.search(sample):
        return "srt"
    for line in sample.splitlines():
        if LRC_LINE_RE.match(line.strip()):
            return "lrc"
    return "txt"


def draft_song_data(
    lyrics_path: str,
    title: str,
    artist: str,
    album: str = "",
    audio_path: str | None = None,
    tlyric_path: str | None = None,
    duration: float | None = None,
    use_whisper: bool = False,
    whisper_model: str = "base",
    split_mode: str = "C",
) -> dict[str, Any]:
    """Create a complete draft song JSON structure from LRC/SRT/TXT (+ optional audio)."""
    fmt = _detect_lyrics_format(lyrics_path)
    if fmt == "lrc":
        lines = parse_lrc(lyrics_path)
    elif fmt == "srt":
        lines = parse_srt(lyrics_path)
    else:
        lines = parse_plain_text(lyrics_path)

    if not lines:
        raise ValueError(f"No lyric lines parsed from {lyrics_path}")

    if tlyric_path and os.path.exists(tlyric_path):
        merge_tlyric(lines, tlyric_path)

    if duration is None:
        if audio_path and os.path.exists(audio_path):
            duration = round(probe_audio_duration(audio_path), 3)
        else:
            last_t = max((ln.end or ln.start or 0.0) for ln in lines)
            duration = round(max(last_t + 8.0, len(lines) * 4.5), 3)

    has_unaligned = any(ln.start is None for ln in lines)
    if has_unaligned:
        if use_whisper and audio_path and os.path.exists(audio_path):
            _align_plain_lines_with_whisper(lines, audio_path, duration, model_size=whisper_model)
        else:
            _assign_uniform_timestamps(lines, duration)

    _fill_missing_end_times(lines, duration)

    drafter = JapaneseDrafter(split_mode=split_mode)
    sentences: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        sentences.append(
            {
                "id": idx,
                "start": round(float(line.start or 0.0), 3),
                "end": round(float(line.end or 0.0), 3),
                "raw": line.text,
                "trans": f"「{line.trans}」" if line.trans else f"[待意译] {line.text}",
                "tokens": drafter.tokenize_line(line.text),
            }
        )

    raw_data = {
        "meta": {
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
            "style": "5+1 Dual-Buffer Morpheme Breakdown",
            "draft": True,
        },
        "colors": DEFAULT_POS_COLORS,
        "sentences": sentences,
    }
    return normalize_song_data(raw_data)
