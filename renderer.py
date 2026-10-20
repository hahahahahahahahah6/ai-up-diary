# -*- coding: utf-8 -*-
"""
renderer.py — render a script into a 1280x720 visual-novel-style MP4.

Pipeline: build a timeline of segments (typewriter steps + holds), draw one
Pillow frame per segment, encode with ffmpeg's concat demuxer, then mux the
per-line voice clips (delayed to their line's start) and optional BGM.

Scene: dotted cream background, pixel-art host on the right, name tag,
dialogue box at the bottom, optional danmaku floating across the top.
"""
import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 30
CHAR_SEC = 0.055           # typewriter speed, seconds per character
BG = (246, 237, 218)
DOT = (233, 216, 182)
BOX_FILL = (255, 252, 246)
INK = (58, 46, 40)
ORANGE = (232, 134, 46)
BOX = (36, 512, 1244, 696)  # x0, y0, x1, y1
TEXT_X, TEXT_Y, TEXT_W = 64, 542, 1152
FONT_SIZE = 33
LINE_H = 48

_FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
_FONT_BOLD_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
] + _FONT_CANDIDATES


def _load_font(size, bold=False):
    env = os.environ.get("AI_UP_FONT")
    candidates = [(env, 0)] if env else []
    candidates += _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for path, idx in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- helpers
_NO_BREAK_START = set("，。！？、；：）】」』%…,.!?;:)]}")


def wrap_text(draw, text, font, max_width):
    """Greedy character wrap; never starts a line with closing punctuation."""
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        elif ch in _NO_BREAK_START:
            cur = trial  # let it overflow slightly rather than orphan punctuation
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def make_background():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    step, r = 46, 3
    for row, y in enumerate(range(24, H, step)):
        offset = (step // 2) if row % 2 else 0
        for x in range(24 + offset, W, step):
            d.ellipse([x - r, y - r, x + r, y + r], fill=DOT)
    return img


def schedule_danmaku(comments, total_dur, draw, font):
    """Loop comments across 3 lanes, right to left. Returns event dicts."""
    events = []
    if not comments:
        return events
    cycle = len(comments) * 3.4
    base = 0.0
    i = 0
    while base < total_dur:
        for j, text in enumerate(comments):
            start = 1.0 + base + j * 3.4
            if start > total_dur:
                break
            speed = 105 + (i % 4) * 14
            events.append({
                "text": text, "start": start, "lane": (i + j) % 3,
                "speed": speed, "w": draw.textlength(text, font=font),
            })
        base += cycle
        i += 1
    return events


# ---------------------------------------------------------------- timeline
def build_timeline(lines, audio_items):
    """
    Returns (segments, line_starts, total_dur).
    Segment: {"line": idx, "revealed": chars, "dur": s, "indicator": bool, "start": s}
    """
    segments = []
    line_starts = []
    t = 0.0

    def add(line_idx, revealed, dur, indicator, start):
        segments.append({"line": line_idx, "revealed": revealed, "dur": dur,
                         "indicator": indicator, "start": start})

    add(0, 0, 0.5, False, t)  # intro beat
    t += 0.5
    for i, line in enumerate(lines):
        line_starts.append(t)
        text = line["text"]
        typing = len(text) * CHAR_SEC
        speak = audio_items[i][1]
        total = max(typing + 0.45, speak + 0.15) + float(line.get("pause", 0.6))
        # typing steps: one segment per character
        for k in range(1, len(text) + 1):
            add(i, k, CHAR_SEC, False, t + (k - 1) * CHAR_SEC)
        # hold: split into <=0.5s chunks so the "next" indicator can blink
        hold = total - typing
        chunk = 0.5
        n = max(1, math.ceil(hold / chunk))
        for c in range(n):
            add(i, len(text), hold / n, c % 2 == 0, t + typing + c * (hold / n))
        t += total
    add(len(lines) - 1, len(lines[-1]["text"]), 0.8, True, t)  # outro beat
    t += 0.8
    return segments, line_starts, t


# ---------------------------------------------------------------- drawing
class Scene:
    def __init__(self, persona_name, day, sprites_dir):
        self.bg = make_background()
        self.font = _load_font(FONT_SIZE)
        self.font_tag = _load_font(25, bold=True)
        self.font_chip = _load_font(22, bold=True)
        self.font_danmaku = _load_font(26, bold=True)
        self.name = persona_name
        self.day = day
        self.sprites = {}
        for p in Path(sprites_dir).glob("*.png"):
            self.sprites[p.stem] = Image.open(p).convert("RGBA")
        self._static_cache = {}
        self._wrap_cache = {}
        scratch = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        self._scratch = scratch

    def sprite(self, expr):
        return self.sprites.get(expr) or self.sprites.get("neutral")

    def static_layer(self, expr):
        """Background + sprite + box + tags (everything except dialogue text)."""
        if expr in self._static_cache:
            return self._static_cache[expr]
        img = self.bg.copy()
        spr = self.sprite(expr)
        if spr is not None:
            img.paste(spr, (W - spr.width - 24, BOX[3] - spr.height), spr)
        d = ImageDraw.Draw(img)
        # dialogue box
        d.rounded_rectangle(BOX, radius=18, fill=BOX_FILL, outline=INK, width=4)
        # title chip, top-left
        chip = f"{self.name}的运营日记 · Day {self.day}"
        cw = d.textlength(chip, font=self.font_chip)
        d.rounded_rectangle([28, 26, 28 + cw + 32, 70], radius=12,
                            fill=BOX_FILL, outline=INK, width=3)
        d.text((44, 36), chip, font=self.font_chip, fill=INK)
        # name tag overlapping the box's top edge
        tw = d.textlength(self.name, font=self.font_tag)
        d.rounded_rectangle([56, BOX[1] - 24, 56 + tw + 36, BOX[1] + 22],
                            radius=10, fill=ORANGE, outline=INK, width=3)
        d.text((74, BOX[1] - 15), self.name, font=self.font_tag, fill=(255, 255, 255))
        self._static_cache[expr] = img
        return img

    def wrapped(self, text):
        if text not in self._wrap_cache:
            self._wrap_cache[text] = wrap_text(self._scratch, text, self.font, TEXT_W)
        return self._wrap_cache[text]

    def frame(self, seg, lines, danmaku_events, t):
        line = lines[seg["line"]]
        img = self.static_layer(line["expression"]).copy()
        d = ImageDraw.Draw(img)
        # danmaku
        for ev in danmaku_events:
            age = t - ev["start"]
            if age < 0:
                continue
            x = W - age * ev["speed"]
            if x < -ev["w"]:
                continue
            y = 92 + ev["lane"] * 44
            d.text((x, y), ev["text"], font=self.font_danmaku,
                   fill=(255, 255, 255), stroke_width=3, stroke_fill=INK)
        # dialogue text, revealed character by character
        wrapped = self.wrapped(line["text"])
        remaining = seg["revealed"]
        for li, wline in enumerate(wrapped[:3]):
            if remaining <= 0:
                break
            show = wline[:remaining]
            remaining -= len(wline)
            d.text((TEXT_X, TEXT_Y + li * LINE_H), show, font=self.font, fill=INK)
        # blinking "next" indicator
        if seg["indicator"]:
            cx, cy = BOX[2] - 44, BOX[3] - 30
            d.polygon([(cx, cy), (cx + 18, cy), (cx + 9, cy + 12)], fill=ORANGE)
        return img


# ---------------------------------------------------------------- ffmpeg
def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def encode(frames_dir, segments, audio_items, line_starts, total_dur,
           bgm_path, out_path):
    frames_dir = Path(frames_dir)
    list_file = frames_dir / "frames.txt"
    with open(list_file, "w") as f:
        f.write("ffconcat version 1.0\n")
        for i, seg in enumerate(segments):
            f.write(f"file 'frame_{i:04d}.png'\nduration {seg['dur']:.3f}\n")
        f.write(f"file 'frame_{len(segments) - 1:04d}.png'\n")  # repeat last
    video_only = frames_dir / "video_only.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-pix_fmt", "yuv420p", "-r", str(FPS), str(video_only)])

    voiced = [(p, d, line_starts[i]) for i, (p, d) in enumerate(audio_items) if p]
    has_bgm = bgm_path and Path(bgm_path).exists()
    if not voiced and not has_bgm:
        os.replace(video_only, out_path)
        return

    cmd = ["ffmpeg", "-y", "-i", str(video_only)]
    filters = []
    labels = []
    for j, (path, _dur, start) in enumerate(voiced):
        cmd += ["-i", str(path)]
        idx = j + 1
        ms = int((start + 0.05) * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms}[v{j}]")
        labels.append(f"[v{j}]")
    if voiced:
        if len(labels) == 1:
            filters.append(f"{labels[0]}apad,atrim=0:{total_dur:.3f}[voice]")
        else:
            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
                f"normalize=0,apad,atrim=0:{total_dur:.3f}[voice]")
    if has_bgm:
        bidx = 1 + len(voiced)
        cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
        filters.append(f"[{bidx}:a]volume=0.10,atrim=0:{total_dur:.3f}[bg]")
        if voiced:
            filters.append("[voice][bg]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            filters.append("[bg]volume=1.4[aout]")
    else:
        filters.append("[voice]anull[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", str(out_path)]
    _run(cmd)


# ---------------------------------------------------------------- top level
def render_episode(*, lines, audio_items, persona_name, day, sprites_dir,
                   danmaku_comments, bgm_path, out_path, workdir):
    workdir = Path(workdir)
    frames_dir = workdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    scene = Scene(persona_name, day, sprites_dir)
    segments, line_starts, total_dur = build_timeline(lines, audio_items)
    events = schedule_danmaku(danmaku_comments or [], total_dur,
                              scene._scratch, scene.font_danmaku)
    for i, seg in enumerate(segments):
        img = scene.frame(seg, lines, events, seg["start"])
        img.save(frames_dir / f"frame_{i:04d}.png")
    encode(frames_dir, segments, audio_items, line_starts, total_dur,
           bgm_path, Path(out_path))
    return {"duration": total_dur, "frames": len(segments),
            "line_starts": line_starts}
