# Minimal Smoke-Test Demo

This 8-second original demo lets you verify `jp-lyrics-kit` end-to-end without external copyrighted audio.

```bash
# 1. Check FFmpeg, Python deps, and system CJK fonts
python -m jp_lyrics_kit doctor

# 2. Test offline morphological drafting from LRC + tlyric
python -m jp_lyrics_kit draft \
  --lyrics examples/minimal_demo/lyrics.lrc \
  --tlyric examples/minimal_demo/tlyric.lrc \
  --title "星灯りの詩 (Demo)" --artist "Sample Vocal" --duration 8.0 \
  -o /tmp/demo.draft.json

# 3. Strictly validate the refined song.json and open the HTML proofing workbench
python -m jp_lyrics_kit validate examples/minimal_demo/song.json --strict
python -m jp_lyrics_kit preview examples/minimal_demo/song.json -o /tmp/demo_workbench.html

# 4. Generate a synthetic 8s test tone and render a master video + cover PNGs
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=8.0" -ar 48000 /tmp/demo.wav
python -m jp_lyrics_kit audio-env /tmp/demo.wav -o /tmp/demo_env.npz --fps 30
python -m jp_lyrics_kit render examples/minimal_demo/song.json \
  --audio /tmp/demo.wav --env /tmp/demo_env.npz \
  --bg-mode preset --preset astrolabe_botanical --fps 30 \
  -o /tmp/demo_master.mp4
python -m jp_lyrics_kit cover examples/minimal_demo/song.json -o /tmp/cover_16x9.png --out-4x3 /tmp/cover_4x3.png
```
