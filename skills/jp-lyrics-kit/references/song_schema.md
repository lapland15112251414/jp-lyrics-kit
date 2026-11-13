# `song.json` Schema & Theme Reference

## JSON Structure

```json
{
  "meta": {
    "title": "星灯りの詩",
    "artist": "Sample Vocal",
    "album": "Demo Album [2026]",
    "duration": 215.4,
    "style": "5+1 Dual-Buffer Morpheme Breakdown"
  },
  "sentences": [
    {
      "id": 1,
      "start": 12.40,
      "end": 16.85,
      "trans": "「若是那扇未曾言说的门扉，便绝不会被撞破」",
      "tokens": [
        {
          "romaji": "ko no",
          "kana": "この",
          "word": "此の",
          "pos": "连体词(近称)",
          "gloss": "这扇/此",
          "type": "prenoun"
        },
        {
          "romaji": "do a",
          "kana": "ドア",
          "word": "扉",
          "pos": "名词[当て字:ドア]",
          "gloss": "门扉(唱作ドア)",
          "type": "noun"
        }
      ]
    }
  ]
}
```

## Standard POS Types (`tokens[].type`)

| `type` | Meaning | Default Hex |
| :--- | :--- | :--- |
| `noun` | 名词 / 代词 | `#059669` |
| `verb` | 动词活用 | `#0284c7` |
| `particle` | 助词情态 | `#e11d48` |
| `adj` | 形容词 / 形容动词 | `#d97706` |
| `adv` | 副词修饰 | `#db2777` |
| `prenoun` | 连体词 | `#ca8a04` |
| `aux` | 助动词 / 感叹词 | `#9333ea` |

## Available Themes, Presets & Cover Styles

- **Card Themes (`--theme`)**: `kalk_crimson`, `classic_blue`, `dark_museum`
- **Background Presets (`--preset`)**: `astrolabe_botanical`, `twilight_horizon`, `minimal_ink`
- **Cover Styles (`--style`)**: `dark_museum`, `crimson_gold`, `classic_slate`
