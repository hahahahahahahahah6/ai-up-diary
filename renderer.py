# -*- coding: utf-8 -*-
"""
renderer.py — render a script into a 1280x720, 30fps visual-novel-style MP4,
plus a matching cover image.

Every frame is drawn with Pillow and piped straight into ffmpeg (no PNG
files on disk). Per-line voice clips are delayed to their line's start and
mixed with optional BGM.

What moves:
- typewriter dialogue text, blinking "next" arrow
- the host: lip-flap driven by the voice's loudness, blinks, idle bob,
  a small hop whenever the expression changes
- danmaku (floating comments) in two lanes that never overlap
- a title card ("<name>的B站运营日记 / DAY N") before the first line
"""
import array
import bisect
import math
import os
import random
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 30
CHAR_SEC = 0.055            # typewriter speed, seconds per character
TITLE_DUR = 2.2             # title card before the first line
OUTRO_DUR = 1.0
BG = (246, 237, 218)
DOT = (233, 216, 182)
BOX_FILL = (255, 252, 246)
INK = (58, 46, 40)
ORANGE = (232, 134, 46)
WHITE = (255, 255, 255)
BOX = (36, 512, 1244, 696)  # x0, y0, x1, y1
TEXT_X, TEXT_Y, TEXT_W = 64, 542, 1152
FONT_SIZES = (33, 29, 26)   # shrink to fit 3 lines if needed
DANMAKU_LANES = (78, 116)   # y of each lane; kept above the host's head
DANMAKU_SPEED = 125         # px/s, same for all so nothing overtakes
DANMAKU_GAP = 70            # px between comments in the same lane
SPRITE_H = 560              # host sprites are scaled to this height
SPRITE_SINK = 44            # feet hide behind the dialogue box

# ---------------------------------------------------------------- fonts
# (path, ttc index). For Noto CJK .ttc files index 2 is Simplified Chinese.
_REGULAR = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
]
_BOLD = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 2),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
] + _REGULAR
_BLACK = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Black.ttc", 2),
] + _BOLD
_warned_font = False


def _load_font(size, weight="regular"):
    global _warned_font
    env = os.environ.get("AI_UP_FONT")
    cands = [(env, 0)] if env else []
    cands += {"regular": _REGULAR, "bold": _BOLD, "black": _BLACK}[weight]
    for path, idx in cands:
        if path and os.path.exists(path):
            for i in (idx, 0):
                try:
                    return ImageFont.truetype(path, size, index=i)
                except Exception:
                    continue
    if not _warned_font:
        print("WARNING: no Chinese font found - text will render as boxes.\n"
              "  Set AI_UP_FONT=/path/to/a/CJK/font.ttf (e.g. NotoSansSC).")
        _warned_font = True
    try:
        return ImageFont.load_default(size)
    except TypeError:
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
            cur = trial  # overflow slightly rather than orphan punctuation
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def make_background(w=W, h=H):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    step, r = 46, 3
    for row, y in enumerate(range(24, h, step)):
        offset = (step // 2) if row % 2 else 0
        for x in range(24 + offset, w, step):
            d.ellipse([x - r, y - r, x + r, y + r], fill=DOT)
    return img


def shadow_text(d, xy, text, font, fill, shadow=INK, offset=6):
    """Chunky drop-shadow text, retro-game style."""
    x, y = xy
    d.text((x + offset, y + offset), text, font=font, fill=shadow)
    d.text((x, y), text, font=font, fill=fill)


def load_sprites(sprites_dir, height=SPRITE_H):
    """All PNGs in sprites/, scaled to a common height. Small pixel art is
    scaled with NEAREST so it stays crisp; big painted art with LANCZOS."""
    out = {}
    for p in Path(sprites_dir).glob("*.png"):
        img = Image.open(p).convert("RGBA")
        if img.height != height:
            resample = Image.NEAREST if img.height <= 200 else Image.LANCZOS
            img = img.resize((max(1, round(img.width * height / img.height)),
                              height), resample)
        out[p.stem] = img
    return out


# ---------------------------------------------------------------- audio
def loudness_envelope(path, fps=FPS):
    """Per-video-frame RMS (0..1) of an audio file, via ffmpeg. [] on failure."""
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
             "-ac", "1", "-ar", "8000", "-"],
            capture_output=True, timeout=60, check=True).stdout
    except Exception:
        return []
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    win = 8000 // fps
    env = []
    for i in range(0, len(samples), win):
        chunk = samples[i:i + win]
        if not chunk:
            break
        env.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768)
    peak = max(env) if env else 0
    return [v / peak for v in env] if peak > 0 else env


# ---------------------------------------------------------------- timeline
def build_timeline(lines, audio_items):
    """
    Returns (items, total_dur). One item per line:
    {start, type_end, speak_start, speak_end, end, chars}
    """
    items = []
    t = TITLE_DUR
    for i, line in enumerate(lines):
        n = len(line["text"])
        typing = n * CHAR_SEC
        speak = audio_items[i][1]
        total = max(typing + 0.45, speak + 0.15) + float(line.get("pause", 0.6))
        items.append({"start": t, "type_end": t + typing,
                      "speak_start": t + 0.05, "speak_end": t + 0.05 + speak,
                      "end": t + total, "chars": n})
        t += total
    return items, t + OUTRO_DUR


def schedule_danmaku(texts, start_at, total_dur, draw, font):
    """Fill lanes right-to-left; each lane waits until the previous comment
    has cleared enough room. Loops the list until the video ends."""
    events = []
    if not texts:
        return events
    lane_free = [start_at + 0.0, start_at + 1.3]
    i = 0
    rng = random.Random(len(texts))
    while True:
        lane = min(range(len(DANMAKU_LANES)), key=lambda k: lane_free[k])
        start = lane_free[lane] + rng.uniform(0.2, 1.4)
        if start > total_dur - 2:
            break
        text = texts[i % len(texts)]
        w = draw.textlength(text, font=font)
        events.append({"text": text, "start": start, "lane": lane, "w": w})
        lane_free[lane] = start + (w + DANMAKU_GAP) / DANMAKU_SPEED
        i += 1
    return events


# ---------------------------------------------------------------- scene
class Scene:
    def __init__(self, persona_name, day, sprites_dir, seed=0):
        self.name, self.day = persona_name, day
        self.font_tag = _load_font(25, "bold")
        self.font_chip = _load_font(22, "bold")
        self.font_danmaku = _load_font(26, "bold")
        self.font_title = _load_font(64, "black")
        self.font_day = _load_font(150, "black")
        self.fonts = [_load_font(s) for s in FONT_SIZES]
        self.sprites = load_sprites(sprites_dir)
        self._scratch = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        self._base = self._make_base()
        self._box = self._make_box_layer()
        self._composites = {}
        self._wrap_cache = {}
        rng = random.Random(seed * 7919 + day)
        self.blinks, t = [], rng.uniform(1.5, 3.0)
        while t < 3600:
            self.blinks.append(t)
            t += rng.uniform(2.4, 4.8)

    # -- static layers
    def _make_base(self):
        img = make_background()
        d = ImageDraw.Draw(img)
        chip = f"{self.name}的运营日记 · Day {self.day}"
        cw = d.textlength(chip, font=self.font_chip)
        d.rounded_rectangle([28, 26, 28 + cw + 32, 70], radius=12,
                            fill=BOX_FILL, outline=INK, width=3)
        d.text((44, 36), chip, font=self.font_chip, fill=INK)
        return img

    def _make_box_layer(self):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(BOX, radius=18, fill=BOX_FILL + (255,),
                            outline=INK, width=4)
        tw = d.textlength(self.name, font=self.font_tag)
        d.rounded_rectangle([56, BOX[1] - 24, 56 + tw + 36, BOX[1] + 22],
                            radius=10, fill=ORANGE, outline=INK, width=3)
        d.text((74, BOX[1] - 15), self.name, font=self.font_tag, fill=WHITE)
        return layer

    def sprite(self, key, expr):
        return (self.sprites.get(key) or self.sprites.get(expr)
                or self.sprites.get("neutral"))

    def composite(self, sprite_key, expr, dy):
        """Background + host + dialogue box. Cached per pose."""
        ck = (sprite_key, expr, dy)
        if ck not in self._composites:
            img = self._base.copy()
            spr = self.sprite(sprite_key, expr)
            if spr is not None:
                img.paste(spr, (W - spr.width - 24,
                                BOX[3] - spr.height + SPRITE_SINK + dy), spr)
            img.paste(self._box, (0, 0), self._box)
            self._composites[ck] = img
        return self._composites[ck]

    def wrapped(self, text):
        """(font, lines) — the largest font size that fits in 3 lines."""
        if text not in self._wrap_cache:
            for font in self.fonts:
                lines = wrap_text(self._scratch, text, font, TEXT_W)
                if len(lines) <= 3:
                    break
            self._wrap_cache[text] = (font, lines[:3])
        return self._wrap_cache[text]

    def is_blinking(self, t):
        i = bisect.bisect_right(self.blinks, t) - 1
        return i >= 0 and t - self.blinks[i] < 0.13

    # -- one frame
    def frame(self, t, fi, lines, items, envelopes, danmaku):
        idx = max(0, bisect.bisect_right([it["start"] for it in items], t) - 1)
        before_first = t < items[0]["start"]
        line, it = lines[idx], items[idx]
        expr = line["expression"]

        # mouth: loudness-driven flap while the voice plays; typing-driven
        # flap for silent episodes
        talking = False
        if not before_first:
            env = envelopes[idx]
            if env:
                k = int((t - it["speak_start"]) * FPS)
                talking = 0 <= k < len(env) and env[k] > 0.18
            else:
                talking = it["start"] <= t < it["type_end"]
            talking = talking and (fi // 3) % 2 == 0
        key = expr + ("_talk" if talking else
                      "_blink" if self.is_blinking(t) else "")

        # body: idle bob + hop on expression change
        dy = 0 if int(t / 0.7) % 2 == 0 else 6
        if idx > 0 and not before_first and lines[idx - 1]["expression"] != expr:
            age = t - it["start"]
            if age < 0.10:
                dy = -18
            elif age < 0.20:
                dy = -8

        img = self.composite(key, expr, dy).copy()
        d = ImageDraw.Draw(img)

        if before_first:
            shadow_text(d, (90, 170), f"{self.name}的B站运营日记",
                        self.font_title, INK, shadow=DOT, offset=5)
            shadow_text(d, (100, 270), f"DAY {self.day}",
                        self.font_day, ORANGE, offset=9)

        for ev in danmaku:
            age = t - ev["start"]
            if age < 0:
                continue
            x = W - age * DANMAKU_SPEED
            if x < -ev["w"]:
                continue
            d.text((x, DANMAKU_LANES[ev["lane"]]), ev["text"],
                   font=self.font_danmaku, fill=WHITE,
                   stroke_width=3, stroke_fill=INK)

        if not before_first:
            font, wrapped = self.wrapped(line["text"])
            remaining = min(it["chars"], int((t - it["start"]) / CHAR_SEC) + 1)
            lh = int(font.size * 1.45)
            for li, wline in enumerate(wrapped):
                if remaining <= 0:
                    break
                d.text((TEXT_X, TEXT_Y + li * lh), wline[:remaining],
                       font=font, fill=INK)
                remaining -= len(wline)
            if t >= it["type_end"] + 0.3 and int(t * 2) % 2 == 0:
                cx, cy = BOX[2] - 44, BOX[3] - 30
                d.polygon([(cx, cy), (cx + 18, cy), (cx + 9, cy + 12)],
                          fill=ORANGE)
        return img


# ---------------------------------------------------------------- ffmpeg
def check_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit(
            "ffmpeg not found. Install it first:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg")


def _run(cmd, log_path):
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log)
    if proc.returncode != 0:
        tail = Path(log_path).read_text(errors="replace")[-1500:]
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


def mux_audio(video_only, audio_items, items, total_dur, bgm_path, out_path,
              workdir):
    voiced = [(p, items[i]["speak_start"]) for i, (p, _d) in enumerate(audio_items) if p]
    has_bgm = bool(bgm_path) and Path(bgm_path).exists()
    if not voiced and not has_bgm:
        os.replace(video_only, out_path)
        return
    cmd = ["ffmpeg", "-y", "-i", str(video_only)]
    filters, labels = [], []
    for j, (path, start) in enumerate(voiced):
        cmd += ["-i", str(path)]
        ms = int(start * 1000)
        filters.append(f"[{j + 1}:a]adelay={ms}|{ms}[v{j}]")
        labels.append(f"[v{j}]")
    if voiced:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
            f"normalize=0,apad,atrim=0:{total_dur:.3f}[voice]")
    if has_bgm:
        b = 1 + len(voiced)
        cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
        filters.append(f"[{b}:a]volume=0.10,atrim=0:{total_dur:.3f},"
                       f"afade=t=out:st={max(0, total_dur - 1.5):.3f}:d=1.5[bg]")
        filters.append("[voice][bg]amix=inputs=2:duration=first:normalize=0[aout]"
                       if voiced else "[bg]volume=1.4[aout]")
    else:
        filters.append("[voice]anull[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
            str(out_path)]
    _run(cmd, Path(workdir) / "ffmpeg-mux.log")


# ---------------------------------------------------------------- top level
def render_episode(*, lines, audio_items, persona_name, day, sprites_dir,
                   danmaku_texts, bgm_path, out_path, workdir, progress=True):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    scene = Scene(persona_name, day, sprites_dir)
    items, total_dur = build_timeline(lines, audio_items)
    envelopes = [loudness_envelope(p) if p else [] for p, _d in audio_items]
    danmaku = schedule_danmaku(danmaku_texts or [], TITLE_DUR - 0.8, total_dur,
                               scene._scratch, scene.font_danmaku)

    video_only = workdir / "video_only.mp4"
    n_frames = int(math.ceil(total_dur * FPS))
    log = open(workdir / "ffmpeg-video.log", "w")
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video_only)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
    try:
        for fi in range(n_frames):
            img = scene.frame(fi / FPS, fi, lines, items, envelopes, danmaku)
            proc.stdin.write(img.tobytes())
            if progress and fi % (FPS * 5) == 0:
                print(f"\r  rendering {fi / FPS:5.1f}s / {total_dur:.1f}s",
                      end="", flush=True)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    rc = proc.wait()
    log.close()
    if progress:
        print(f"\r  rendering {total_dur:5.1f}s / {total_dur:.1f}s")
    if rc != 0:
        tail = (workdir / "ffmpeg-video.log").read_text(errors="replace")[-1500:]
        raise RuntimeError(f"ffmpeg video encode failed:\n{tail}")

    mux_audio(video_only, audio_items, items, total_dur, bgm_path,
              Path(out_path), workdir)
    return {"duration": total_dur, "frames": n_frames,
            "line_starts": [it["start"] for it in items],
            "lip_sync": any(envelopes)}


def render_cover(*, persona_name, day, cover_text, expression, sprites_dir,
                 out_path):
    """1280x720 cover: big DAY number, a short hook, and the host."""
    img = make_background()
    d = ImageDraw.Draw(img)
    sprites = load_sprites(sprites_dir, height=680)
    spr = sprites.get(expression) or sprites.get("neutral")
    if spr is not None:
        img.paste(spr, (W - spr.width - 10, H - spr.height + 40), spr)
    f_title = _load_font(56, "black")
    f_day = _load_font(190, "black")
    shadow_text(d, (60, 50), f"{persona_name}的B站运营日记", f_title, INK,
                shadow=DOT, offset=5)
    shadow_text(d, (60, 120), f"DAY {day}", f_day, ORANGE, offset=11)
    if cover_text:
        size = 92
        while size > 40:
            f_hook = _load_font(size, "black")
            if d.textlength(cover_text, font=f_hook) <= 700:
                break
            size -= 6
        tw = d.textlength(cover_text, font=f_hook)
        x0, y0 = 50, 430
        d.rounded_rectangle([x0, y0, x0 + tw + 60, y0 + size + 56], radius=20,
                            fill=INK)
        d.rounded_rectangle([x0 - 8, y0 - 8, x0 + tw + 52, y0 + size + 48],
                            radius=20, fill=ORANGE, outline=INK, width=5)
        d.text((x0 + 22, y0 + 12), cover_text, font=f_hook, fill=WHITE,
               stroke_width=4, stroke_fill=INK)
    img.save(out_path)
    return out_path
