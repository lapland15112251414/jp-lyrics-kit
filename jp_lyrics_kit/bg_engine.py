"""Pluggable background rendering (external, preset SVG/OpenCV, custom plugin) and master muxing."""

from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import tempfile
from typing import Any, Callable

import cv2
import numpy as np
import resvg_py

from .alpha_exporter import OverlayEngine
from .card_renderer import CANVAS_H, CANVAS_W, FontPack
from .schema import CardTheme, ensure_binary
from .timeline import build_timeline, card_visibility_at

S4 = 16


def apply_card_sanctuary_floor(
    canvas_bgr: np.ndarray,
    card_visibility: float,
    y0: int = 500,
    strength: float = 0.62,
) -> np.ndarray:
    """
    Softly darken the lower-third sanctuary zone whenever 5+1 cards are visible
    so text stays crisp over animated backgrounds, lifting during instrumental interludes.
    """
    if card_visibility <= 0.01:
        return canvas_bgr
    h_zone = CANVAS_H - y0
    grad = np.linspace(0.0, strength * card_visibility, h_zone, dtype=np.float32)[:, None, None]
    roi = canvas_bgr[y0:CANVAS_H, :, :].astype(np.float32)
    canvas_bgr[y0:CANVAS_H, :, :] = np.clip(roi * (1.0 - grad), 0, 255).astype(np.uint8)
    return canvas_bgr


def _render_svg_bgra(svg_str: str, w: int, h: int) -> np.ndarray:
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_str, width=w, height=h, skip_system_fonts=True)
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    bgra = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if bgra is None:
        raise RuntimeError("Failed to decode SVG bytes into BGRA image.")
    return bgra


def _blend_sprite(
    canvas_bgr: np.ndarray,
    sprite_bgra: np.ndarray,
    cx: float,
    cy: float,
    scale: float = 1.0,
    angle_deg: float = 0.0,
    opacity: float = 1.0,
) -> None:
    if opacity <= 0.01 or scale <= 0.01:
        return
    sh, sw = sprite_bgra.shape[:2]
    max_dim = int(math.hypot(sw * scale, sh * scale)) + 8
    half_d = max_dim // 2
    x0, y0 = int(cx) - half_d, int(cy) - half_d
    x1, y1 = x0 + max_dim, y0 + max_dim
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(CANVAS_W, x1), min(CANVAS_H, y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return

    rad = math.radians(angle_deg)
    c, s = math.cos(rad) * scale, math.sin(rad) * scale
    tx = (cx - cx0) - (sw * 0.5 * c - sh * 0.5 * s)
    ty = (cy - cy0) - (sw * 0.5 * s + sh * 0.5 * c)
    M = np.array([[c, -s, tx], [s, c, ty]], dtype=np.float32)
    warped = cv2.warpAffine(
        sprite_bgra, M, (cx1 - cx0, cy1 - cy0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT
    )
    a = (warped[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)
    roi = canvas_bgr[cy0:cy1, cx0:cx1].astype(np.float32)
    canvas_bgr[cy0:cy1, cx0:cx1] = np.clip(roi * (1.0 - a) + warped[:, :, :3].astype(np.float32) * a, 0, 255).astype(
        np.uint8
    )


def _build_lotus_emblem_svg() -> str:
    petals = []
    for k in range(12):
        ang = k * 30
        petals.append(
            f'<path d="M 200 200 C 175 140 185 75 200 45 C 215 75 225 140 200 200 Z" '
            f'fill="url(#petalGrad)" stroke="#e5c882" stroke-width="1.4" opacity="0.82" '
            f'transform="rotate({ang} 200 200)"/>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
        "<defs>"
        '<linearGradient id="petalGrad" x1="0%" y1="100%" x2="0%" y2="0%">'
        '<stop offset="0%" stop-color="#3b0764" stop-opacity="0.3"/>'
        '<stop offset="65%" stop-color="#9f1239" stop-opacity="0.85"/>'
        '<stop offset="100%" stop-color="#fde68a" stop-opacity="0.95"/>'
        "</linearGradient>"
        "</defs>"
        + "".join(petals)
        + '<circle cx="200" cy="200" r="148" fill="none" stroke="#d4af37" stroke-width="1.2" stroke-dasharray="6 4"/>'
        + '<circle cx="200" cy="200" r="32" fill="#fde68a" fill-opacity="0.22" stroke="#fde68a" stroke-width="1.5"/>'
        + "</svg>"
    )


class PresetBackgroundRenderer:
    """Built-in audio-reactive presets (`astrolabe_botanical`, `twilight_horizon`, `minimal_ink`)."""

    def __init__(self, preset: str, song_data: dict[str, Any]) -> None:
        self.preset = preset
        self.song_data = song_data
        self.title = str(song_data["meta"].get("title", ""))
        self.artist = str(song_data["meta"].get("artist", ""))
        self.emblem = _render_svg_bgra(_build_lotus_emblem_svg(), 420, 420) if preset == "astrolabe_botanical" else None

        rng = np.random.default_rng(2003)
        self.spores = [
            {
                "x0": float(rng.uniform(40, CANVAS_W - 40)),
                "y0": float(rng.uniform(20, 560)),
                "vx": float(rng.uniform(-18, 18)),
                "vy": float(rng.uniform(-26, -6)),
                "r": float(rng.uniform(1.2, 3.2)),
                "phase": float(rng.uniform(0, math.pi * 2)),
            }
            for _ in range(48)
        ]

    def render_frame(self, t: float, env: dict[str, float], card_vis: float) -> np.ndarray:
        sub = env.get("sub", 0.0)
        mid = env.get("mid", 0.0)
        high = env.get("high", 0.0)
        rms = env.get("rms", 0.0)

        cy = 270.0 + (1.0 - card_vis) * 180.0
        cx = CANVAS_W * 0.5 + 6.0 * math.sin(t * 0.7)

        if self.preset == "twilight_horizon":
            c_top = np.array([34, 18, 14], dtype=np.float32)
            c_mid = np.array([75 + 25 * rms, 38 + 18 * mid, 58 + 20 * sub], dtype=np.float32)
            c_bot = np.array([12, 10, 14], dtype=np.float32)
        elif self.preset == "minimal_ink":
            c_top = np.array([16, 16, 18], dtype=np.float32)
            c_mid = np.array([28 + 12 * rms, 26 + 10 * mid, 30 + 12 * sub], dtype=np.float32)
            c_bot = np.array([10, 10, 12], dtype=np.float32)
        else:  # astrolabe_botanical
            c_top = np.array([24, 10, 18], dtype=np.float32)
            c_mid = np.array([58 + 24 * sub, 24 + 14 * mid, 72 + 28 * rms], dtype=np.float32)
            c_bot = np.array([10, 6, 12], dtype=np.float32)

        split = max(1, min(CANVAS_H - 1, int(cy)))
        col_buf = np.empty((CANVAS_H, 1, 3), dtype=np.uint8)
        f1 = np.linspace(0.0, 1.0, split, dtype=np.float32)[:, None]
        f2 = np.linspace(0.0, 1.0, CANVAS_H - split, dtype=np.float32)[:, None]
        col_buf[:split, 0] = np.clip(c_top + f1 * (c_mid - c_top), 0, 255).astype(np.uint8)
        col_buf[split:, 0] = np.clip(c_mid + (f2 ** 0.8) * (c_bot - c_mid), 0, 255).astype(np.uint8)
        frame = cv2.resize(col_buf, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_NEAREST)

        if self.preset == "astrolabe_botanical" and self.emblem is not None:
            for rad, spd, clr in ((165, 14.0, (120, 175, 225)), (235, -9.0, (150, 115, 210))):
                r_s = int((rad + 14.0 * sub) * S4)
                cv2.circle(frame, (int(cx * S4), int(cy * S4)), r_s, clr, 1, cv2.LINE_AA, shift=4)
            _blend_sprite(frame, self.emblem, cx, cy, scale=0.82 + 0.08 * mid, angle_deg=t * 10.0, opacity=0.88)

        elif self.preset == "twilight_horizon":
            hy = int(cy + 110)
            cv2.line(frame, (0, hy), (CANVAS_W, hy), (120, 145, 220), 1, cv2.LINE_AA)
            for idx in range(1, 8):
                persp_y = hy + int((idx ** 1.65) * 14)
                if persp_y < CANVAS_H:
                    cv2.line(frame, (0, persp_y), (CANVAS_W, persp_y), (60, 72, 110), 1, cv2.LINE_AA)
            cv2.circle(frame, (int(cx * S4), int((hy - 24) * S4)), int((72 + 12 * sub) * S4), (110, 155, 245), 2, cv2.LINE_AA, shift=4)

        # Harmonic ribbon across upper stage
        xs = np.linspace(120, CANVAS_W - 120, 120)
        amp = 16.0 + 34.0 * mid
        ys = cy + amp * np.sin((xs - cx) * 0.015 + t * 3.0) * np.exp(-((xs - cx) / 720.0) ** 2)
        pts = np.column_stack((xs * S4, ys * S4)).astype(np.int32)
        cv2.polylines(frame, [pts], False, (145, 200, 240), 1, cv2.LINE_AA, shift=4)

        for sp in self.spores:
            px = (sp["x0"] + sp["vx"] * t) % CANVAS_W
            py = (sp["y0"] + sp["vy"] * t) % 560
            bright = int(130 + 110 * high * (0.5 + 0.5 * math.sin(t * 4.0 + sp["phase"])))
            cv2.circle(frame, (int(px * S4), int(py * S4)), int(sp["r"] * S4), (bright, bright, 255), -1, cv2.LINE_AA, shift=4)

        return frame


def _load_scene_plugin(plugin_path: str, song_data: dict[str, Any], envs: dict[str, np.ndarray]) -> Callable[[float, dict[str, float], float], np.ndarray]:
    spec = importlib.util.spec_from_file_location("jp_lyrics_scene_plugin", plugin_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scene plugin: {plugin_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if hasattr(mod, "ScenePlugin"):
        instance = mod.ScenePlugin(song_data, envs)
        return lambda t, env, vis: instance.render_frame(t, env, vis)
    if hasattr(mod, "render_frame"):
        return lambda t, env, vis: mod.render_frame(t, env, song_data, vis)
    raise AttributeError(f"Plugin {plugin_path} must define ScenePlugin class or render_frame(t, env, song_data, vis).")


def _sample_env(envs: dict[str, np.ndarray], f_idx: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in ("sub", "mid", "high", "rms", "flux"):
        key = f"env_{name}"
        if key in envs and len(envs[key]) > 0:
            arr = envs[key]
            out[name] = float(arr[min(max(0, f_idx), len(arr) - 1)])
        else:
            out[name] = 0.0
    return out


def render_master_video(
    song_data: dict[str, Any],
    audio_path: str,
    output_mp4: str,
    bg_mode: str = "preset",
    bg_preset: str = "astrolabe_botanical",
    bg_video_path: str | None = None,
    plugin_path: str | None = None,
    envelopes_npz: str | None = None,
    fps: int = 60,
    theme: CardTheme | str = "kalk_crimson",
    show_timestamps: bool = True,
    bg_only_mp4: str | None = None,
    preview_dir: str | None = None,
    preview_times: list[float] | None = None,
    start_sec: float = 0.0,
    max_duration: float | None = None,
    crf: int = 17,
    sanctuary_strength: float = 0.62,
    fonts: FontPack | None = None,
) -> str:
    """
    Render background + smooth dual-buffer 5+1 card overlay + audio mux into final MP4.
    Supports `external` video, `preset` audio-reactive themes, and `plugin` scene scripts.
    """
    from .audio_env import load_envelopes

    ffmpeg_bin = ensure_binary("ffmpeg")
    total_dur = float(song_data["meta"]["duration"])
    render_end = min(total_dur, start_sec + max_duration) if max_duration else total_dur
    render_dur = max(0.1, render_end - start_sec)

    envs = load_envelopes(envelopes_npz) if (envelopes_npz and os.path.exists(envelopes_npz)) else {}
    segments = build_timeline(song_data)
    overlay = OverlayEngine(song_data, theme=theme, show_timestamps=show_timestamps, fonts=fonts)

    cap: cv2.VideoCapture | None = None
    if bg_mode == "external":
        if not bg_video_path or not os.path.exists(bg_video_path):
            raise FileNotFoundError(f"External background video not found: {bg_video_path}")
        cap = cv2.VideoCapture(bg_video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open external background video: {bg_video_path}")
        ext_fps = cap.get(cv2.CAP_PROP_FPS) or float(fps)
        frame_provider = None
    elif bg_mode == "plugin":
        if not plugin_path or not os.path.exists(plugin_path):
            raise FileNotFoundError(f"Scene plugin not found: {plugin_path}")
        frame_provider = _load_scene_plugin(plugin_path, song_data, envs)
    else:
        preset_renderer = PresetBackgroundRenderer(bg_preset, song_data)
        frame_provider = lambda t, env, vis: preset_renderer.render_frame(t, env, vis)

    def get_bg_frame(t: float, f_idx: int) -> np.ndarray:
        vis = card_visibility_at(segments, t)
        if cap is not None:
            total_ext = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
            target_ext_idx = int((t * ext_fps) % total_ext)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_ext_idx)
            ok, bgr = cap.read()
            if not ok or bgr is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, bgr = cap.read()
            if bgr.shape[1] != CANVAS_W or bgr.shape[0] != CANVAS_H:
                bgr = cv2.resize(bgr, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_AREA)
        else:
            assert frame_provider is not None
            env = _sample_env(envs, f_idx)
            bgr = frame_provider(t, env, vis)

        if sanctuary_strength > 0:
            apply_card_sanctuary_floor(bgr, vis, strength=sanctuary_strength)
        return bgr

    if preview_dir and preview_times:
        os.makedirs(preview_dir, exist_ok=True)
        for ts in preview_times:
            f_idx = int(round(ts * fps))
            frame = get_bg_frame(ts, f_idx).copy()
            overlay.overlay_bgr(frame, ts)
            out_png = os.path.join(preview_dir, f"preview_{ts:06.2f}s.png")
            cv2.imwrite(out_png, frame)

    out_parent = os.path.dirname(os.path.abspath(output_mp4))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)

    cmd_master = [
        ffmpeg_bin, "-y", "-v", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-s", f"{CANVAS_W}x{CANVAS_H}", "-r", str(fps),
        "-i", "-",
        "-ss", f"{start_sec:.3f}",
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest",
        output_mp4,
    ]
    with tempfile.TemporaryFile() as err_master, tempfile.TemporaryFile() as err_bg:
        proc_master = subprocess.Popen(cmd_master, stdin=subprocess.PIPE, stderr=err_master)
        proc_bg = None
        if bg_only_mp4:
            bg_parent = os.path.dirname(os.path.abspath(bg_only_mp4))
            if bg_parent:
                os.makedirs(bg_parent, exist_ok=True)
            cmd_bg = [
                ffmpeg_bin, "-y", "-v", "error",
                "-f", "rawvideo", "-vcodec", "rawvideo",
                "-pix_fmt", "bgr24", "-s", f"{CANVAS_W}x{CANVAS_H}", "-r", str(fps),
                "-i", "-",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", str(crf),
                bg_only_mp4,
            ]
            proc_bg = subprocess.Popen(cmd_bg, stdin=subprocess.PIPE, stderr=err_bg)

        total_frames = max(1, int(round(render_dur * fps)))
        start_f = int(round(start_sec * fps))
        assert proc_master.stdin is not None
        for i in range(total_frames):
            f_idx = start_f + i
            t = f_idx / float(fps)
            bg = get_bg_frame(t, f_idx)
            if proc_bg is not None and proc_bg.stdin is not None:
                proc_bg.stdin.write(bg.tobytes())
            master = bg.copy()
            overlay.overlay_bgr(master, t)
            proc_master.stdin.write(master.tobytes())

        proc_master.stdin.close()
        rc_m = proc_master.wait()
        if cap is not None:
            cap.release()
        if proc_bg is not None and proc_bg.stdin is not None:
            proc_bg.stdin.close()
            rc_b = proc_bg.wait()
            if rc_b != 0:
                err_bg.seek(0)
                raise RuntimeError(f"FFmpeg bg_only render failed: {err_bg.read().decode('utf-8', errors='ignore')}")

        if rc_m != 0:
            err_master.seek(0)
            err_m = err_master.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"FFmpeg master render failed: {err_m}")
    return output_mp4
