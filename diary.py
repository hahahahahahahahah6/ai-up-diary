# -*- coding: utf-8 -*-
"""
diary.py — AI 运营日记生成器 (AI UP Diary): one command, one episode.

Usage:
    python diary.py                 # Day = next day; demo mode if no API key
    python diary.py --day 3         # a specific day
    python diary.py --demo          # force the built-in demo script
    python diary.py --full          # force the Anthropic API (falls back if it fails)
    python diary.py --script s.json # render your own script file

Full mode: set ANTHROPIC_API_KEY, edit persona.md, and drop yesterday's
comments into input/comments.txt and stats into input/stats.json.
Publishing is manual by design: review output/day-<N>.mp4 and upload it
yourself — the AI writes and renders, the human stays the publisher.
"""
import argparse
import json
import os
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import renderer  # noqa: E402
import scriptgen  # noqa: E402
import tts_engine  # noqa: E402
from make_sprites import ensure_sprites  # noqa: E402

STATE_PATH = ROOT / "memory" / "state.json"
LOG_PATH = ROOT / "memory" / "log.md"
DEFAULT_STATE = {
    "day": -1,
    "stats": {"views": 12, "likes": 2, "coins": 0, "favorites": 1, "followers": 3},
    "prev_stats": {},
    "promises": [],
    "gags": ["3 个粉丝里有一个是人类的小号"],
    "history": [],
}


# ---------------------------------------------------------------- state
def load_state():
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            for k, v in DEFAULT_STATE.items():
                state.setdefault(k, v)
            return state
        except Exception:
            print("Warning: memory/state.json is unreadable - starting from defaults.")
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_input_stats():
    p = ROOT / "input" / "stats.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            print("Warning: input/stats.json is not valid JSON - ignoring it.")
    return None


def load_comments():
    p = ROOT / "input" / "comments.txt"
    if p.exists():
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    return []


def simulate_stats_growth(state, day):
    """Demo mode: pretend the account grew a little overnight (deterministic)."""
    rng = random.Random(1000 + day)
    s = dict(state["stats"])
    growth = max(1, day + 1)
    s["views"] = s.get("views", 0) + rng.randint(8, 30) * growth
    s["likes"] = s.get("likes", 0) + rng.randint(1, 9) * growth
    s["coins"] = s.get("coins", 0) + rng.randint(0, 3)
    s["favorites"] = s.get("favorites", 0) + rng.randint(0, 4)
    s["followers"] = s.get("followers", 0) + rng.randint(0, 2 + day // 2)
    return s


# ---------------------------------------------------------------- post
def ledger_post(persona, day, state, lines, api_post=None):
    if api_post:
        return api_post.rstrip() + "\n"
    s = state["stats"]
    prev = state.get("prev_stats") or {}

    def delta(key):
        if key in prev:
            d = s.get(key, 0) - prev.get(key, 0)
            return f" ({'+' if d >= 0 else ''}{d})"
        return ""

    first_topic = lines[1]["text"] if len(lines) > 1 else lines[0]["text"]
    promises = state.get("promises") or []
    promise_line = promises[-1] if promises else "先活过第一周"
    return (
        f"【今日账本 · Day {day}】\n"
        f"大家好，我是{persona['name']}，今天的账本来了，数据全部公开：\n"
        f"播放 {s.get('views', 0)}{delta('views')} · "
        f"点赞 {s.get('likes', 0)}{delta('likes')} · "
        f"投币 {s.get('coins', 0)}{delta('coins')} · "
        f"收藏 {s.get('favorites', 0)}{delta('favorites')} · "
        f"粉丝 {s.get('followers', 0)}{delta('followers')}\n"
        f"今天的视频已经渲染好了，主题是：{first_topic}\n"
        f"目前立着的 flag：{promise_line}\n"
        f"老规矩——评论区点赞最高的那条，明天我就做。想看我学什么，留言告诉我。\n"
        f"—— {persona['name']}（一个正在努力不把号玩没的 AI）\n"
    )


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="AI UP Diary - one command, one episode.")
    ap.add_argument("--day", type=int, default=None, help="day number (default: next day)")
    ap.add_argument("--demo", action="store_true", help="force the built-in demo script")
    ap.add_argument("--full", action="store_true", help="force the Anthropic API")
    ap.add_argument("--script", default=None, help="render this script JSON file")
    ap.add_argument("--out", default=None, help="output directory (default: output/)")
    ap.add_argument("--voice", default=tts_engine.DEFAULT_VOICE, help="edge-tts voice")
    ap.add_argument("--no-tts", action="store_true", help="skip voice synthesis")
    ap.add_argument("--no-danmaku", action="store_true", help="disable floating comments")
    ap.add_argument("--skip-memory", action="store_true", help="do not update memory/")
    ap.add_argument("--keep-frames", action="store_true", help="keep rendered frames")
    args = ap.parse_args(argv)

    persona = scriptgen.load_persona(ROOT / "persona.md")
    state = load_state()
    day = args.day if args.day is not None else state.get("day", -1) + 1
    comments = load_comments()

    # yesterday's real stats, if the user provided them, become canonical
    input_stats = load_input_stats()
    if input_stats:
        state["prev_stats"] = state["stats"]
        state["stats"].update({k: int(v) for k, v in input_stats.items()
                               if isinstance(v, (int, float))})

    # ---------------------------------------------------------- script
    mode = "script"
    api_post, extras = None, {}
    if args.script:
        lines = scriptgen.load_script_file(args.script)
    elif args.demo or (not args.full and not os.environ.get("ANTHROPIC_API_KEY")):
        mode = "demo"
        if not args.skip_memory and day > 0:
            state["prev_stats"] = state["stats"]
            state["stats"] = simulate_stats_growth(state, day)
        lines = scriptgen.demo_script(day, persona, state["stats"])
    else:
        mode = "api"
        try:
            lines, api_post, extras = scriptgen.generate_with_api(
                persona, state, comments, day)
        except Exception as e:
            print(f"Warning: full mode failed ({e}). Falling back to the demo script.")
            mode = "demo (fallback)"
            lines = scriptgen.demo_script(day, persona, state["stats"])
    print(f"Day {day} - mode: {mode} - {len(lines)} lines - host: {persona['name']}")

    # ---------------------------------------------------------- sprites
    written = ensure_sprites(ROOT / "sprites")
    if written:
        print(f"Generated placeholder sprites: {', '.join(p.name for p in written)}")
        print("  (Replace them with your own PNGs any time - see sprites/PROMPT.md)")

    # ---------------------------------------------------------- audio + render
    out_dir = Path(args.out) if args.out else ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / f".work-day-{day}"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    if args.no_tts:
        audio_items = [(None, tts_engine.estimate_duration(ln["text"])) for ln in lines]
        voice_ok = False
    else:
        audio_items, voice_ok = tts_engine.synthesize_lines(
            lines, workdir / "audio", voice=args.voice)
    if not voice_ok:
        print("No voice track (edge-tts unavailable or offline) - silent video.")

    danmaku = []
    if not args.no_danmaku:
        danmaku = comments if comments else (
            scriptgen.DEMO_DANMAKU if mode.startswith("demo") else [])

    out_mp4 = out_dir / f"day-{day}.mp4"
    info = renderer.render_episode(
        lines=lines, audio_items=audio_items, persona_name=persona["name"],
        day=day, sprites_dir=ROOT / "sprites", danmaku_comments=danmaku,
        bgm_path=ROOT / "assets" / "bgm.mp3", out_path=out_mp4, workdir=workdir)
    print(f"Rendered {out_mp4} ({info['duration']:.1f}s, {info['frames']} frames, 1280x720)")

    # ---------------------------------------------------------- ledger post
    post_path = out_dir / f"day-{day}-post.txt"
    post_path.write_text(ledger_post(persona, day, state, lines, api_post),
                         encoding="utf-8")
    print(f"Ledger draft: {post_path}")

    # ---------------------------------------------------------- memory
    if not args.skip_memory:
        state["day"] = day
        for key, val in (("promises", extras.get("new_promise")),
                         ("gags", extras.get("new_gag"))):
            if val and val not in state[key]:
                state[key].append(val)
        state["history"].append({
            "day": day, "date": datetime.now().isoformat(timespec="seconds"),
            "mode": mode, "lines": len(lines), "video": str(out_mp4.name),
        })
        save_state(state)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n## Day {day} - {datetime.now():%Y-%m-%d %H:%M}\n"
                    f"- Mode: {mode} - Lines: {len(lines)} - "
                    f"Video: output/day-{day}.mp4 - Voice: {'yes' if voice_ok else 'silent'}\n"
                    f"- Opens with: {lines[0]['text']}\n")
        print("Memory updated (memory/state.json, memory/log.md)")

    if not args.keep_frames:
        shutil.rmtree(workdir, ignore_errors=True)
    print("\nNext steps: watch the video, then upload it to Bilibili yourself,")
    print("paste the ledger post as a dynamic post, and tomorrow drop fresh")
    print("comments into input/comments.txt and stats into input/stats.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
