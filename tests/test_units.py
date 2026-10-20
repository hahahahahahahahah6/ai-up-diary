# -*- coding: utf-8 -*-
"""
Fast unit tests (no rendering, no network). Run from the project root:
    python -m unittest discover tests
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import audience  # noqa: E402
import diary  # noqa: E402
import renderer  # noqa: E402
import scriptgen  # noqa: E402

PERSONA = {"name": "小克", "catchphrase": "数据不会骗人！", "raw": "- Name: 小克"}


class TestComments(unittest.TestCase):
    def test_formats(self):
        c = audience.parse_comment("路人甲 (32赞): 想看 AI 学剪辑")
        self.assertEqual((c["author"], c["likes"], c["text"]),
                         ("路人甲", 32, "想看 AI 学剪辑"))
        c = audience.parse_comment("小克本人（人类版）: 别把号玩没了")
        self.assertEqual((c["author"], c["likes"]), ("小克本人（人类版）", 0))
        c = audience.parse_comment("没有作者的一条评论")
        self.assertEqual((c["author"], c["text"]), ("", "没有作者的一条评论"))
        self.assertIsNone(audience.parse_comment("# comment line"))

    def test_ranking_and_danmaku(self):
        cs = [audience.parse_comment(x) for x in
              ["a (1赞): one", "b (9赞): nine", "c: zero", "d (9赞): nine-too"]]
        self.assertEqual([c["author"] for c in audience.top_comments(cs, 3)],
                         ["b", "d", "a"])
        self.assertEqual(audience.danmaku_texts(cs),  # text only, no authors
                         ["one", "nine", "zero", "nine-too"])


class TestStats(unittest.TestCase):
    def test_prev_stats_is_a_copy(self):
        state = json.loads(json.dumps(diary.DEFAULT_STATE))
        self.assertEqual(diary.apply_input_stats(state, {"views": 128, "followers": 4}),
                         "updated")
        self.assertEqual(state["prev_stats"]["views"], 12)  # was aliased before
        self.assertEqual(audience.deltas(state["stats"], state["prev_stats"])["views"], 116)

    def test_stale_input(self):
        state = json.loads(json.dumps(diary.DEFAULT_STATE))
        diary.apply_input_stats(state, {"views": 128})
        self.assertEqual(diary.apply_input_stats(state, {"views": 128}), "stale")
        self.assertEqual(state["prev_stats"]["views"], 12)


class TestEpisode(unittest.TestCase):
    def test_normalize_clamps(self):
        ep = scriptgen.normalize_episode({
            "lines": [{"text": "a" * 200, "expression": "angry", "pause": 9},
                      {"text": "b"}, {"text": "c"}],
            "cover_expression": "nope"}, 3, PERSONA)
        self.assertEqual(len(ep["lines"][0]["text"]), scriptgen.MAX_LINE_CHARS)
        self.assertEqual(ep["lines"][0]["expression"], "neutral")
        self.assertEqual(ep["lines"][0]["pause"], 2.0)
        self.assertIn("Day 3", ep["title"])
        self.assertEqual(ep["cover_expression"], "shocked")

    def test_demo_days(self):
        d0 = scriptgen.demo_episode(0, PERSONA, {"followers": 3}, {}, [])
        cs = [audience.parse_comment("夜猫子 (40赞): 想看你学剪辑")]
        d1 = scriptgen.demo_episode(1, PERSONA, {"followers": 5, "views": 90},
                                    {"followers": 3, "views": 12}, cs)
        self.assertNotEqual(d0["lines"][0]["text"], d1["lines"][0]["text"])
        joined = "".join(l["text"] for l in d1["lines"])
        self.assertIn("夜猫子", joined)
        self.assertIn("+2", joined)

    def test_promise_bookkeeping(self):
        state = json.loads(json.dumps(diary.DEFAULT_STATE))
        state["promises"] = ["先活过第一周", "学会剪辑"]
        ep = scriptgen.demo_episode(0, PERSONA, {}, {}, [])
        ep["resolved_promises"] = ["学会剪辑"]
        ep["new_promise"] = "明天画一张图"
        diary.LOG_PATH = Path(os.devnull)  # don't touch the real log
        diary.update_memory(state, 5, ep, "test", False)
        self.assertEqual(state["promises"], ["先活过第一周", "明天画一张图"])
        self.assertEqual(state["history"][-1]["day"], 5)


class TestTimeline(unittest.TestCase):
    def test_lines_back_to_back(self):
        lines = [{"text": "一二三", "expression": "neutral", "pause": 0.5}] * 3
        items, total = renderer.build_timeline(lines, [(None, 2.0)] * 3)
        self.assertAlmostEqual(items[0]["start"], renderer.TITLE_DUR)
        for a, b in zip(items, items[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        self.assertGreater(total, items[-1]["end"])

    def test_danmaku_lanes_never_overlap(self):
        from PIL import Image, ImageDraw
        d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        f = renderer._load_font(26)
        evs = renderer.schedule_danmaku(["一条比较长的弹幕测试文字", "短"], 0, 60, d, f)
        for lane in range(len(renderer.DANMAKU_LANES)):
            le = [e for e in evs if e["lane"] == lane]
            for a, b in zip(le, le[1:]):
                tail_clear = a["start"] + (a["w"] + renderer.DANMAKU_GAP) / renderer.DANMAKU_SPEED
                self.assertGreaterEqual(b["start"], tail_clear - 1e-9)


class _FakeAPI(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _FakeAPI.seen.append((self.path, self.headers.get("x-api-key"), body))
        episode = {"lines": [{"text": f"第{i}句", "expression": "happy", "pause": 0.5}
                             for i in range(9)],
                   "title": "【Day 2】测试标题", "tags": ["测试"], "cover_text": "封面",
                   "cover_expression": "smug", "summary": "测试", "post": "账本",
                   "new_promise": "", "resolved_promises": [], "new_gag": ""}
        out = json.dumps({"content": [{"type": "text",
                                       "text": "```json\n" + json.dumps(episode) + "\n```"}]})
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


class TestAPI(unittest.TestCase):
    def test_base_url_and_parse(self):
        srv = HTTPServer(("127.0.0.1", 0), _FakeAPI)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
        try:
            state = json.loads(json.dumps(diary.DEFAULT_STATE))
            state["history"] = [{"day": i, "title": f"t{i}", "summary": "s"}
                                for i in range(20)]
            cs = [audience.parse_comment("甲 (5赞): 你好")]
            ep = scriptgen.generate_with_api(PERSONA, state, cs, 2, api_key="k")
        finally:
            del os.environ["ANTHROPIC_BASE_URL"]
            srv.shutdown()
            srv.server_close()
        self.assertEqual(ep["title"], "【Day 2】测试标题")
        path, key, body = _FakeAPI.seen[-1]
        self.assertEqual((path, key), ("/v1/messages", "k"))
        msg = body["messages"][0]["content"]
        self.assertIn("甲 (5赞): 你好", msg)
        self.assertIn("Day 19", msg)
        self.assertNotIn("Day 10:", msg)  # only recent history is sent


if __name__ == "__main__":
    unittest.main()
