---
name: jp-lyrics-kit
description: >-
  Build 5+1 Japanese-Chinese dual-buffer lyrics breakdown study videos from audio
  and lyrics using the `jp_lyrics_kit` CLI toolchain. Use when asked to create a
  Japanese lyrics learning video, 5+1 morpheme breakdown cards, dual-buffer alpha
  subtitle tracks, or interactive bilingual lyric study cards (中日双语歌词学习视频 /
  5+1形态素精解 / 歌词对照分解视频).
---

# Japanese Lyrics 5+1 Study Video Workflow (`jp-lyrics-kit`)

Use `python -m jp_lyrics_kit ...` as the deterministic rendering backend, and focus AI reasoning on accurate Japanese morphological grouping, actual sung phonetics (ateji / historical kana), grammar annotation, and literary translation.

## Step 0: Preflight Check & Bootstrap

Always verify the runtime environment before starting a song project:

```bash
python -m jp_lyrics_kit doctor
```

- If `No module named jp_lyrics_kit` occurs, install the Python package from the repository root (`pip install -e <path-to-jp-lyrics-kit>`) or via PyPI (`pip install jp-lyrics-kit`), and re-run `doctor`.
- If `ffmpeg` or `ffprobe` is reported `MISSING`, ask the user to install FFmpeg and add it to `PATH`.
- If CJK fonts are missing on Linux/headless servers, install Noto CJK (`sudo apt install fonts-noto-cjk`) or pass `--font-jp-bold` / `--font-jp-reg` / `--font-cn-bold` / `--font-cn-reg` (or set `JP_LYRICS_KIT_FONT_JP` / `JP_LYRICS_KIT_FONT_CN`).

## Step 1: Initialize Workspace & Draft Skeleton

Scaffold a song directory and run the offline `SudachiPy` + `pykakasi` drafter when lyrics are supplied:

```bash
python -m jp_lyrics_kit init "<project_dir>"
python -m jp_lyrics_kit draft \
  --lyrics "<lyrics_path>" \
  --tlyric "<optional_tlyric_path>" \
  --audio "<audio_path>" \
  --title "<Title>" \
  --artist "<Artist>" \
  --album "<Album>" \
  -o "<project_dir>/song.draft.json"
```

- Supported lyrics formats: `.lrc`, `.srt`, `.txt` (auto-detects LRC timestamps inside `.txt` files as well as plain text).
- If the lyrics file has no timestamps, add `--whisper --whisper-model small` (requires `pip install "jp-lyrics-kit[whisper]"`).

## Step 2: AI Semantic Refinement -> `song.json`

Read `<project_dir>/song.draft.json` and refine it into `<project_dir>/song.json`. Always consult [song_schema.md](./references/song_schema.md) for exact field names and the 7 standard POS categories.

Quality requirements:
1. **Sung Phonetics First**: Preserve literary/historical orthography or kanji in `word` (e.g., `扉`, `蒼空`), while writing the **actual sung pronunciation** in `kana` and `romaji` (e.g., `ドア` / `do a`, or `そら` / `so ra`).
2. **Pedagogical Token Granularity**: Keep meaningful learning units (typically 3–10 tokens per sentence; merge auxiliary verb chains naturally while avoiding monolithic clauses).
3. **Strict 7 POS Categories**: Every `type` must be one of `noun`, `verb`, `particle`, `adj`, `adv`, `prenoun`, `aux`.
4. **Zero Draft Leftovers**: Replace every `[待释义]` and `[待意译]`, remove `needs_review` flags and `meta.draft`, and verify `start <= end` timestamps ascend cleanly within `meta.duration`.

## Step 3: Strict Validation & Proofing Workbench

```bash
python -m jp_lyrics_kit validate "<project_dir>/song.json" --strict
python -m jp_lyrics_kit preview "<project_dir>/song.json" --audio "<audio_path>" -o "<project_dir>/workbench.html"
```

Resolve all reported validation errors before rendering video. Share `workbench.html` with the user whenever lyric timings or sung readings need human sign-off.

## Step 4: Render Video Outputs

Choose the output pipeline requested by the user:

- **Option A — Transparent Alpha Track Only** (for Premiere Pro / CapCut / DaVinci Resolve):
  ```bash
  python -m jp_lyrics_kit alpha "<project_dir>/song.json" --mode concat --fps 30 -o "<project_dir>/alpha_lyrics_track.mov"
  # Use `--mode smooth --fps 60` for animated Slot B -> Slot A upward relay glides
  ```

- **Option B — Built-in Audio-Reactive Preset or External Video**:
  ```bash
  python -m jp_lyrics_kit audio-env "<audio_path>" -o "<project_dir>/audio_envelopes.npz" --fps 60
  python -m jp_lyrics_kit render "<project_dir>/song.json" \
    --audio "<audio_path>" \
    --env "<project_dir>/audio_envelopes.npz" \
    --bg-mode preset --preset astrolabe_botanical \
    --theme kalk_crimson --fps 60 \
    -o "<project_dir>/final_master.mp4"
  ```
  (Pass `--bg-mode external --bg-video "<bg.mp4>"` to composite over an existing video.)

- **Option C — Custom Per-Song Scene Plugin** (best for bespoke narrative or SVG art visuals):
  Implement `ScenePlugin(song_data, envs).render_frame(t, env, card_vis) -> bgr_1080p` in `<project_dir>/scene_plugin.py`. Always render sample previews and a short clip first:
  ```bash
  python -m jp_lyrics_kit render "<project_dir>/song.json" \
    --audio "<audio_path>" --env "<project_dir>/audio_envelopes.npz" \
    --bg-mode plugin --plugin "<project_dir>/scene_plugin.py" \
    --preview-dir "<project_dir>/previews" --preview-times 15 45 90 \
    --max-duration 6 -o "<project_dir>/test_clip.mp4"
  ```
  Inspect the generated preview PNGs visually using your image/file viewing tool before running the full render without `--max-duration`.

## Step 5: Optional 16:9 & 4:3 Covers

```bash
python -m jp_lyrics_kit cover "<project_dir>/song.json" \
  --art "<optional_cover_art>" --style dark_museum \
  -o "<project_dir>/cover_16x9.png" --out-4x3 "<project_dir>/cover_4x3.png"
```
