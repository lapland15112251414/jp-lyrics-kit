"""Unified dual-buffer timeline computation for seamless switching and interlude clearing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimelineSegment:
    """One contiguous display segment in the dual-buffer lyrics timeline."""

    kind: str  # "blank" or "card"
    start: float
    end: float
    sentence_id: int | None = None
    next_sentence_id: int | None = None
    prev_sentence_id: int | None = None
    seamless_from_prev: bool = False
    description: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 <= edge0:
        return 1.0 if x >= edge1 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def build_timeline(
    song_data: dict[str, Any],
    interlude_gap: float = 12.0,
    min_hold: float = 7.5,
    interlude_tail_margin: float = 4.0,
    outro_tail_hold: float = 10.0,
) -> list[TimelineSegment]:
    """
    Build deterministic dual-buffer card display segments.

    Behavior matches the verified 3-song teaching standard:
    - Holds each sentence continuously until the next sentence starts (seamless switch)
      whenever the gap between consecutive start times <= `interlude_gap`.
    - During long instrumental interludes (`gap > interlude_gap`), holds the active
      card long enough for reading (`min(gap - margin, max(sing_dur + 2.5, min_hold))`),
      then clears to blank so the background stage can breathe cleanly.
    """
    sentences = song_data["sentences"]
    total_duration = float(song_data["meta"]["duration"])
    segments: list[TimelineSegment] = []

    if not sentences:
        if total_duration > 0:
            segments.append(TimelineSegment("blank", 0.0, total_duration, description="Empty Blank"))
        return segments

    intro_start = float(sentences[0]["start"])
    if intro_start > 0.05:
        segments.append(TimelineSegment("blank", 0.0, intro_start, description="Intro Blank"))
    elif intro_start > 0.0:
        segments.append(TimelineSegment("blank", 0.0, intro_start, description="Intro Micro Blank"))

    prev_was_card = False
    prev_sid: int | None = None

    for idx, sent in enumerate(sentences):
        sid = int(sent["id"])
        cur_start = float(sent["start"])
        cur_end = float(sent["end"])
        next_sent = sentences[idx + 1] if idx + 1 < len(sentences) else None
        next_sid = int(next_sent["id"]) if next_sent is not None else None

        if next_sent is not None:
            next_start = float(next_sent["start"])
            gap = next_start - cur_start
            if gap > interlude_gap:
                sing_dur = max(0.5, cur_end - cur_start)
                reading_dur = min(gap - interlude_tail_margin, max(sing_dur + 2.5, min_hold))
                reading_dur = max(min(gap, sing_dur), reading_dur)
                hold_end = min(next_start, cur_start + reading_dur)
                segments.append(
                    TimelineSegment(
                        kind="card",
                        start=cur_start,
                        end=hold_end,
                        sentence_id=sid,
                        next_sentence_id=next_sid,
                        prev_sentence_id=prev_sid if prev_was_card else None,
                        seamless_from_prev=prev_was_card,
                        description=f"Sentence {sid} (Hold before Interlude)",
                    )
                )
                if next_start - hold_end > 0.02:
                    segments.append(
                        TimelineSegment(
                            kind="blank",
                            start=hold_end,
                            end=next_start,
                            description=f"Instrumental Interlude after {sid}",
                        )
                    )
                    prev_was_card = False
                else:
                    prev_was_card = True
            else:
                segments.append(
                    TimelineSegment(
                        kind="card",
                        start=cur_start,
                        end=next_start,
                        sentence_id=sid,
                        next_sentence_id=next_sid,
                        prev_sentence_id=prev_sid if prev_was_card else None,
                        seamless_from_prev=prev_was_card,
                        description=f"Sentence {sid} (Seamless Switch)",
                    )
                )
                prev_was_card = True
        else:
            rem = max(0.0, total_duration - cur_start)
            if rem > max(outro_tail_hold, (cur_end - cur_start) + 4.0):
                hold_dur = max((cur_end - cur_start) + 4.0, outro_tail_hold)
                hold_end = min(total_duration, cur_start + hold_dur)
                segments.append(
                    TimelineSegment(
                        kind="card",
                        start=cur_start,
                        end=hold_end,
                        sentence_id=sid,
                        next_sentence_id=None,
                        prev_sentence_id=prev_sid if prev_was_card else None,
                        seamless_from_prev=prev_was_card,
                        description=f"Sentence {sid} (Outro Hold)",
                    )
                )
                if total_duration - hold_end > 0.02:
                    segments.append(
                        TimelineSegment(
                            kind="blank",
                            start=hold_end,
                            end=total_duration,
                            description="Outro Blank",
                        )
                    )
            else:
                segments.append(
                    TimelineSegment(
                        kind="card",
                        start=cur_start,
                        end=total_duration,
                        sentence_id=sid,
                        next_sentence_id=None,
                        prev_sentence_id=prev_sid if prev_was_card else None,
                        seamless_from_prev=prev_was_card,
                        description=f"Sentence {sid} (Outro)",
                    )
                )
            prev_was_card = True

        prev_sid = sid

    return segments


def card_visibility_at(segments: list[TimelineSegment], t_sec: float, fade_sec: float = 0.8) -> float:
    """
    Compute smooth [0.0, 1.0] card presence factor at `t_sec` for automatic
    lower-third sanctuary darkening over animated backgrounds.
    """
    if not segments:
        return 0.0

    for idx, seg in enumerate(segments):
        if seg.start <= t_sec < seg.end:
            if seg.kind == "card":
                vis = 1.0
                if not seg.seamless_from_prev:
                    vis = min(vis, _smoothstep(seg.start - fade_sec * 0.6, seg.start + fade_sec * 0.4, t_sec))
                if idx + 1 < len(segments) and segments[idx + 1].kind == "blank":
                    vis = min(vis, 1.0 - _smoothstep(seg.end - fade_sec * 0.7, seg.end, t_sec))
                return vis
            vis = 0.0
            if idx - 1 >= 0 and segments[idx - 1].kind == "card":
                vis = max(vis, 1.0 - _smoothstep(seg.start, seg.start + fade_sec * 0.5, t_sec))
            if idx + 1 < len(segments) and segments[idx + 1].kind == "card":
                vis = max(vis, _smoothstep(seg.end - fade_sec * 0.6, seg.end, t_sec))
            return vis

    # At exact end of timeline
    last = segments[-1]
    return 1.0 if (last.kind == "card" and t_sec <= last.end) else 0.0
