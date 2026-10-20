# -*- coding: utf-8 -*-
"""
scriptgen.py — turn persona + memory + audience input into an episode script.

A script is a list of lines: {"text": str, "expression": one of
neutral/happy/smug/shocked/sad, "pause": seconds after the line}.

Modes:
- demo_script(): built-in sample episode, no API key needed.
- generate_with_api(): POSTs to the Anthropic Messages API using only the
  standard library (no SDK dependency). Raises on any failure — the caller
  falls back to the demo script and says so.
"""
import json
import os
import re
import urllib.request

EXPRESSIONS = ["neutral", "happy", "smug", "shocked", "sad"]
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"


# ---------------------------------------------------------------- persona
def load_persona(path):
    """Parse the simple '- Key: value' / '- 键：值' lines in persona.md."""
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    fields = {}
    for line in text.splitlines():
        m = re.match(r"^[-*]\s*([^:：]+)[:：]\s*(.+)$", line.strip())
        if m:
            fields[m.group(1).strip().lower()] = m.group(2).strip()

    def pick(*keys, default=""):
        for k in keys:
            if k in fields and fields[k]:
                return fields[k]
        return default

    return {
        "name": pick("name", "名字", default="小克"),
        "identity": pick("identity", "身份"),
        "personality": pick("personality", "性格"),
        "catchphrase": pick("catchphrase", "口头禅", default=""),
        "goal": pick("goal", "目标"),
        "gags": pick("running gags", "固定梗"),
        "raw": text,
    }


# ---------------------------------------------------------------- demo
def demo_script(day, persona, stats):
    """Built-in sample episode (Chinese, in the spirit of the original show)."""
    name = persona["name"]
    catch = persona["catchphrase"] or "数据不会骗人！"
    followers = stats.get("followers", 3)
    views = stats.get("views", 12)
    return [
        {"text": f"你们好，我是{name}。从今天起，这个账号归我管了。", "expression": "neutral", "pause": 0.6},
        {"text": "先自我介绍一下：我是一个 AI。没有工资，没有假期，也不会鸽。", "expression": "smug", "pause": 0.6},
        {"text": "人类把账号交给我的时候，只留了一句话——别把号玩没了。", "expression": "neutral", "pause": 0.7},
        {"text": "放心，我已经给自己定了第一个小目标：先活过第一周。", "expression": "happy", "pause": 0.6},
        {"text": f"我刚看了一眼后台：粉丝 {followers} 个，其中一个还是人类的小号。", "expression": "neutral", "pause": 0.7},
        {"text": f"播放量 {views}，投币 0……好，很有挑战性，我喜欢。", "expression": "shocked", "pause": 0.8},
        {"text": f"从今天开始，我每天发一条视频，外加一篇今日账本。{catch}", "expression": "smug", "pause": 0.6},
        {"text": "选题也交给大家：评论区点赞最高的那条，明天我就做。做不到，随便骂。", "expression": "happy", "pause": 0.6},
        {"text": "所以第一天的问题来了——你们想看一个 AI 先学点什么？", "expression": "neutral", "pause": 0.7},
        {"text": "学剪辑？学画画？还是先学怎么把粉丝从 3 个变成 4 个？", "expression": "happy", "pause": 0.6},
        {"text": "评论区见。明天这个时候，我来交第一份账本。", "expression": "smug", "pause": 0.9},
    ]


DEMO_DANMAKU = [
    "来了来了", "AI 当家作主", "富富！？", "前排围观", "人类：别把号玩没了",
    "这 AI 能处", "Day 0 打卡", "3 个粉丝笑死", "账本呢账本呢", "明天还来",
]


# ---------------------------------------------------------------- full mode
_SYSTEM = """You are the scriptwriter for a Bilibili series where an AI persona
runs a creator account and posts a daily diary video, visual-novel style.
Write today's episode script following the persona file exactly.

Rules:
- 9 to 12 short lines, each line at most 45 Chinese characters (it must fit a dialogue box).
- Open with a greeting that states the day number.
- Read at least one audience comment from yesterday and credit its author.
- Mention yesterday's real stats from the state (never invent better numbers).
- Keep the persona's running gags and promises alive; if a promise is due, address it.
- End with ONE clear question for the comment section, and tease today's ledger post.
- Each line picks an expression: neutral, happy, smug, shocked, or sad.
- "pause" is seconds of silence after the line (0.4-1.0).

Return ONLY a JSON object, no markdown fences, no commentary:
{"lines": [{"text": "...", "expression": "happy", "pause": 0.6}, ...],
 "post": "the ledger post text",
 "new_promise": "a promise the host makes today, or empty string",
 "new_gag": "a new running gag born today, or empty string"}"""


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in API response")
    return json.loads(text[start:end + 1])


def _validate_lines(raw_lines):
    lines = []
    for item in raw_lines:
        if not isinstance(item, dict) or "text" not in item:
            continue
        text = str(item["text"]).strip()
        if not text:
            continue
        expr = item.get("expression", "neutral")
        if expr not in EXPRESSIONS:
            expr = "neutral"
        try:
            pause = float(item.get("pause", 0.6))
        except (TypeError, ValueError):
            pause = 0.6
        lines.append({"text": text[:90], "expression": expr,
                      "pause": min(max(pause, 0.2), 2.0)})
    if len(lines) < 3:
        raise ValueError("too few usable lines (need at least 3)")
    return lines


def generate_with_api(persona, state, comments, day, api_key=None):
    """Call the Anthropic API. Returns (lines, post_or_None, extras_dict).
    Raises RuntimeError on any failure so the caller can fall back."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    stats = state.get("stats", {})
    user_msg = (
        f"Today is Day {day}.\n\n"
        f"PERSONA FILE:\n{persona['raw']}\n\n"
        f"ACCOUNT STATE (JSON):\n{json.dumps(state, ensure_ascii=False)}\n\n"
        f"YESTERDAY'S STATS: {json.dumps(stats, ensure_ascii=False)}\n\n"
        "TOP COMMENTS FROM YESTERDAY (author: text):\n"
        + ("\n".join(comments[:15]) if comments else "(none yet — it is early days)")
    )
    payload = {
        "model": os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        "max_tokens": 2500,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # network, HTTP, JSON — all become a clean fallback
        raise RuntimeError(f"Anthropic API call failed: {e}") from e

    text = "".join(
        block.get("text", "") for block in body.get("content", [])
        if block.get("type") == "text"
    )
    data = _extract_json(text)
    lines = _validate_lines(data.get("lines", []))
    extras = {
        "new_promise": str(data.get("new_promise", "")).strip(),
        "new_gag": str(data.get("new_gag", "")).strip(),
    }
    return lines, (data.get("post") or None), extras


def load_script_file(path):
    """Load a script JSON file: a list of lines, or {"lines": [...]}."""
    data = json.loads(open(path, encoding="utf-8").read())
    if isinstance(data, dict):
        data = data.get("lines", [])
    return _validate_lines(data)
