# -*- coding: utf-8 -*-
"""
diary.py — AI 运营日记生成器 (AI UP Diary): one command, one episode.

    python diary.py                  # next day; demo mode if no API key
    python diary.py --day 3          # a specific day
    python diary.py --demo           # force the built-in demo script
    python diary.py --full           # force the Anthropic API
    python diary.py --script s.json  # render your own script / re-render one

Everything for one episode lands in output/day-<N>/:
    video.mp4    the episode
    cover.png    1280x720 cover
    upload.txt   title, tags, description and a pre-upload checklist
    post.txt     the 今日账本 dynamic post
    script.json  the script — edit it and re-render with --script

Publishing is manual by design: the AI writes and renders, a human reviews
and uploads.
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

import audience  # noqa: E402
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
    "last_input_stats": None,
    "promises": [],
    "gags": ["3 个粉丝里有一个是人类的小号"],
    "history": [],
}


# ---------------------------------------------------------------- state
def load_state(path=STATE_PATH):
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            for k, v in DEFAULT_STATE.items():
                state.setdefault(k, json.loads(json.dumps(v)))
            return state
        except Exception:
            print("Warning: memory/state.json is unreadable - starting from defaults.")
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state, path=STATE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_input_stats(state, input_stats):
    """Real numbers from input/stats.json become canonical. Returns a status
    string. Copies before updating so prev_stats keeps yesterday's values."""
    if not input_stats:
        return "none"
    if input_stats == state.get("last_input_stats"):
        return "stale"
    state["prev_stats"] = dict(state["stats"])
    state["stats"] = dict(state["stats"], **input_stats)
    state["last_input_stats"] = dict(input_stats)
    return "updated"


def simulate_stats_growth(stats, day):
    """Demo mode: pretend the account grew a little overnight (deterministic)."""
    rng = random.Random(1000 + day)
    s = dict(stats)
    g = max(1, day + 1)
    s["views"] = s.get("views", 0) + rng.randint(8, 30) * g
    s["likes"] = s.get("likes", 0) + rng.randint(1, 9) * g
    s["coins"] = s.get("coins", 0) + rng.randint(0, 3)
    s["favorites"] = s.get("favorites", 0) + rng.randint(0, 4)
    s["followers"] = s.get("followers", 0) + rng.randint(0, 2 + day // 2)
    return s


def update_memory(state, day, episode, mode, voice_ok):
    for done in episode["resolved_promises"]:
        state["promises"] = [p for p in state["promises"]
                             if p != done and p not in done and done not in p]
    if episode["new_promise"] and episode["new_promise"] not in state["promises"]:
        state["promises"].append(episode["new_promise"])
    if episode["new_gag"] and episode["new_gag"] not in state["gags"]:
        state["gags"].append(episode["new_gag"])
    state["promises"] = state["promises"][-10:]
    state["gags"] = state["gags"][-15:]
    entry = {"day": day, "date": datetime.now().isoformat(timespec="seconds"),
             "mode": mode, "title": episode["title"], "summary": episode["summary"]}
    state["history"] = [h for h in state["history"] if h.get("day") != day] + [entry]
    state["history"].sort(key=lambda h: h.get("day", 0))
    state["day"] = max(state.get("day", -1), day)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n## Day {day} - {datetime.now():%Y-%m-%d %H:%M}\n"
                f"- {episode['title']}\n- {episode['summary']}\n"
                f"- Mode: {mode} - Lines: {len(episode['lines'])} - "
                f"Voice: {'yes' if voice_ok else 'silent'}\n")


# ---------------------------------------------------------------- texts
def ledger_post(persona, day, state, episode):
    if episode["post"]:
        return episode["post"].rstrip() + "\n"
    s, prev = state["stats"], state.get("prev_stats") or {}
    d = audience.deltas(s, prev)

    def fmt(key, label):
        extra = f"（{'+' if d[key] >= 0 else ''}{d[key]}）" if key in d else ""
        return f"{label} {s.get(key, 0)}{extra}"

    promises = state.get("promises") or ["先活过第一周"]
    return (
        f"【今日账本 · Day {day}】\n"
        f"我是{persona['name']}，今天的账本来了，数据全部公开：\n"
        + " · ".join([fmt("views", "播放"), fmt("likes", "点赞"), fmt("coins", "投币"),
                      fmt("favorites", "收藏"), fmt("followers", "粉丝")]) + "\n"
        f"今天的视频：{episode['title']}\n"
        f"还立着的 flag：{promises[-1]}\n"
        f"老规矩，评论区点赞最高的那条，明天我就做。\n"
        f"—— {persona['name']}（一个努力不把号玩没的 AI）\n"
    )


def upload_sheet(persona, day, episode):
    return (
        f"标题：\n{episode['title']}\n\n"
        f"标签：\n{', '.join(episode['tags'])}\n\n"
        f"简介：\n"
        f"运营日记 Day {day}。这个账号的选题、脚本、视频由 AI（{persona['name']}）"
        f"负责，人类只负责审核和发布。\n"
        f"想看我做什么，写在评论区，点赞最高的那条明天就做。\n"
        f"本视频由 AI 生成。\n\n"
        f"发布前检查：\n"
        f"[ ] 从头到尾看一遍 video.mp4，台词和数字没问题\n"
        f"[ ] 封面用 cover.png\n"
        f"[ ] 投稿时勾选「含 AI 生成内容」声明\n"
        f"[ ] BGM 和立绘你有使用权\n"
        f"[ ] 发布后把 post.txt 发成动态\n"
    )


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="AI UP Diary - one command, one episode.")
    ap.add_argument("--day", type=int, default=None, help="day number (default: next day)")
    ap.add_argument("--demo", action="store_true", help="force the built-in demo script")
    ap.add_argument("--full", action="store_true", help="force the Anthropic API")
    ap.add_argument("--script", default=None, help="render this script/episode JSON")
    ap.add_argument("--out", default=None, help="output root (default: output/)")
    ap.add_argument("--voice", default=tts_engine.DEFAULT_VOICE, help="edge-tts voice")
    ap.add_argument("--rate", default=tts_engine.DEFAULT_RATE, help="speech rate, e.g. +10%%")
    ap.add_argument("--pitch", default=tts_engine.DEFAULT_PITCH, help="speech pitch, e.g. +5Hz")
    ap.add_argument("--no-tts", action="store_true", help="skip voice synthesis")
    ap.add_argument("--no-danmaku", action="store_true", help="disable floating comments")
    ap.add_argument("--skip-memory", action="store_true", help="do not read/update memory/")
    ap.add_argument("--keep-work", action="store_true", help="keep temp audio/logs")
    args = ap.parse_args(argv)

    renderer.check_ffmpeg()
    persona = scriptgen.load_persona(ROOT / "persona.md")
    state = load_state() if not args.skip_memory else json.loads(json.dumps(DEFAULT_STATE))
    day = args.day if args.day is not None else state.get("day", -1) + 1
    rerun = any(h.get("day") == day for h in state["history"])

    use_api = not args.script and not args.demo and (
        args.full or bool(os.environ.get("ANTHROPIC_API_KEY")))
    comments = audience.load_comments(ROOT / "input" / "comments.txt")
    if not comments and not use_api and day > 0:
        comments = audience.load_comments(ROOT / "input" / "comments.example.txt")

    # ---------------------------------------------------------- stats
    if not rerun:
        status = apply_input_stats(state, audience.load_stats(ROOT / "input" / "stats.json"))
        if status == "stale":
            print("Warning: input/stats.json is identical to last time - did you "
                  "forget to update it? Using it without counting any change.")
        elif status == "none" and not use_api and day > 0:
            state["prev_stats"] = dict(state["stats"])
            state["stats"] = simulate_stats_growth(state["stats"], day)

    # ---------------------------------------------------------- script
    mode = "demo"
    if args.script:
        mode = "script"
        episode = scriptgen.load_script_file(args.script, day, persona)
    elif use_api:
        mode = "api"
        try:
            episode = scriptgen.generate_with_api(persona, state, comments, day)
        except Exception as e:
            print(f"Warning: full mode failed ({e}).\n  Falling back to the demo script.")
            mode = "demo (fallback)"
    if mode.startswith("demo"):
        episode = scriptgen.demo_episode(day, persona, state["stats"],
                                         state.get("prev_stats") or {}, comments)
    lines = episode["lines"]
    print(f"Day {day} - mode: {mode} - {len(lines)} lines - host: {persona['name']}")
    print(f"  {episode['title']}")

    # ---------------------------------------------------------- sprites
    written = ensure_sprites(ROOT / "sprites")
    if written:
        print(f"Generated placeholder sprites: {', '.join(p.name for p in written)}")

    # ---------------------------------------------------------- output dir
    out_dir = (Path(args.out) if args.out else ROOT / "output") / f"day-{day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / ".work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    (out_dir / "script.json").write_text(
        json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------- voice
    if args.no_tts:
        audio_items = [(None, tts_engine.estimate_duration(l["text"])) for l in lines]
        voice_ok = False
    else:
        print("Synthesizing voice...")
        audio_items, voice_ok = tts_engine.synthesize_lines(
            lines, work / "audio", voice=args.voice, rate=args.rate, pitch=args.pitch)
        if not voice_ok:
            print("  No voice (edge-tts not installed or offline) - silent video.")

    # ---------------------------------------------------------- render
    danmaku = []
    if not args.no_danmaku:
        danmaku = audience.danmaku_texts(comments) or (
            scriptgen.DEMO_DANMAKU if mode.startswith("demo") else [])
    print("Rendering video...")
    info = renderer.render_episode(
        lines=lines, audio_items=audio_items, persona_name=persona["name"],
        day=day, sprites_dir=ROOT / "sprites", danmaku_texts=danmaku,
        bgm_path=ROOT / "assets" / "bgm.mp3", out_path=out_dir / "video.mp4",
        workdir=work)
    renderer.render_cover(persona_name=persona["name"], day=day,
                          cover_text=episode["cover_text"],
                          expression=episode["cover_expression"],
                          sprites_dir=ROOT / "sprites", out_path=out_dir / "cover.png")

    (out_dir / "post.txt").write_text(ledger_post(persona, day, state, episode),
                                      encoding="utf-8")
    (out_dir / "upload.txt").write_text(upload_sheet(persona, day, episode),
                                        encoding="utf-8")

    if not args.skip_memory and mode != "script":
        update_memory(state, day, episode, mode, voice_ok)
        save_state(state)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\nDone: {out_dir}  ({info['duration']:.1f}s, {info['frames']} frames"
          f"{', lip-sync on' if info['lip_sync'] else ''})")
    print("  video.mp4 / cover.png / upload.txt / post.txt / script.json")
    print("Next: watch it, then upload with the title/tags in upload.txt.")
    print("Remember to tick 「含 AI 生成内容」 when you upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
