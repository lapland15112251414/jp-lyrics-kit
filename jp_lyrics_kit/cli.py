"""Unified command-line interface for jp_lyrics_kit."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys

from .alpha_exporter import export_alpha_mov
from .audio_env import extract_audio_envelopes
from .bg_engine import render_master_video
from .card_renderer import FontPack, batch_render_cards
from .cover_gen import COVER_STYLES, generate_covers
from .drafter import draft_song_data
from .schema import THEMES, load_song_data, probe_audio_duration, save_song_data, validate_song_data
from .workbench import build_workbench_html

SCENE_PLUGIN_TEMPLATE = '''"""Custom per-song background scene plugin template for jp-lyrics-kit."""

import numpy as np


class ScenePlugin:
    def __init__(self, song_data: dict, envs: dict[str, np.ndarray]) -> None:
        self.song_data = song_data
        self.envs = envs

    def render_frame(self, t: float, env: dict[str, float], card_vis: float) -> np.ndarray:
        """
        Return a 1920x1080 BGR uint8 frame for song timestamp `t`.
        `env` contains keys: sub, mid, high, rms, flux in ~[0, 1].
        `card_vis` is in [0, 1], indicating whether 5+1 study cards are currently visible.
        """
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        glow = int(min(255, 40 + 140 * env.get("rms", 0.0)))
        frame[:, :] = (24, 14, glow // 3)
        return frame
'''


def _add_font_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--font-jp-bold", default=None, help="Override path for Japanese bold font")
    parser.add_argument("--font-jp-reg", default=None, help="Override path for Japanese regular font")
    parser.add_argument("--font-cn-bold", default=None, help="Override path for Chinese bold font")
    parser.add_argument("--font-cn-reg", default=None, help="Override path for Chinese regular font")


def _resolve_fonts_from_args(args: argparse.Namespace, *, only_if_overridden: bool = False) -> FontPack | None:
    has_override = any(getattr(args, attr, None) for attr in ("font_jp_bold", "font_jp_reg", "font_cn_bold", "font_cn_reg"))
    if only_if_overridden and not has_override:
        return None
    return FontPack.resolve(
        jp_bold=args.font_jp_bold,
        jp_reg=args.font_jp_reg,
        cn_reg=args.font_cn_reg,
        cn_bold=args.font_cn_bold,
    )


def _cmd_doctor(args: argparse.Namespace) -> int:
    core_modules = ("PIL", "numpy", "cv2", "resvg_py", "sudachipy", "sudachidict_core", "pykakasi")
    optional_modules = ("faster_whisper", "mutagen")

    mod_status: dict[str, bool] = {}
    for name in core_modules + optional_modules:
        try:
            importlib.import_module(name)
            mod_status[name] = True
        except Exception:
            mod_status[name] = False

    binaries = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}

    fonts_info: dict[str, str | None] = {}
    font_error: str | None = None
    try:
        pack = _resolve_fonts_from_args(args)
        assert pack is not None
        fonts_info = {
            "jp_bold": pack.jp_bold,
            "jp_reg": pack.jp_reg,
            "cn_reg": pack.cn_reg,
            "cn_bold": pack.cn_bold,
        }
    except Exception as exc:
        font_error = str(exc)

    missing_core = [m for m in core_modules if not mod_status[m]]
    missing_bins = [b for b, p in binaries.items() if not p]
    ok = (sys.version_info >= (3, 10)) and not missing_core and not missing_bins and font_error is None

    report = {
        "ok": ok,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "modules": mod_status,
        "binaries": binaries,
        "fonts": fonts_info,
        "font_error": font_error,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    print(f"Python: {report['python']} ({report['platform']})")
    for b, p in binaries.items():
        print(f"  {b:8s}: {p or 'MISSING'}")
    print("Python modules:")
    for name in core_modules:
        print(f"  {name:18s}: {'OK' if mod_status[name] else 'MISSING (required)'}")
    for name in optional_modules:
        print(f"  {name:18s}: {'OK' if mod_status[name] else 'not installed (optional)'}")
    if fonts_info:
        print("Resolved CJK fonts:")
        for role, fpath in fonts_info.items():
            print(f"  {role:8s}: {fpath}")
    else:
        print(f"Fonts: ERROR - {font_error}")

    if not ok:
        print("\nDoctor found missing prerequisites above.", file=sys.stderr)
        return 1
    print("\nAll required checks passed.")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    proj_dir = os.path.abspath(args.project_dir)
    os.makedirs(proj_dir, exist_ok=True)
    for sub in ("output_cards", "previews", "deliverables"):
        os.makedirs(os.path.join(proj_dir, sub), exist_ok=True)

    plugin_path = os.path.join(proj_dir, "scene_plugin.example.py")
    if not os.path.exists(plugin_path):
        with open(plugin_path, "w", encoding="utf-8") as f:
            f.write(SCENE_PLUGIN_TEMPLATE)

    print(f"Initialized project workspace: {proj_dir}")
    print(f"Example scene plugin template: {plugin_path}")
    return 0


def _cmd_draft(args: argparse.Namespace) -> int:
    data = draft_song_data(
        lyrics_path=args.lyrics,
        title=args.title,
        artist=args.artist,
        album=args.album,
        audio_path=args.audio,
        tlyric_path=args.tlyric,
        duration=args.duration,
        use_whisper=args.whisper,
        whisper_model=args.whisper_model,
        split_mode=args.split,
    )
    save_song_data(data, args.output)
    n_sent = len(data["sentences"])
    n_review = sum(1 for s in data["sentences"] for tok in s["tokens"] if tok.get("needs_review"))
    print(f"Draft saved -> {args.output} ({n_sent} sentences, {n_review} tokens flagged needs_review)")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    errors, warnings = validate_song_data(data, strict=args.strict)
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}", file=sys.stderr)
    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).", file=sys.stderr)
        return 1
    print(f"Validation passed ({len(data['sentences'])} sentences, {len(warnings)} warning(s)).")
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    out = build_workbench_html(data, args.output, audio_path=args.audio)
    print(f"Interactive proofing workbench -> {out}")
    return 0


def _cmd_cards(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    fonts = _resolve_fonts_from_args(args)
    res = batch_render_cards(
        data,
        output_dir=args.output_dir,
        theme=args.theme,
        show_timestamps=not args.no_timestamps,
        fonts=fonts,
    )
    print(f"Rendered {len(res['active'])} active + {len(res['buffer'])} buffer cards -> {args.output_dir}")
    return 0


def _cmd_alpha(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    fonts = _resolve_fonts_from_args(args)
    work_dir = args.work_dir or os.path.dirname(os.path.abspath(args.output))
    out = export_alpha_mov(
        data,
        output_mov=args.output,
        work_dir=work_dir,
        mode=args.mode,
        fps=args.fps,
        theme=args.theme,
        show_timestamps=not args.no_timestamps,
        interlude_gap=args.interlude_gap,
        fonts=fonts,
    )
    print(f"Exported alpha MOV ({args.mode}) -> {out}")
    return 0


def _cmd_audio_env(args: argparse.Namespace) -> int:
    dur = args.duration or probe_audio_duration(args.audio)
    out = extract_audio_envelopes(args.audio, args.output, fps=args.fps, duration=dur)
    print(f"Extracted {args.fps}fps audio envelopes -> {out}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    fonts = _resolve_fonts_from_args(args)
    out = render_master_video(
        song_data=data,
        audio_path=args.audio,
        output_mp4=args.output,
        bg_mode=args.bg_mode,
        bg_preset=args.preset,
        bg_video_path=args.bg_video,
        plugin_path=args.plugin,
        envelopes_npz=args.env,
        fps=args.fps,
        theme=args.theme,
        show_timestamps=not args.no_timestamps,
        bg_only_mp4=args.bg_only,
        preview_dir=args.preview_dir,
        preview_times=args.preview_times,
        start_sec=args.start,
        max_duration=args.max_duration,
        crf=args.crf,
        sanctuary_strength=args.sanctuary,
        fonts=fonts,
    )
    print(f"Master video complete -> {out}")
    return 0


def _cmd_cover(args: argparse.Namespace) -> int:
    data = load_song_data(args.song_json)
    fonts = _resolve_fonts_from_args(args, only_if_overridden=True)
    outs = generate_covers(
        song_data=data,
        out_16x9=args.output,
        out_4x3=args.out_4x3,
        art_path=args.art,
        sentence_id=args.sentence_id,
        style=args.style,
        fonts=fonts,
    )
    print("Generated covers:", ", ".join(outs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jp-lyrics-kit",
        description="5+1 Japanese-Chinese dual-buffer lyrics learning video toolchain",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Check Python deps, FFmpeg binaries, and cross-platform CJK fonts")
    p_doc.add_argument("--json", action="store_true", help="Print machine-readable JSON diagnostics")
    _add_font_args(p_doc)
    p_doc.set_defaults(func=_cmd_doctor)

    p_init = sub.add_parser("init", help="Scaffold a new song project directory")
    p_init.add_argument("project_dir")
    p_init.set_defaults(func=_cmd_init)

    p_draft = sub.add_parser("draft", help="Create song.draft.json via offline SudachiPy + pykakasi")
    p_draft.add_argument("--lyrics", required=True, help="Path to .lrc, .srt, or .txt lyrics")
    p_draft.add_argument("--title", required=True)
    p_draft.add_argument("--artist", required=True)
    p_draft.add_argument("--album", default="")
    p_draft.add_argument("--audio", default=None, help="Optional audio file for duration/Whisper alignment")
    p_draft.add_argument("--tlyric", default=None, help="Optional paired Chinese translation LRC")
    p_draft.add_argument("--duration", type=float, default=None)
    p_draft.add_argument("--whisper", action="store_true", help="Align plain text using faster-whisper")
    p_draft.add_argument("--whisper-model", default="base")
    p_draft.add_argument("--split", choices=["A", "B", "C"], default="C")
    p_draft.add_argument("-o", "--output", default="song.draft.json")
    p_draft.set_defaults(func=_cmd_draft)

    p_val = sub.add_parser("validate", help="Validate song.json schema and timing")
    p_val.add_argument("song_json")
    p_val.add_argument("--strict", action="store_true", help="Fail if draft placeholders or needs_review remain")
    p_val.set_defaults(func=_cmd_validate)

    p_prev = sub.add_parser("preview", help="Build interactive HTML proofing workbench")
    p_prev.add_argument("song_json")
    p_prev.add_argument("-o", "--output", default="workbench.html")
    p_prev.add_argument("--audio", default=None)
    p_prev.set_defaults(func=_cmd_preview)

    p_cards = sub.add_parser("cards", help="Batch render 1080p transparent 5+1 PNG cards")
    p_cards.add_argument("song_json")
    p_cards.add_argument("-o", "--output-dir", default="output_cards")
    p_cards.add_argument("--theme", choices=sorted(THEMES.keys()), default="kalk_crimson")
    p_cards.add_argument("--no-timestamps", action="store_true")
    _add_font_args(p_cards)
    p_cards.set_defaults(func=_cmd_cards)

    p_alpha = sub.add_parser("alpha", help="Export transparent QuickTime RLE (.mov) lyrics track")
    p_alpha.add_argument("song_json")
    p_alpha.add_argument("-o", "--output", default="alpha_lyrics_track.mov")
    p_alpha.add_argument("--work-dir", default=None)
    p_alpha.add_argument("--mode", choices=["concat", "smooth"], default="concat")
    p_alpha.add_argument("--fps", type=int, default=30)
    p_alpha.add_argument("--theme", choices=sorted(THEMES.keys()), default="kalk_crimson")
    p_alpha.add_argument("--interlude-gap", type=float, default=12.0)
    p_alpha.add_argument("--no-timestamps", action="store_true")
    _add_font_args(p_alpha)
    p_alpha.set_defaults(func=_cmd_alpha)

    p_env = sub.add_parser("audio-env", help="Extract multi-band audio envelopes (.npz)")
    p_env.add_argument("audio")
    p_env.add_argument("-o", "--output", default="audio_envelopes.npz")
    p_env.add_argument("--fps", type=int, default=60)
    p_env.add_argument("--duration", type=float, default=None)
    p_env.set_defaults(func=_cmd_audio_env)

    p_ren = sub.add_parser("render", help="Render background + smooth 5+1 overlay + audio master MP4")
    p_ren.add_argument("song_json")
    p_ren.add_argument("--audio", required=True)
    p_ren.add_argument("-o", "--output", default="final_master.mp4")
    p_ren.add_argument("--bg-mode", choices=["preset", "external", "plugin"], default="preset")
    p_ren.add_argument("--preset", choices=["astrolabe_botanical", "twilight_horizon", "minimal_ink"], default="astrolabe_botanical")
    p_ren.add_argument("--bg-video", default=None)
    p_ren.add_argument("--plugin", default=None)
    p_ren.add_argument("--env", default=None, help="Path to audio_envelopes.npz")
    p_ren.add_argument("--fps", type=int, default=60)
    p_ren.add_argument("--theme", choices=sorted(THEMES.keys()), default="kalk_crimson")
    p_ren.add_argument("--no-timestamps", action="store_true")
    p_ren.add_argument("--bg-only", default=None)
    p_ren.add_argument("--preview-dir", default=None)
    p_ren.add_argument("--preview-times", type=float, nargs="*", default=None)
    p_ren.add_argument("--start", type=float, default=0.0)
    p_ren.add_argument("--max-duration", type=float, default=None)
    p_ren.add_argument("--crf", type=int, default=17)
    p_ren.add_argument("--sanctuary", type=float, default=0.62)
    _add_font_args(p_ren)
    p_ren.set_defaults(func=_cmd_render)

    p_cov = sub.add_parser("cover", help="Generate 16:9 and 4:3 covers with sample 5+1 snippet")
    p_cov.add_argument("song_json")
    p_cov.add_argument("-o", "--output", default="cover_16x9.png")
    p_cov.add_argument("--out-4x3", default=None)
    p_cov.add_argument("--art", default=None)
    p_cov.add_argument("--sentence-id", type=int, default=None)
    p_cov.add_argument("--style", choices=sorted(COVER_STYLES.keys()), default="dark_museum")
    _add_font_args(p_cov)
    p_cov.set_defaults(func=_cmd_cover)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
