"""Unit and end-to-end regression tests for jp_lyrics_kit."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import numpy as np

from jp_lyrics_kit.alpha_exporter import export_alpha_mov
from jp_lyrics_kit.audio_env import extract_audio_envelopes, load_envelopes
from jp_lyrics_kit.bg_engine import render_master_video
from jp_lyrics_kit.card_renderer import FontPack, batch_render_cards, find_font, render_single_card
from jp_lyrics_kit.cli import main as cli_main
from jp_lyrics_kit.cover_gen import generate_covers
from jp_lyrics_kit.drafter import draft_song_data
from jp_lyrics_kit.schema import load_song_data, resolve_pos_palette, save_song_data, validate_song_data
from jp_lyrics_kit.timeline import build_timeline, card_visibility_at
from jp_lyrics_kit.workbench import build_workbench_html


class TestExistingSongsRegression(unittest.TestCase):
    """Verify optional extra song JSONs supplied via JP_LYRICS_KIT_EXTRA_SONGS."""

    def test_validate_extra_songs(self) -> None:
        raw = os.environ.get("JP_LYRICS_KIT_EXTRA_SONGS", "").strip()
        if not raw:
            return
        for path in [p for p in raw.split(os.pathsep) if p.strip()]:
            if not os.path.exists(path):
                continue
            data = load_song_data(path)
            errors, warnings = validate_song_data(data, strict=True)
            self.assertEqual(errors, [], f"{path} errors: {errors}")
            self.assertEqual(warnings, [], f"{path} warnings: {warnings}")
            segs = build_timeline(data)
            self.assertGreater(len(segs), len(data["sentences"]))
            total_tl = sum(s.duration for s in segs)
            self.assertAlmostEqual(total_tl, float(data["meta"]["duration"]), delta=0.5)


class TestDrafterAndPipeline(unittest.TestCase):
    """End-to-end tests for offline drafter, adaptive card fitting, workbench, alpha MOV, render & cover."""

    def test_drafter_lrc_and_ateji(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lrc = os.path.join(tmp, "netease_lrc.txt")
            tlyric = os.path.join(tmp, "netease_tlyric.txt")
            with open(lrc, "w", encoding="utf-8") as f:
                f.write("[00:00.00] 作词 : 测试\n")
                f.write("[00:02.00]此の扉（ドア）なら破れない\n")
                f.write("[00:05.50]誰かに巧いお菓子を\n")
            with open(tlyric, "w", encoding="utf-8") as f:
                f.write("[00:02.00]只要是这扇门便不会被撞破\n")
                f.write("[00:05.50]谁能给我美味的糖果\n")

            draft = draft_song_data(lrc, title="テスト", artist="Tester", tlyric_path=tlyric, duration=10.0)
            errors, _ = validate_song_data(draft, strict=False)
            self.assertEqual(errors, [])
            self.assertEqual(len(draft["sentences"]), 2)
            s1, s2 = draft["sentences"]
            self.assertAlmostEqual(s1["start"], 2.0, places=2)
            self.assertIn("只要是这扇门", s1["trans"])
            door_tok = [t for t in s1["tokens"] if t["word"] == "扉"][0]
            self.assertEqual(door_tok["kana"], "ドア")
            self.assertTrue(door_tok["needs_review"])
            # Pedagogical merger checks
            words_s2 = [t["word"] for t in s2["tokens"]]
            self.assertIn("誰か", words_s2)
            self.assertIn("お菓子", words_s2)

    def test_long_sentence_card_no_crash_and_full_smoke_render(self) -> None:
        dense_song = {
            "meta": {"title": "検証曲", "artist": "テスト", "album": "Test", "duration": 6.0},
            "sentences": [
                {
                    "id": 1,
                    "start": 0.5,
                    "end": 2.8,
                    "trans": "「这是一句用来验证十二个词素自动缩放防溢出的极长测试句」",
                    "tokens": [
                        {"romaji": "ko re wa", "kana": "これは", "word": "此れは", "pos": "代词+提示助词", "gloss": "这个呀", "type": "noun"},
                        {"romaji": "to te mo", "kana": "とても", "word": "とても", "pos": "程度副词", "gloss": "非常", "type": "adv"},
                        {"romaji": "na ga i", "kana": "ながい", "word": "長い", "pos": "形1[長い]连体", "gloss": "漫长的", "type": "adj"},
                        {"romaji": "ka shi", "kana": "かし", "word": "歌詞", "pos": "名词", "gloss": "歌词", "type": "noun"},
                        {"romaji": "no", "kana": "の", "word": "の", "pos": "格助词(属格)", "gloss": "的", "type": "particle"},
                        {"romaji": "bu n ka i", "kana": "ぶんかい", "word": "分解", "pos": "サ变名词", "gloss": "拆解", "type": "noun"},
                        {"romaji": "te su to", "kana": "テスト", "word": "テスト", "pos": "外来名词", "gloss": "测试", "type": "noun"},
                        {"romaji": "de", "kana": "で", "word": "で", "pos": "格助词(手段)", "gloss": "用…", "type": "particle"},
                        {"romaji": "a ru", "kana": "ある", "word": "有る", "pos": "动1[有る]连体", "gloss": "存在", "type": "verb"},
                        {"romaji": "ka ra", "kana": "から", "word": "から", "pos": "接续助词", "gloss": "因为", "type": "particle"},
                        {"romaji": "yo u", "kana": "よう", "word": "様", "pos": "助动词", "gloss": "好像", "type": "aux"},
                        {"romaji": "da", "kana": "だ", "word": "だ", "pos": "断定助动词", "gloss": "是", "type": "aux"},
                    ],
                },
                {
                    "id": 2,
                    "start": 3.0,
                    "end": 5.5,
                    "trans": "「第二句测试接力切换」",
                    "tokens": [
                        {"romaji": "tsu gi", "kana": "つぎ", "word": "次", "pos": "名词", "gloss": "下一句", "type": "noun"},
                        {"romaji": "e", "kana": "へ", "word": "へ", "pos": "格助词", "gloss": "向着", "type": "particle"},
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "song.json")
            save_song_data(dense_song, json_path)
            loaded = load_song_data(json_path)
            errs, warns = validate_song_data(loaded, strict=True)
            self.assertEqual(errs, [])
            self.assertEqual(warns, [])

            # Generate synthetic 6s 440Hz WAV audio via FFmpeg
            wav_path = os.path.join(tmp, "tone.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6.0", "-ar", "48000", wav_path],
                check=True,
                capture_output=True,
            )

            # Card render + visibility check
            pal = resolve_pos_palette(loaded)
            img = render_single_card(loaded["sentences"][0], pal, slot_type="active", theme="kalk_crimson")
            self.assertEqual(img.size, (1920, 1080))
            cards = batch_render_cards(loaded, os.path.join(tmp, "cards"))
            self.assertTrue(os.path.exists(cards["active"][1]))

            # Workbench HTML (must be 100% offline-self-contained)
            wb_path = build_workbench_html(loaded, os.path.join(tmp, "workbench.html"), audio_path=wav_path)
            self.assertTrue(os.path.exists(wb_path))
            with open(wb_path, "r", encoding="utf-8") as f:
                wb_html = f.read()
            self.assertNotIn("cdn.tailwindcss.com", wb_html)
            self.assertIn("escapeHtml", wb_html)

            # Audio envelope + visibility curve
            env_npz = extract_audio_envelopes(wav_path, os.path.join(tmp, "env.npz"), fps=30, duration=6.0)
            envs = load_envelopes(env_npz)
            self.assertEqual(len(envs["env_rms"]), 180)
            tl = build_timeline(loaded)
            self.assertGreater(card_visibility_at(tl, 1.5), 0.9)

            # Alpha MOV (concat + smooth)
            mov_path = export_alpha_mov(loaded, os.path.join(tmp, "alpha.mov"), work_dir=tmp, mode="concat", fps=30)
            self.assertTrue(os.path.exists(mov_path))
            self.assertGreater(os.path.getsize(mov_path), 1024)

            mov_smooth = export_alpha_mov(loaded, os.path.join(tmp, "alpha_smooth.mov"), work_dir=tmp, mode="smooth", fps=15)
            self.assertTrue(os.path.exists(mov_smooth))
            self.assertGreater(os.path.getsize(mov_smooth), 1024)

            # Master render (2s clip @ 30fps with preview PNGs + bg_only)
            out_mp4 = os.path.join(tmp, "master.mp4")
            bg_mp4 = os.path.join(tmp, "bg_only.mp4")
            prev_dir = os.path.join(tmp, "previews")
            render_master_video(
                loaded,
                audio_path=wav_path,
                output_mp4=out_mp4,
                bg_mode="preset",
                bg_preset="astrolabe_botanical",
                envelopes_npz=env_npz,
                fps=30,
                bg_only_mp4=bg_mp4,
                preview_dir=prev_dir,
                preview_times=[0.8, 3.05],
                max_duration=2.0,
            )
            self.assertTrue(os.path.exists(out_mp4))
            self.assertTrue(os.path.exists(bg_mp4))
            self.assertGreater(os.path.getsize(out_mp4), 10240)
            self.assertTrue(os.path.exists(os.path.join(prev_dir, "preview_003.05s.png")))

            # External video background mode
            ext_mp4 = os.path.join(tmp, "ext_master.mp4")
            render_master_video(
                loaded,
                audio_path=wav_path,
                output_mp4=ext_mp4,
                bg_mode="external",
                bg_video_path=bg_mp4,
                fps=30,
                max_duration=1.0,
            )
            self.assertTrue(os.path.exists(ext_mp4))

            # Custom plugin background mode
            plugin_py = os.path.join(tmp, "custom_scene.py")
            with open(plugin_py, "w", encoding="utf-8") as f:
                f.write(
                    "import numpy as np\n"
                    "def render_frame(t, env, song_data, vis):\n"
                    "    arr = np.zeros((1080, 1920, 3), dtype=np.uint8)\n"
                    "    arr[:, :] = (30, 20, 40)\n"
                    "    return arr\n"
                )
            plug_mp4 = os.path.join(tmp, "plugin_master.mp4")
            render_master_video(
                loaded,
                audio_path=wav_path,
                output_mp4=plug_mp4,
                bg_mode="plugin",
                plugin_path=plugin_py,
                envelopes_npz=env_npz,
                fps=30,
                max_duration=1.0,
            )
            self.assertTrue(os.path.exists(plug_mp4))

            # Covers
            c16 = os.path.join(tmp, "cover_16x9.png")
            c43 = os.path.join(tmp, "cover_4x3.png")
            generate_covers(loaded, c16, c43, style="dark_museum")
            self.assertTrue(os.path.exists(c16))
            self.assertTrue(os.path.exists(c43))


class TestOpenSourceReadiness(unittest.TestCase):
    """Verify doctor preflight, cross-platform font overrides, and bundled minimal_demo."""

    def test_doctor_and_font_overrides(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(["doctor", "--json"])
        self.assertEqual(rc, 0)
        report = json.loads(buf.getvalue())
        self.assertTrue(report["ok"])
        self.assertTrue(all(report["fonts"].values()))

        resolved = FontPack.resolve()
        # Env var override should take precedence over defaults
        with mock.patch.dict(os.environ, {"JP_LYRICS_KIT_FONT_JP_BOLD": resolved.jp_reg}):
            env_pack = FontPack.resolve()
            self.assertEqual(env_pack.jp_bold, resolved.jp_reg)

        # Missing explicit font override fails loudly instead of silently falling back
        with self.assertRaises(FileNotFoundError):
            find_font((), override="/nonexistent/missing_font.ttf", role="test")

    def test_minimal_demo_and_cli_font_flags(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        demo_dir = os.path.join(repo_root, "examples", "minimal_demo")
        demo_json = os.path.join(demo_dir, "song.json")
        demo_lrc = os.path.join(demo_dir, "lyrics.lrc")
        demo_tlyric = os.path.join(demo_dir, "tlyric.lrc")

        data = load_song_data(demo_json)
        errors, warnings = validate_song_data(data, strict=True)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        draft = draft_song_data(
            demo_lrc,
            title="星灯りの詩 (Demo)",
            artist="Sample Vocal",
            tlyric_path=demo_tlyric,
            duration=8.0,
        )
        self.assertEqual(len(draft["sentences"]), 2)
        sora_tok = [t for t in draft["sentences"][1]["tokens"] if t["word"] == "蒼空"][0]
        self.assertEqual(sora_tok["kana"], "そら")

        pack = FontPack.resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cards_dir = os.path.join(tmp, "cards")
            cov16 = os.path.join(tmp, "cov_16x9.png")
            rc_cards = cli_main(
                [
                    "cards",
                    demo_json,
                    "-o",
                    cards_dir,
                    "--font-jp-bold",
                    pack.jp_bold,
                    "--font-cn-reg",
                    pack.cn_reg,
                ]
            )
            self.assertEqual(rc_cards, 0)
            self.assertTrue(os.path.exists(os.path.join(cards_dir, "card_01_active.png")))

            rc_cov = cli_main(
                [
                    "cover",
                    demo_json,
                    "-o",
                    cov16,
                    "--font-jp-bold",
                    pack.jp_bold,
                    "--font-cn-bold",
                    pack.cn_bold,
                ]
            )
            self.assertEqual(rc_cov, 0)
            self.assertTrue(os.path.exists(cov16))


if __name__ == "__main__":
    unittest.main()
