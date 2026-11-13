"""Interactive HTML proofreading workbench generator with audio sync & review highlights."""

from __future__ import annotations

import html
import json
import os
from typing import Any

from .schema import DEFAULT_POS_COLORS


def build_workbench_html(
    song_data: dict[str, Any],
    output_html: str,
    audio_path: str | None = None,
) -> str:
    """
    Generate a self-contained HTML 5+1 card inspection & audio-sync proofing workbench.
    """
    meta = song_data["meta"]
    sentences = song_data["sentences"]
    colors = song_data.get("colors") or DEFAULT_POS_COLORS

    json_sentences = json.dumps(sentences, ensure_ascii=False)
    json_colors = json.dumps(colors, ensure_ascii=False)

    audio_rel = ""
    if audio_path and os.path.exists(audio_path):
        out_dir = os.path.dirname(os.path.abspath(output_html))
        try:
            audio_rel = os.path.relpath(os.path.abspath(audio_path), out_dir).replace("\\", "/")
        except ValueError:
            audio_rel = "file:///" + os.path.abspath(audio_path).replace("\\", "/")

    legend_html = "\n".join(
        f'<span class="legend-item">'
        f'<span class="legend-dot" style="background:{html.escape(v["hex"])}"></span>'
        f'{html.escape(v["name"])}</span>'
        for v in colors.values()
        if isinstance(v, dict) and "hex" in v and "name" in v
    )

    audio_block = (
        f'<div class="audio-bar">'
        f'<span class="audio-label">音频同步试听</span>'
        f'<audio id="audioPlayer" controls class="audio-player" src="{html.escape(audio_rel)}"></audio>'
        f'<button id="jumpAudioBtn" class="btn btn-amber">跳到当前句</button>'
        f"</div>"
        if audio_rel
        else ""
    )

    title_esc = html.escape(str(meta.get("title", "")))
    artist_esc = html.escape(str(meta.get("artist", "")))
    album_esc = html.escape(str(meta.get("album", "")))
    draft_badge = (
        '<span class="draft-badge">DRAFT / 含待校对项</span>'
        if meta.get("draft")
        else ""
    )

    content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{artist_esc}《{title_esc}》5+1 歌词精解校对台</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #020617;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Microsoft YaHei", sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 16px;
      user-select: none;
    }}
    .shell {{
      background: rgba(15, 23, 42, 0.96);
      border: 1px solid rgba(245, 158, 11, 0.35);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 24px 48px rgba(0, 0, 0, 0.55);
      max-width: 1024px;
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 12px;
    }}
    .title-row {{ font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }}
    .subtitle {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
    .draft-badge {{
      padding: 2px 8px;
      font-size: 10px;
      border-radius: 4px;
      background: rgba(245, 158, 11, 0.2);
      color: #fcd34d;
      border: 1px solid rgba(245, 158, 11, 0.4);
    }}
    .controls {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    select {{
      background: #1e293b;
      color: #e2e8f0;
      font-size: 12px;
      padding: 6px 10px;
      border-radius: 8px;
      border: 1px solid #334155;
      max-width: 280px;
    }}
    .btn {{
      padding: 6px 12px;
      font-size: 12px;
      border-radius: 8px;
      border: 1px solid #334155;
      background: transparent;
      color: #cbd5e1;
      cursor: pointer;
      flex-shrink: 0;
    }}
    .btn:hover {{ background: #1e293b; }}
    .btn-primary {{ background: #be123c; border-color: #be123c; color: #fff; font-weight: 600; }}
    .btn-primary:hover {{ background: #e11d48; }}
    .btn-amber {{ background: #d97706; border-color: #d97706; color: #fff; font-weight: 600; }}
    .btn-amber:hover {{ background: #f59e0b; }}
    .audio-bar {{
      display: flex;
      align-items: center;
      gap: 12px;
      background: rgba(2, 6, 23, 0.8);
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 8px 12px;
    }}
    .audio-label {{ font-size: 12px; color: #fcd34d; font-weight: 600; flex-shrink: 0; }}
    .audio-player {{ width: 100%; height: 32px; }}
    .card {{
      border-radius: 12px;
      padding: 14px;
    }}
    .card-active {{
      background: #ffffff;
      color: #1e293b;
      border: 2px solid rgba(245, 158, 11, 0.65);
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
    }}
    .card-buffer {{
      background: rgba(241, 245, 249, 0.95);
      color: #334155;
      border: 1px dashed #cbd5e1;
      opacity: 0.92;
    }}
    .card-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
      font-size: 12px;
    }}
    .badge {{
      display: inline-block;
      padding: 2px 10px;
      border-radius: 6px;
      color: #fff;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-weight: 600;
    }}
    .badge-active {{ background: #9f1239; }}
    .badge-buffer {{ background: #64748b; }}
    .time-label {{ font-size: 11px; color: #64748b; font-weight: 500; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; text-align: center; border-collapse: collapse; font-size: 12px; }}
    .cell-border {{ border: 1px solid rgba(226, 232, 240, 0.95); padding: 4px 8px; }}
    .row-th {{ background: #f1f5f9; color: #64748b; font-weight: 500; font-size: 11px; width: 56px; }}
    .tok-romaji {{ color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }}
    .tok-kana {{ color: #475569; font-size: 12px; }}
    .tok-word {{ font-weight: 700; font-size: 14px; letter-spacing: 0.04em; }}
    .tok-pos {{ color: #64748b; font-size: 11px; background: #f8fafc; }}
    .tok-gloss {{ color: #334155; font-size: 12px; font-weight: 500; }}
    .review-cell {{ background-color: rgba(254, 243, 199, 0.8); }}
    .trans-row {{
      margin-top: 10px;
      padding-top: 8px;
      border-top: 1px solid #e2e8f0;
      display: flex;
      align-items: baseline;
      gap: 8px;
    }}
    .trans-label {{ font-size: 12px; font-weight: 700; color: #94a3b8; flex-shrink: 0; }}
    .trans-text {{ font-size: 13px; color: #1e293b; font-weight: 500; font-style: italic; }}
    .card-buffer .trans-text {{ color: #475569; }}
    .footer {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 6px 16px;
      font-size: 12px;
      padding-top: 8px;
      border-top: 1px solid #1e293b;
      color: #94a3b8;
    }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
    .legend-dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .review-hint {{ color: rgba(252, 211, 77, 0.9); margin-left: 8px; }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <div>
        <h2 class="title-row">
          {artist_esc}《{title_esc}》5+1 歌词形态素分解卡片{draft_badge}
        </h2>
        <p class="subtitle">专辑：{album_esc or '—'} ｜ 时长：{float(meta.get('duration', 0)):.2f}s ｜ 共 {len(sentences)} 句</p>
      </div>
      <div class="controls">
        <select id="jumpSelect"></select>
        <button id="prevBtn" class="btn">上一句 (←)</button>
        <button id="nextBtn" class="btn btn-primary">下一句 (→)</button>
      </div>
    </div>

    {audio_block}

    <div id="cardA" class="card card-active">
      <div class="card-head">
        <span class="badge badge-active" id="cardAIndex">句 1</span>
        <span class="time-label" id="cardATime"></span>
      </div>
      <div class="table-wrap">
        <table><tbody id="cardABody"></tbody></table>
      </div>
      <div class="trans-row">
        <span class="trans-label">文学意译</span>
        <p class="trans-text" id="cardATrans"></p>
      </div>
    </div>

    <div id="cardB" class="card card-buffer">
      <div class="card-head">
        <span class="badge badge-buffer" id="cardBIndex">下句预读</span>
        <span class="time-label" id="cardBTime"></span>
      </div>
      <div class="table-wrap">
        <table><tbody id="cardBBody"></tbody></table>
      </div>
      <div class="trans-row">
        <span class="trans-label">文学意译</span>
        <p class="trans-text" id="cardBTrans"></p>
      </div>
    </div>

    <div class="footer">
      <span style="color:#cbd5e1;font-weight:600">词性配色：</span>
      {legend_html}
      <span class="review-hint">（浅黄底格 = 标记待人工/AI复核）</span>
    </div>
  </div>

  <script>
    const songData = {json_sentences};
    const posColors = {json_colors};
    let currentIndex = 0;

    function escapeHtml(val) {{
      return String(val ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function formatTime(s) {{
      const m = Math.floor(s / 60);
      const sec = (s % 60).toFixed(2);
      return `${{String(m).padStart(2, '0')}}:${{String(sec).padStart(5, '0')}}`;
    }}

    function renderCard(bodyId, idxId, timeId, transId, data, isSlotB) {{
      if (!data) {{
        document.getElementById(idxId).innerText = isSlotB ? "已至曲末" : "—";
        document.getElementById(timeId).innerText = "";
        document.getElementById(transId).innerText = "";
        document.getElementById(bodyId).innerHTML = "";
        return;
      }}
      document.getElementById(idxId).innerText = `句 ${{data.id}}${{isSlotB ? ' (下句预读)' : ''}}`;
      document.getElementById(timeId).innerText = isSlotB
        ? `即将接力 [${{formatTime(data.start)}}]`
        : `当前唱段 [${{formatTime(data.start)}} ~ ${{formatTime(data.end)}}]`;
      document.getElementById(transId).innerText = data.trans || "";

      const rows = [
        {{ label: "发音", key: "romaji", cls: "tok-romaji" }},
        {{ label: "假名", key: "kana", cls: "tok-kana" }},
        {{ label: "单词", key: "word", isWord: true }},
        {{ label: "语法", key: "pos", cls: "tok-pos" }},
        {{ label: "字义", key: "gloss", cls: "tok-gloss" }}
      ];

      const htmlStr = rows.map(r => {{
        const cells = data.tokens.map(t => {{
          const content = escapeHtml(t[r.key] || "");
          const reviewCls = t.needs_review ? "review-cell" : "";
          const titleAttr = t.note ? `title="${{escapeHtml(t.note)}}"` : "";
          if (r.isWord) {{
            const clr = escapeHtml((posColors[t.type] && posColors[t.type].hex) || "#1e293b");
            return `<td ${{titleAttr}} class="cell-border tok-word ${{reviewCls}}" style="color:${{clr}}">${{content}}</td>`;
          }}
          return `<td ${{titleAttr}} class="cell-border ${{r.cls}} ${{reviewCls}}">${{content}}</td>`;
        }}).join("");
        return `<tr><th class="cell-border row-th">${{r.label}}</th>${{cells}}</tr>`;
      }}).join("");

      document.getElementById(bodyId).innerHTML = htmlStr;
    }}

    function update() {{
      const cur = songData[currentIndex];
      const nxt = currentIndex + 1 < songData.length ? songData[currentIndex + 1] : null;
      renderCard("cardABody", "cardAIndex", "cardATime", "cardATrans", cur, false);
      renderCard("cardBBody", "cardBIndex", "cardBTime", "cardBTrans", nxt, true);
      document.getElementById("jumpSelect").value = currentIndex;
    }}

    const select = document.getElementById("jumpSelect");
    songData.forEach((s, idx) => {{
      const opt = document.createElement("option");
      opt.value = idx;
      opt.innerText = `句 ${{s.id}} [${{formatTime(s.start)}}]: ${{s.tokens.map(t => t.word).join('')}}`;
      select.appendChild(opt);
    }});

    select.addEventListener("change", (e) => {{
      currentIndex = parseInt(e.target.value, 10);
      update();
    }});
    document.getElementById("prevBtn").addEventListener("click", () => {{
      currentIndex = (currentIndex - 1 + songData.length) % songData.length;
      update();
    }});
    document.getElementById("nextBtn").addEventListener("click", () => {{
      currentIndex = (currentIndex + 1) % songData.length;
      update();
    }});
    window.addEventListener("keydown", (e) => {{
      if (e.key === "ArrowLeft") document.getElementById("prevBtn").click();
      if (e.key === "ArrowRight") document.getElementById("nextBtn").click();
    }});

    const audio = document.getElementById("audioPlayer");
    if (audio) {{
      document.getElementById("jumpAudioBtn").addEventListener("click", () => {{
        if (songData[currentIndex]) {{
          audio.currentTime = songData[currentIndex].start;
          audio.play();
        }}
      }});
      audio.addEventListener("timeupdate", () => {{
        const t = audio.currentTime;
        for (let i = songData.length - 1; i >= 0; i--) {{
          if (t >= songData[i].start - 0.05) {{
            if (currentIndex !== i) {{
              currentIndex = i;
              update();
            }}
            break;
          }}
        }}
      }});
    }}

    update();
  </script>
</body>
</html>
"""
    parent = os.path.dirname(os.path.abspath(output_html))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(content)
    return output_html
