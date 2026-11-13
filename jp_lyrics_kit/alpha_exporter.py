"""Dual-buffer alpha lyrics track exporter (concat & 60fps smooth relay) and memory overlay engine."""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .card_renderer import (
    ACTIVE_STRIP_Y0,
    BUFFER_STRIP_Y0,
    CANVAS_H,
    CANVAS_W,
    STRIP_X,
    FontPack,
    batch_render_cards,
    render_card_strips,
)
from .schema import CardTheme, ensure_binary
from .timeline import TimelineSegment, build_timeline


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 <= edge0:
        return 1.0 if x >= edge1 else 0.0
    u = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return u * u * (3.0 - 2.0 * u)


def _paste_strip_bgr(
    frame_bgr: np.ndarray,
    strip_bgra: np.ndarray,
    x_left: int,
    y_top: float,
    opacity: float,
) -> None:
    if opacity <= 0.01:
        return
    sh, sw = strip_bgra.shape[:2]
    y0 = max(0, int(round(y_top)))
    y1 = min(CANVAS_H, y0 + sh)
    if y1 <= y0:
        return
    src_y0 = y0 - int(round(y_top))
    src_y1 = src_y0 + (y1 - y0)
    sub = strip_bgra[src_y0:src_y1, :sw]
    alpha = (sub[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)
    roi = frame_bgr[y0:y1, x_left : x_left + sw].astype(np.float32)
    frame_bgr[y0:y1, x_left : x_left + sw] = np.clip(
        roi * (1.0 - alpha) + sub[:, :, :3].astype(np.float32) * alpha, 0, 255
    ).astype(np.uint8)


def _paste_strip_rgba(
    frame_rgba: np.ndarray,
    strip_bgra: np.ndarray,
    x_left: int,
    y_top: float,
    opacity: float,
) -> None:
    if opacity <= 0.01:
        return
    sh, sw = strip_bgra.shape[:2]
    y0 = max(0, int(round(y_top)))
    y1 = min(CANVAS_H, y0 + sh)
    if y1 <= y0:
        return
    src_y0 = y0 - int(round(y_top))
    src_y1 = src_y0 + (y1 - y0)
    sub_bgra = strip_bgra[src_y0:src_y1, :sw]
    sub_rgba = cv2.cvtColor(sub_bgra, cv2.COLOR_BGRA2RGBA)
    src_a = (sub_rgba[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)

    dst = frame_rgba[y0:y1, x_left : x_left + sw].astype(np.float32)
    dst_a = dst[:, :, 3:4] / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    safe_a = np.maximum(out_a, 1e-5)
    out_rgb = (sub_rgba[:, :, :3].astype(np.float32) * src_a + dst[:, :, :3] * dst_a * (1.0 - src_a)) / safe_a
    frame_rgba[y0:y1, x_left : x_left + sw, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    frame_rgba[y0:y1, x_left : x_left + sw, 3:4] = np.clip(out_a * 255.0, 0, 255).astype(np.uint8)


class OverlayEngine:
    """Renders smooth dual-buffer card relay transitions onto BGR or RGBA frames."""

    def __init__(
        self,
        song_data: dict[str, Any],
        theme: CardTheme | str = "kalk_crimson",
        show_timestamps: bool = True,
        interlude_gap: float = 12.0,
        relay_transition_sec: float = 0.22,
        fade_sec: float = 0.45,
        fonts: FontPack | None = None,
    ) -> None:
        self.song_data = song_data
        self.segments = build_timeline(song_data, interlude_gap=interlude_gap)
        self.active_strips, self.buffer_strips = render_card_strips(
            song_data, theme=theme, show_timestamps=show_timestamps, fonts=fonts
        )
        self.relay_transition_sec = relay_transition_sec
        self.fade_sec = fade_sec

    def _draw_at_time(self, target: np.ndarray, t: float, paste_fn: Any) -> None:
        for idx, seg in enumerate(self.segments):
            if not (seg.start <= t < seg.end):
                continue

            if seg.kind == "blank":
                # Fade in just before the next card starts
                if idx + 1 < len(self.segments) and self.segments[idx + 1].kind == "card":
                    nxt = self.segments[idx + 1]
                    if t >= nxt.start - self.fade_sec:
                        p_in = _smoothstep(nxt.start - self.fade_sec, nxt.start, t)
                        dy = (1.0 - p_in) * 22.0
                        if nxt.sentence_id in self.active_strips:
                            paste_fn(target, self.active_strips[nxt.sentence_id], STRIP_X, ACTIVE_STRIP_Y0 + dy, p_in)
                        if nxt.next_sentence_id in self.buffer_strips:
                            paste_fn(target, self.buffer_strips[nxt.next_sentence_id], STRIP_X, BUFFER_STRIP_Y0 + dy, p_in)
                return

            sid = seg.sentence_id
            next_sid = seg.next_sentence_id
            prev_sid = seg.prev_sentence_id
            if sid is None:
                return

            # Smooth fade-out before blank interlude or outro end
            fade_out = 1.0
            is_last_seg = idx == len(self.segments) - 1
            next_is_blank = idx + 1 < len(self.segments) and self.segments[idx + 1].kind == "blank"
            if next_is_blank:
                fade_out = 1.0 - _smoothstep(seg.end - 0.5, seg.end, t)
            elif is_last_seg and seg.duration > 1.5:
                fade_out = 1.0 - _smoothstep(seg.end - 1.0, seg.end - 0.05, t)

            dt = t - seg.start
            if seg.seamless_from_prev and prev_sid is not None and dt < self.relay_transition_sec and self.relay_transition_sec > 0:
                u = dt / self.relay_transition_sec
                ease = 1.0 - (1.0 - u) ** 3
                if prev_sid in self.active_strips:
                    paste_fn(target, self.active_strips[prev_sid], STRIP_X, ACTIVE_STRIP_Y0 - 28.0 * ease, (1.0 - ease) * fade_out)
                y_glide = BUFFER_STRIP_Y0 + (ACTIVE_STRIP_Y0 - BUFFER_STRIP_Y0) * ease
                if sid in self.buffer_strips:
                    paste_fn(target, self.buffer_strips[sid], STRIP_X, y_glide, (1.0 - ease) * fade_out)
                if sid in self.active_strips:
                    paste_fn(target, self.active_strips[sid], STRIP_X, y_glide, ease * fade_out)
                if next_sid is not None and next_sid in self.buffer_strips:
                    paste_fn(target, self.buffer_strips[next_sid], STRIP_X, BUFFER_STRIP_Y0 + 24.0 * (1.0 - ease), ease * fade_out)
            else:
                if sid in self.active_strips:
                    paste_fn(target, self.active_strips[sid], STRIP_X, ACTIVE_STRIP_Y0, fade_out)
                if next_sid is not None and next_sid in self.buffer_strips:
                    paste_fn(target, self.buffer_strips[next_sid], STRIP_X, BUFFER_STRIP_Y0, fade_out)
            return

    def overlay_bgr(self, frame_bgr: np.ndarray, t: float) -> np.ndarray:
        """Composite dual-buffer cards onto a BGR uint8 frame in place."""
        self._draw_at_time(frame_bgr, t, _paste_strip_bgr)
        return frame_bgr

    def render_rgba_frame(self, t: float) -> np.ndarray:
        """Return a 1920x1080 RGBA transparent frame for alpha video export."""
        frame = np.zeros((CANVAS_H, CANVAS_W, 4), dtype=np.uint8)
        self._draw_at_time(frame, t, _paste_strip_rgba)
        return frame


def export_alpha_mov(
    song_data: dict[str, Any],
    output_mov: str,
    work_dir: str,
    mode: str = "concat",
    fps: int = 30,
    theme: CardTheme | str = "kalk_crimson",
    show_timestamps: bool = True,
    interlude_gap: float = 12.0,
    fonts: FontPack | None = None,
) -> str:
    """
    Export a 1920x1080 transparent QuickTime RLE (`qtrle` / `argb`) alpha MOV track.

    - `concat` mode: renders static composite cards and builds an FFmpeg concat timeline (very fast).
    - `smooth` mode: streams animated frames with smooth Slot B -> Slot A upward relay transitions.
    """
    ffmpeg_bin = ensure_binary("ffmpeg")
    os.makedirs(work_dir, exist_ok=True)
    out_parent = os.path.dirname(os.path.abspath(output_mov))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)

    if mode == "smooth":
        engine = OverlayEngine(
            song_data,
            theme=theme,
            show_timestamps=show_timestamps,
            interlude_gap=interlude_gap,
            fonts=fonts,
        )
        total_dur = float(song_data["meta"]["duration"])
        total_frames = max(1, int(round(total_dur * fps)))
        cmd = [
            ffmpeg_bin, "-y", "-v", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{CANVAS_W}x{CANVAS_H}",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            output_mov,
        ]
        with tempfile.TemporaryFile() as err_log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err_log)
            assert proc.stdin is not None
            for f_idx in range(total_frames):
                rgba = engine.render_rgba_frame(f_idx / float(fps))
                proc.stdin.write(rgba.tobytes())
            proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                err_log.seek(0)
                stderr = err_log.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"FFmpeg smooth alpha export failed: {stderr}")
        return output_mov

    # Fast concat mode
    cards_dir = os.path.join(work_dir, "output_cards")
    comp_dir = os.path.join(work_dir, "composite_frames")
    os.makedirs(comp_dir, exist_ok=True)

    paths = batch_render_cards(song_data, cards_dir, theme=theme, show_timestamps=show_timestamps, fonts=fonts)
    blank_path = os.path.join(comp_dir, "frame_blank.png")
    Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0)).save(blank_path)

    segments: list[TimelineSegment] = build_timeline(song_data, interlude_gap=interlude_gap)
    composite_cache: dict[tuple[int, int | None], str] = {}

    for seg in segments:
        if seg.kind != "card" or seg.sentence_id is None:
            continue
        key = (seg.sentence_id, seg.next_sentence_id)
        if key in composite_cache:
            continue
        frame = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        frame.alpha_composite(Image.open(paths["active"][seg.sentence_id]))
        if seg.next_sentence_id is not None and seg.next_sentence_id in paths["buffer"]:
            frame.alpha_composite(Image.open(paths["buffer"][seg.next_sentence_id]))
        comp_name = f"frame_{seg.sentence_id:02d}.png"
        comp_path = os.path.join(comp_dir, comp_name)
        frame.save(comp_path)
        composite_cache[key] = comp_name

    concat_file = os.path.join(work_dir, "concat_list.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for seg in segments:
            if seg.duration <= 0.001:
                continue
            fname = "frame_blank.png" if seg.kind == "blank" else composite_cache[(seg.sentence_id, seg.next_sentence_id)]  # type: ignore[index]
            rel_img = os.path.join("composite_frames", fname).replace("\\", "/")
            f.write(f"file '{rel_img}'\n")
            f.write(f"duration {seg.duration:.3f}\n")
        f.write("file 'composite_frames/frame_blank.png'\n")

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", os.path.abspath(concat_file),
        "-c:v", "qtrle",
        "-pix_fmt", "argb",
        "-r", str(fps),
        os.path.abspath(output_mov),
    ]
    res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg concat alpha export failed: {res.stderr}")
    return output_mov
