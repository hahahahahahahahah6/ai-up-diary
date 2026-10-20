# -*- coding: utf-8 -*-
"""
audience.py — read what the audience left behind: comments and stats.

Comment file format (input/comments.txt), one per line, any of:
    路人甲 (32赞): 想看 AI 学剪辑
    路人甲: 想看 AI 学剪辑
    想看 AI 学剪辑
Lines starting with # are ignored. The like count is optional; when present,
comments are ranked by it, so "do the top-liked request tomorrow" is real.
"""
import json
import re
from pathlib import Path

_COMMENT_RE = re.compile(
    r"^(?P<author>[^:：]{1,32}?)\s*"
    r"(?:[（(]\s*(?P<likes>\d+)\s*(?:赞|likes?)?\s*[)）])?\s*"
    r"[:：]\s*(?P<text>.+)$"
)

STAT_KEYS = ("views", "likes", "coins", "favorites", "followers")


def parse_comment(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = _COMMENT_RE.match(line)
    if m:
        return {"author": m.group("author").strip(),
                "likes": int(m.group("likes") or 0),
                "text": m.group("text").strip()}
    return {"author": "", "likes": 0, "text": line}


def load_comments(path):
    """Return comments in file order (list of dicts)."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        c = parse_comment(ln)
        if c:
            out.append(c)
    return out


def top_comments(comments, n=15):
    """Highest-liked first; ties keep file order."""
    ranked = sorted(enumerate(comments), key=lambda ic: (-ic[1]["likes"], ic[0]))
    return [c for _, c in ranked[:n]]


def format_for_prompt(comments):
    lines = []
    for c in comments:
        who = c["author"] or "匿名"
        likes = f" ({c['likes']}赞)" if c["likes"] else ""
        lines.append(f"{who}{likes}: {c['text']}")
    return "\n".join(lines)


def danmaku_texts(comments, max_len=22):
    """Floating comments show the text only — never the author's name."""
    return [c["text"] for c in comments if 0 < len(c["text"]) <= max_len]


def load_stats(path):
    """Read input/stats.json -> dict of ints, or None if missing/invalid."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        print("Warning: input/stats.json is not valid JSON - ignoring it.")
        return None
    stats = {k: int(raw[k]) for k in STAT_KEYS
             if isinstance(raw.get(k), (int, float))}
    return stats or None


def deltas(stats, prev):
    """{key: change since prev} for keys present in both."""
    return {k: stats.get(k, 0) - prev[k] for k in STAT_KEYS
            if prev and k in prev}
