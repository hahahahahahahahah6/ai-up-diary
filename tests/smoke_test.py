# -*- coding: utf-8 -*-
"""
Smoke test: render a tiny 3-line episode in demo conditions and verify the
MP4 is real (exists, non-trivial size, valid duration via ffprobe).

Run from the project root:  python tests/smoke_test.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent

TINY_SCRIPT = [
    {"text": "你们好，我是小克，这是冒烟测试。", "expression": "neutral", "pause": 0.3},
    {"text": "三句话，验证整条流水线能跑通。", "expression": "happy", "pause": 0.3},
    {"text": "评论区见，明天见！", "expression": "smug", "pause": 0.3},
]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        script_file = tmp / "tiny.json"
        script_file.write_text(json.dumps(TINY_SCRIPT, ensure_ascii=False),
                               encoding="utf-8")
        out_dir = tmp / "out"
        cmd = [sys.executable, str(ROOT / "diary.py"),
               "--script", str(script_file), "--day", "999",
               "--out", str(out_dir), "--skip-memory", "--no-tts"]
        print("+", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr)
            raise AssertionError(f"diary.py exited with {proc.returncode}")

        mp4 = out_dir / "day-999.mp4"
        assert mp4.exists(), "MP4 was not created"
        size = mp4.stat().st_size
        assert size > 20_000, f"MP4 suspiciously small: {size} bytes"
        post = out_dir / "day-999-post.txt"
        assert post.exists() and post.stat().st_size > 0, "ledger post missing"

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(mp4)],
            capture_output=True, text=True, timeout=60)
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        stream = info["streams"][0]
        assert duration > 3, f"duration too short: {duration}s"
        assert (stream["width"], stream["height"]) == (1280, 720), stream
        print(f"✅ smoke test passed: {mp4.name} "
              f"{size / 1024:.0f} KiB, {duration:.1f}s, 1280x720")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
