# -*- coding: utf-8 -*-
"""
bili_fetch.py — pull yesterday's numbers and comments from Bilibili's public
web API into input/stats.json and input/comments.txt, so you don't have to
copy them by hand.

    python bili_fetch.py --uid 12345678 --bvid BV1xx411c7XX

--uid   your account's UID (the number in space.bilibili.com/<uid>)
--bvid  yesterday's video (views/likes/coins/favorites + its top comments)

Read-only, no login, no cookies. Bilibili changes these endpoints from time
to time and may rate-limit or require a login for comments; if anything
fails this script says what, and you can still fill the two files by hand.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8"))
    if body.get("code") != 0:
        raise RuntimeError(f"code {body.get('code')}: {body.get('message')}")
    return body["data"]


def fetch_followers(uid):
    return int(get(f"https://api.bilibili.com/x/relation/stat?vmid={uid}")["follower"])


def fetch_video(bvid):
    data = get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    s = data["stat"]
    return data["aid"], {"views": s["view"], "likes": s["like"],
                         "coins": s["coin"], "favorites": s["favorite"]}


def fetch_comments(aid, n=20):
    # sort=1: by like count
    data = get(f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1&ps={n}&pn=1")
    out = []
    for r in (data.get("replies") or [])[:n]:
        text = " ".join(r["content"]["message"].split())
        out.append(f"{r['member']['uname']} ({r.get('like', 0)}赞): {text}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--uid", required=True)
    ap.add_argument("--bvid", help="yesterday's video BV id")
    args = ap.parse_args(argv)

    stats, ok = {}, True
    try:
        stats["followers"] = fetch_followers(args.uid)
    except Exception as e:
        ok = False
        print(f"followers: failed ({e})")
    comments = None
    if args.bvid:
        try:
            aid, vstats = fetch_video(args.bvid)
            stats.update(vstats)
            try:
                comments = fetch_comments(aid)
            except Exception as e:
                ok = False
                print(f"comments: failed ({e}) - fill input/comments.txt by hand")
        except Exception as e:
            ok = False
            print(f"video stats: failed ({e})")

    (ROOT / "input").mkdir(exist_ok=True)
    if stats:
        (ROOT / "input" / "stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"input/stats.json  <- {stats}")
    if comments is not None:
        (ROOT / "input" / "comments.txt").write_text(
            "\n".join(comments) + "\n", encoding="utf-8")
        print(f"input/comments.txt <- {len(comments)} comments")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
