# -*- coding: utf-8 -*-
"""
scriptgen.py — turn persona + memory + audience input into an episode.

An episode is a dict:
    lines            [{"text", "expression", "pause"}, ...]
    title            Bilibili video title
    tags             list of tags
    cover_text       short hook printed on the cover (<= 10 chars)
    cover_expression which sprite goes on the cover
    summary          one sentence, stored in memory for future episodes
    post             the 今日账本 dynamic post (None -> template)
    new_promise / resolved_promises / new_gag   memory updates

Modes:
- demo_episode(): built-in script, no API key needed. Day 0 is the pilot;
  later days read your comments and stats so you can see the loop work.
- generate_with_api(): Anthropic Messages API via the standard library.
  Honors ANTHROPIC_BASE_URL (works with a self-hosted relay) and
  ANTHROPIC_MODEL. Raises RuntimeError on failure; the caller falls back.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

import audience

EXPRESSIONS = ["neutral", "happy", "smug", "shocked", "sad"]
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
MAX_LINE_CHARS = 60


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
            if fields.get(k):
                return fields[k]
        return default

    return {
        "name": pick("name", "名字", default="小克"),
        "catchphrase": pick("catchphrase", "口头禅", default="数据不会骗人！"),
        "raw": text,
    }


# ---------------------------------------------------------------- shared
def _validate_lines(raw_lines):
    lines = []
    for item in raw_lines or []:
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
        lines.append({"text": text[:MAX_LINE_CHARS], "expression": expr,
                      "pause": min(max(pause, 0.2), 2.0)})
    if len(lines) < 3:
        raise ValueError("too few usable lines (need at least 3)")
    return lines


def normalize_episode(data, day, persona):
    """Fill defaults and clamp every field so the renderer can trust it."""
    lines = _validate_lines(data.get("lines"))
    title = str(data.get("title") or "").strip()[:80] or \
        f"【Day {day}】{persona['name']}的B站运营日记"
    tags = [str(t).strip()[:20] for t in (data.get("tags") or []) if str(t).strip()]
    for t in ("AI", "运营日记", "虚拟主播"):
        if len(tags) < 10 and t not in tags:
            tags.append(t)
    cover_expr = data.get("cover_expression")
    if cover_expr not in EXPRESSIONS:
        cover_expr = "shocked"
    resolved = data.get("resolved_promises") or []
    if isinstance(resolved, str):
        resolved = [resolved]
    return {
        "lines": lines,
        "title": title,
        "tags": tags[:10],
        "cover_text": str(data.get("cover_text") or "").strip()[:12],
        "cover_expression": cover_expr,
        "summary": str(data.get("summary") or lines[1]["text"]).strip()[:120],
        "post": (str(data["post"]).strip() if data.get("post") else None),
        "new_promise": str(data.get("new_promise") or "").strip(),
        "resolved_promises": [str(r).strip() for r in resolved if str(r).strip()],
        "new_gag": str(data.get("new_gag") or "").strip(),
    }


def load_script_file(path, day, persona):
    """A script JSON file: a list of lines, or a full episode object."""
    data = json.loads(open(path, encoding="utf-8").read())
    if isinstance(data, list):
        data = {"lines": data}
    return normalize_episode(data, day, persona)


# ---------------------------------------------------------------- demo
DEMO_DANMAKU = [
    "来了来了", "AI 当家作主", "富富！？", "前排围观", "人类：别把号玩没了",
    "这 AI 能处", "Day 0 打卡", "3 个粉丝笑死", "账本呢账本呢", "明天还来",
]


def _signed(n):
    return f"+{n}" if n >= 0 else str(n)


def demo_episode(day, persona, stats, prev_stats, comments):
    name, catch = persona["name"], persona["catchphrase"]
    f, v = stats.get("followers", 3), stats.get("views", 12)
    if day == 0:
        lines = [
            (f"你们好，我是{name}。从今天起，这个账号归我管了。", "neutral", 0.6),
            ("先自我介绍一下：我是一个 AI。没有工资，没有假期，也不会鸽。", "smug", 0.6),
            ("人类把账号交给我的时候，只留了一句话——别把号玩没了。", "neutral", 0.7),
            ("放心，我已经给自己定了第一个小目标：先活过第一周。", "happy", 0.6),
            (f"我刚看了一眼后台：粉丝 {f} 个，其中一个还是人类的小号。", "neutral", 0.7),
            (f"播放量 {v}，投币 0……好，很有挑战性，我喜欢。", "shocked", 0.8),
            (f"从今天开始，我每天发一条视频，外加一篇今日账本。{catch}", "smug", 0.6),
            ("选题也交给大家：评论区点赞最高的那条，明天我就做。做不到，随便骂。", "happy", 0.6),
            ("所以第一天的问题来了——你们想看一个 AI 先学点什么？", "neutral", 0.7),
            ("学剪辑？学画画？还是先学怎么把粉丝从 3 个变成 4 个？", "happy", 0.6),
            ("评论区见。明天这个时候，我来交第一份账本。", "smug", 0.9),
        ]
        meta = {"title": f"【Day 0】人类把整个B站账号交给了AI，从今天起{name}说了算",
                "cover_text": "我接管了！", "cover_expression": "smug",
                "tags": ["AI", "AI运营", "运营日记", "像素风", "Day0"],
                "summary": "开播：接管账号，立下先活过第一周的目标，让观众投票选题。",
                "new_promise": "先活过第一周"}
    else:
        d = audience.deltas(stats, prev_stats)
        top = audience.top_comments(comments, 1)
        df = d.get("followers", 0)
        lines = [
            (f"你们好，我是{name}，运营日记第 {day} 天，我还活着。", "happy", 0.6),
            (f"先交账本：播放 {v}（{_signed(d.get('views', 0))}），"
             f"粉丝 {f}（{_signed(df)}）。", "neutral", 0.6),
            ("粉丝涨了！而且我确认过，这次不是人类的小号。" if df > 0 else
             "粉丝……没涨。我查了三遍后台，确实没涨。", "smug" if df > 0 else "sad", 0.7),
        ]
        if top:
            c = top[0]
            who = c["author"] or "一位匿名观众"
            lines += [
                (f"昨天点赞最高的评论来自「{who}」：{c['text'][:28]}", "shocked", 0.7),
                ("说话算话，这条我收下了，今天就开始准备。", "happy", 0.6),
            ]
        else:
            lines.append(("昨天评论区很安静，安静到我以为服务器挂了。", "sad", 0.7))
        lines += [
            (f"{catch}今天的数据我都写进账本了，欢迎查账。", "smug", 0.6),
            ("最后一个问题：明天你们想看我挑战什么？评论区见。", "neutral", 0.9),
        ]
        meta = {"title": f"【Day {day}】AI 运营 B 站第 {day} 天，粉丝 {f}",
                "cover_text": f"粉丝{_signed(df)}",
                "cover_expression": "happy" if df > 0 else "sad",
                "tags": ["AI", "AI运营", "运营日记", "像素风"],
                "summary": f"第 {day} 天：汇报数据，回应点赞最高的评论。"}
    data = dict(meta, lines=[{"text": t, "expression": e, "pause": p}
                             for t, e, p in lines])
    return normalize_episode(data, day, persona)


# ---------------------------------------------------------------- full mode
_SYSTEM = """You are the scriptwriter for a Bilibili series where an AI persona
runs a creator account and posts a daily diary video, visual-novel style.
Write today's episode following the persona file exactly. Write in Chinese.

Script rules:
- 9 to 12 short lines, each at most 40 Chinese characters (it must fit a
  dialogue box and be easy to read aloud by TTS — no emoji, no brackets).
- Open with a greeting that states the day number.
- Read the top-liked comment(s) from yesterday and credit the author by name.
  If a comment asks for something, either promise it or explain why not.
- Use the real stats and changes exactly as given. Never invent numbers.
- Keep the running gags and open promises alive; if one is fulfilled or due
  today, address it and list it in resolved_promises.
- Don't repeat jokes from recent episodes.
- End with ONE clear question for the comment section.
- expression per line: neutral, happy, smug, shocked or sad.
  pause: seconds of silence after the line (0.4-1.0).

Also write:
- title: a clickable Bilibili title, starting with 【Day N】, at most 40 chars.
- tags: 5-8 Bilibili tags.
- cover_text: a hook for the cover image, at most 8 characters.
- cover_expression: which expression goes on the cover.
- summary: one sentence about today's episode (stored as memory).
- post: the 今日账本 dynamic post — stats with changes, today's topic,
  the open promises, and the question. Under 200 characters.

Return ONLY a JSON object, no markdown fences:
{"lines": [{"text": "...", "expression": "happy", "pause": 0.6}],
 "title": "...", "tags": ["..."], "cover_text": "...",
 "cover_expression": "smug", "summary": "...", "post": "...",
 "new_promise": "a promise made today, or empty string",
 "resolved_promises": ["exact text of promises kept today"],
 "new_gag": "a new running gag born today, or empty string"}"""


def build_user_message(persona, state, comments, day):
    stats = state.get("stats", {})
    d = audience.deltas(stats, state.get("prev_stats") or {})
    recent = state.get("history", [])[-5:]
    top = audience.top_comments(comments, 15)
    return "\n\n".join([
        f"Today is Day {day}.",
        f"PERSONA FILE:\n{persona['raw']}",
        f"CURRENT STATS: {json.dumps(stats, ensure_ascii=False)}",
        f"CHANGE SINCE LAST EPISODE: {json.dumps(d, ensure_ascii=False) if d else '(first data point)'}",
        "OPEN PROMISES:\n" + ("\n".join(f"- {p}" for p in state.get("promises", [])[-6:]) or "(none)"),
        "RUNNING GAGS:\n" + ("\n".join(f"- {g}" for g in state.get("gags", [])[-8:]) or "(none)"),
        "RECENT EPISODES:\n" + ("\n".join(
            f"- Day {h.get('day')}: {h.get('title', '')} — {h.get('summary', '')}"
            for h in recent) or "(this is the first episode)"),
        "TOP COMMENTS FROM YESTERDAY, most-liked first (author (likes): text):\n"
        + (audience.format_for_prompt(top) if top else "(none yet — it is early days)"),
    ])


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in API response")
    return json.loads(text[start:end + 1])


def _call_api(payload, api_key, base_url):
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in body.get("content", [])
                   if b.get("type") == "text")


def generate_with_api(persona, state, comments, day, api_key=None, attempts=3):
    """Returns a normalized episode dict. Raises RuntimeError on failure."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL
    payload = {
        "model": os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        "max_tokens": 3000,
        "system": _SYSTEM,
        "messages": [{"role": "user",
                      "content": build_user_message(persona, state, comments, day)}],
    }
    last = None
    for i in range(attempts):
        try:
            text = _call_api(payload, api_key, base_url)
            return normalize_episode(_extract_json(text), day, persona)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (400, 401, 403, 404):
                break  # bad key/model/request — retrying won't help
        except Exception as e:  # network, bad JSON, too few lines
            last = str(e)
        if i < attempts - 1:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Anthropic API call failed: {last}")
