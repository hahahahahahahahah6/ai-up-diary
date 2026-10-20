# -*- coding: utf-8 -*-
"""
tts_engine.py — per-line speech with edge-tts (free, no API key).

edge-tts is OPTIONAL. If it is not installed, or synthesis fails (offline,
blocked endpoint), every line falls back to a silent duration estimated from
its length, and the video renders without a voice track.

Voices worth trying for a cute host: zh-CN-XiaoyiNeural (lively),
zh-CN-XiaoxiaoNeural (default, clear). List all: `edge-tts --list-voices`.
"""
import asyncio
import subprocess
from pathlib import Path

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "+8%"     # a touch faster sounds more energetic
DEFAULT_PITCH = "+6Hz"   # a touch higher sounds younger


def _probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return None


def estimate_duration(text):
    """Rough spoken length for Chinese text: ~0.19s per character + lead-in."""
    return 0.7 + len(text) * 0.19


async def _synth_all(lines, voice, rate, pitch, workdir):
    import edge_tts  # lazy: absence must not break anything
    results, fails = [], 0
    for i, line in enumerate(lines):
        path = workdir / f"line_{i:02d}.mp3"
        if fails >= 2:  # endpoint is down - stop waiting on timeouts
            results.append(None)
            continue
        try:
            await asyncio.wait_for(
                edge_tts.Communicate(line["text"], voice, rate=rate,
                                     pitch=pitch).save(str(path)),
                timeout=30)
            results.append(path)
            fails = 0
        except Exception:
            fails += 1
            if path.exists():
                path.unlink()
            results.append(None)
    return results


def synthesize_lines(lines, workdir, voice=DEFAULT_VOICE, rate=DEFAULT_RATE,
                     pitch=DEFAULT_PITCH):
    """
    Returns (items, voice_ok) where items is a list of
    (audio_path_or_None, duration_seconds) aligned with `lines`.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        import edge_tts  # noqa: F401
        paths = asyncio.run(_synth_all(lines, voice, rate, pitch, workdir))
    except ImportError:
        paths = [None] * len(lines)
    except Exception as e:
        print(f"  TTS error: {e}")
        paths = [None] * len(lines)

    items, any_voice = [], False
    for line, path in zip(lines, paths):
        dur = _probe_duration(path) if path else None
        if dur and dur > 0:
            items.append((path, dur))
            any_voice = True
        else:
            items.append((None, estimate_duration(line["text"])))
    return items, any_voice
