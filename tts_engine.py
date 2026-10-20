# -*- coding: utf-8 -*-
"""
tts_engine.py — per-line speech with edge-tts (free, no API key).

edge-tts is OPTIONAL. If it is not installed, or synthesis fails (offline,
blocked endpoint), every line falls back to a silent duration estimated from
its length, and the video renders without a voice track. The caller prints a
note so the user knows why the video is silent.
"""
import asyncio
import subprocess
from pathlib import Path

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
_fail_streak = 0  # give up after 2 consecutive failures instead of stalling


def _probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def estimate_duration(text):
    """Rough spoken length for Chinese text: ~0.19s per character + lead-in."""
    return 0.7 + len(text) * 0.19


async def _synth_one(text, voice, out_path):
    import edge_tts  # imported lazily: absence must not break anything
    await edge_tts.Communicate(text, voice).save(str(out_path))


def synthesize_lines(lines, workdir, voice=DEFAULT_VOICE):
    """
    Returns (items, voice_ok) where items is a list of
    (audio_path_or_None, duration_seconds) aligned with `lines`.
    """
    global _fail_streak
    _fail_streak = 0
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        import edge_tts  # noqa: F401
        available = True
    except ImportError:
        available = False

    items = []
    any_voice = False
    for i, line in enumerate(lines):
        path = workdir / f"line_{i:02d}.mp3"
        dur = None
        if available and _fail_streak < 2:
            try:
                asyncio.run(_synth_one(line["text"], voice, path))
                dur = _probe_duration(path)
                if dur is None or dur <= 0:
                    raise RuntimeError("empty audio")
                _fail_streak = 0
                any_voice = True
            except Exception:
                _fail_streak += 1
                dur = None
                if path.exists():
                    path.unlink()
        if dur is None:
            items.append((None, estimate_duration(line["text"])))
        else:
            items.append((path, dur))
    return items, any_voice
