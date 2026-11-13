"""Multi-band audio envelope extraction (sub, mid, high, rms, flux) for visual driving."""

from __future__ import annotations

import os
import subprocess

import numpy as np

from .schema import ensure_binary, probe_audio_duration


def _smooth_norm(arr: np.ndarray, attack: float, release: float) -> np.ndarray:
    p99 = float(np.percentile(arr, 99.2)) + 1e-6
    normed = np.clip(arr / p99, 0.0, 1.25)
    out = np.zeros_like(normed, dtype=np.float32)
    cur = 0.0
    for i, val in enumerate(normed):
        coef = attack if val > cur else release
        cur = cur + coef * (float(val) - cur)
        out[i] = cur
    return out


def extract_audio_envelopes(
    audio_path: str,
    out_npz: str,
    fps: int = 60,
    duration: float | None = None,
) -> str:
    """
    Decode audio via FFmpeg and compute smoothed 4-band + spectral flux envelopes at `fps`.
    Saves `env_sub`, `env_mid`, `env_high`, `env_rms`, `env_flux`, and `fps` to `out_npz`.
    """
    ffmpeg_bin = ensure_binary("ffmpeg")
    if duration is None:
        duration = probe_audio_duration(audio_path)

    total_frames = max(1, int(round(duration * fps)))
    sr = 24000
    cmd = [
        ffmpeg_bin, "-v", "error",
        "-i", audio_path,
        "-ac", "1",
        "-ar", str(sr),
        "-f", "f32le",
        "-",
    ]
    raw = subprocess.check_output(cmd)
    samples = np.frombuffer(raw, dtype=np.float32)

    hop = max(1, sr // fps)
    win_size = 1024
    hann = np.hanning(win_size).astype(np.float32)
    freqs = np.fft.rfftfreq(win_size, d=1.0 / sr)

    idx_sub = (freqs >= 20) & (freqs <= 180)
    idx_mid = (freqs > 180) & (freqs <= 2400)
    idx_high = (freqs > 2400) & (freqs <= 11000)

    env_sub = np.zeros(total_frames, dtype=np.float32)
    env_mid = np.zeros(total_frames, dtype=np.float32)
    env_high = np.zeros(total_frames, dtype=np.float32)
    env_rms = np.zeros(total_frames, dtype=np.float32)
    env_flux = np.zeros(total_frames, dtype=np.float32)

    prev_spec: np.ndarray | None = None
    for f in range(total_frames):
        center = f * hop
        start = max(0, center - win_size // 2)
        end = start + win_size
        if end > len(samples):
            chunk = np.zeros(win_size, dtype=np.float32)
            valid = samples[start:]
            chunk[: len(valid)] = valid
        else:
            chunk = samples[start:end]

        env_rms[f] = float(np.sqrt(np.mean(chunk ** 2) + 1e-8))
        spec = np.abs(np.fft.rfft(chunk * hann))
        env_sub[f] = float(np.mean(spec[idx_sub])) if np.any(idx_sub) else 0.0
        env_mid[f] = float(np.mean(spec[idx_mid])) if np.any(idx_mid) else 0.0
        env_high[f] = float(np.mean(spec[idx_high])) if np.any(idx_high) else 0.0
        if prev_spec is not None:
            diff = np.maximum(0.0, spec - prev_spec)
            env_flux[f] = float(np.mean(diff))
        prev_spec = spec

    env_sub = _smooth_norm(env_sub, 0.50, 0.14)
    env_mid = _smooth_norm(env_mid, 0.35, 0.10)
    env_high = _smooth_norm(env_high, 0.60, 0.16)
    env_rms = _smooth_norm(env_rms, 0.40, 0.12)
    env_flux = _smooth_norm(env_flux, 0.65, 0.22)

    out_dir = os.path.dirname(os.path.abspath(out_npz))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    np.savez(
        out_npz,
        env_sub=env_sub,
        env_mid=env_mid,
        env_high=env_high,
        env_rms=env_rms,
        env_flux=env_flux,
        fps=np.array([fps], dtype=np.int32),
    )
    return out_npz


def load_envelopes(npz_path: str) -> dict[str, np.ndarray]:
    """Load saved audio envelope arrays from an `.npz` file."""
    data = np.load(npz_path)
    return {k: data[k] for k in data.files}
