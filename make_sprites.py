# -*- coding: utf-8 -*-
"""
make_sprites.py — generate placeholder pixel-art expression sprites with Pillow.

The character is drawn on a 32x40 pixel grid (a chibi host with long orange
hair and a white/orange outfit) and upscaled with NEAREST so it stays crisp.

Outputs: sprites/<expr>.png plus <expr>_talk.png (mouth open) and
<expr>_blink.png (eyes closed) for neutral, happy, smug, shocked, sad.

These are PLACEHOLDERS. Drop your own PNGs with the same filenames into
sprites/ and diary.py will use yours instead (it only generates the ones
that are missing). See sprites/PROMPT.md for how to create a matching set.
"""
from pathlib import Path
from PIL import Image, ImageDraw

GRID_W, GRID_H = 32, 40
SCALE = 14  # 32*14=448 wide, 40*14=560 tall

PALETTE = {
    "H": (232, 134, 46),    # hair, main orange
    "d": (192, 95, 20),     # hair, shadow
    "l": (247, 178, 92),    # hair, highlight
    "S": (255, 223, 194),   # skin
    "c": (245, 163, 163),   # blush
    "W": (250, 246, 238),   # clothes, white
    "O": (232, 134, 46),    # clothes, orange
    "K": (51, 48, 46),      # dark (bow, shoes, eyes)
    "G": (242, 179, 61),    # gold accent
    "B": (120, 180, 240),   # tear blue
}

# The body/hair/outfit map. Face features (eyes/mouth) are drawn per
# expression on top of this base, so the face area stays plain skin here.
BASE_MAP = [
    "............HHHHHHHH............",
    "..........HHHHHHHHHHHH..........",
    ".........HlHHHHHHHHHHlH.........",
    "........HHlHHHHHHHHHHlHH........",
    ".......HHdHHHHHHHHHHHHdHH.......",
    "......HHHdHHSSSSSSSSHHdHHH......",
    "......HHdHHSSSSSSSSSSHHdHH......",
    ".....HHHdHSSSSSSSSSSSSHdHHH.....",
    ".....HHdHHSSSSSSSSSSSSHdHH......",
    ".....HHdHSSSSSSSSSSSSSHdHH......",
    "....HHHdHSSSSSSSSSSSSSHdHHH.....",
    "....HHdHHSSSSSSSSSSSSSHdHH......",
    "....HHdHSSSSSSSSSSSSSSHdHH......",
    "....HHdHSSSSSSSSSSSSSSHdHH......",
    "....HHdHSSccSSSSSSccSSSHdHH.....",
    "....HHHdHSSSSSSSSSSSHdHHH......",
    ".....HHdHHSSSSSSSSSSHdHH........",
    ".....HHHdHSSSSSSSSSHdHHH........",
    "......HHdHHSSSSSSHHdHHH.........",
    "......HHHdHHSSSSHHdHHHH.........",
    ".......HHdHHHSSHHdHHH...........",
    ".......HHdHWWWKWWWHdHH..........",
    "......HHHdHWWKKKWWWHdHHH........",
    "......HHdHWWWWWWWWWHdHH.........",
    "......HHdHWWWWWWWWWHdHH.........",
    "......HHdHOOOOOOOOOHdHH.........",
    "......HHdOOOOOOOOOOdHH..........",
    "......HHdOOOOOOOOOOdHH..........",
    "......SHHdOOOOOOOOOdHHHS........",
    "......SSSdOOOOOOOOOdSSS.........",
    ".......HdOWKWKWKWKOdH...........",
    ".......HdOOOOOOOOOOdH...........",
    "........dOOOOOOOOOOd............",
    ".........SSSSSSSSSS.............",
    ".........SSSSSSSSSS.............",
    ".........WWWWWWWWWW.............",
    ".........KKKK..KKKK.............",
    ".........KKKK..KKKK.............",
    "................................",
    "................................",
]

# Face anchor points on the grid (x, y). Eyes are 3 wide x 3 tall.
EYE_L = (11, 10)
EYE_R = (18, 10)
MOUTH_Y = 15


def _px(draw, x, y, ch):
    draw.point((x, y), fill=PALETTE[ch])


def _rect(draw, x, y, w, h, ch):
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=PALETTE[ch])


def draw_expression(img, name):
    """Draw eyes + mouth for one expression onto the base grid image."""
    d = ImageDraw.Draw(img)
    lx, ly = EYE_L
    rx, ry = EYE_R
    mx = 15  # mouth center x (mouth spans mx..mx+1)

    if name == "neutral":
        for ex, ey in (EYE_L, EYE_R):
            _rect(d, ex, ey, 3, 3, "K")
            _px(d, ex + 1, ey, "W")  # sparkle
        _rect(d, mx, MOUTH_Y, 2, 1, "K")
    elif name == "happy":
        for ex, ey in (EYE_L, EYE_R):  # ^^ closed eyes
            _px(d, ex, ey + 1, "K"); _px(d, ex + 1, ey, "K"); _px(d, ex + 2, ey + 1, "K")
        _px(d, mx, MOUTH_Y, "K"); _px(d, mx + 1, MOUTH_Y, "K")
        _px(d, mx, MOUTH_Y + 1, "K"); _px(d, mx + 1, MOUTH_Y + 1, "K")  # open smile
    elif name == "smug":
        for ex, ey in (EYE_L, EYE_R):  # half-lidded
            _rect(d, ex, ey, 3, 1, "K")
            _px(d, ex + 1, ey + 1, "K")
        _px(d, mx + 1, MOUTH_Y, "K"); _px(d, mx + 2, MOUTH_Y - 1, "K")  # smirk rising right
        _px(d, mx, MOUTH_Y, "K")
    elif name == "shocked":
        for ex, ey in (EYE_L, EYE_R):  # wide white eyes, tiny pupils
            _rect(d, ex, ey, 3, 3, "W")
            _px(d, ex + 1, ey + 1, "K")
        _rect(d, mx - 1, MOUTH_Y - 1, 3, 3, "K")  # O mouth: 3x3 ring
        _px(d, mx, MOUTH_Y, "S")
    elif name == "sad":
        for ex, ey in (EYE_L, EYE_R):  # droopy eyes
            _rect(d, ex, ey + 1, 3, 2, "K")
            _px(d, ex + 1, ey + 1, "W")
        _px(d, lx + 2, ly - 1, "K"); _px(d, rx, ry - 1, "K")  # worried brows, slanting up to center
        _px(d, mx, MOUTH_Y + 1, "K"); _px(d, mx + 1, MOUTH_Y + 1, "K")  # frown
        _px(d, mx - 1, MOUTH_Y, "K"); _px(d, mx + 2, MOUTH_Y, "K")
        _px(d, lx + 3, ly + 4, "B"); _px(d, lx + 3, ly + 5, "B")  # tear drop
    else:
        raise ValueError(f"unknown expression: {name}")
    return img


def _clear(d, x, y, w, h):
    _rect(d, x, y, w, h, "S")


def draw_talk_mouth(img):
    """Open mouth for lip-flap frames: 3 wide x 2 tall with a tongue pixel."""
    d = ImageDraw.Draw(img)
    _clear(d, 13, MOUTH_Y - 1, 5, 3)
    _rect(d, 14, MOUTH_Y, 3, 1, "K")
    _px(d, 14, MOUTH_Y + 1, "K"); _px(d, 15, MOUTH_Y + 1, "c"); _px(d, 16, MOUTH_Y + 1, "K")
    return img


def draw_blink(img):
    """Closed eyes: a single dark line where each eye was."""
    d = ImageDraw.Draw(img)
    for ex, ey in (EYE_L, EYE_R):
        _clear(d, ex, ey, 3, 3)
        _rect(d, ex, ey + 2, 3, 1, "K")
    return img


def _base_grid():
    img = Image.new("RGBA", (GRID_W, GRID_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(BASE_MAP):
        row = row.ljust(GRID_W, ".")[:GRID_W]
        for x, ch in enumerate(row):
            if ch != ".":
                d.point((x, y), fill=PALETTE[ch] + (255,))
    return img


def build_sprite(name, talk=False, blink=False):
    img = draw_expression(_base_grid(), name)
    if talk:
        draw_talk_mouth(img)
    if blink and name != "happy":  # happy already has closed eyes
        draw_blink(img)
    return img.resize((GRID_W * SCALE, GRID_H * SCALE), Image.NEAREST)


EXPRESSIONS = ["neutral", "happy", "smug", "shocked", "sad"]
VARIANTS = {"": {}, "_talk": {"talk": True}, "_blink": {"blink": True}}


def _is_placeholder(path, name):
    """True if the PNG on disk is exactly our generated placeholder."""
    try:
        on_disk = Image.open(path).convert("RGBA")
    except Exception:
        return False
    ref = build_sprite(name)
    return on_disk.size == ref.size and on_disk.tobytes() == ref.tobytes()


def ensure_sprites(sprites_dir):
    """
    Generate any missing placeholder sprites. Returns list of paths written.

    Talk (<expr>_talk.png) and blink (<expr>_blink.png) frames are generated
    only for placeholder bases. If you drop in your own <expr>.png, add your
    own _talk/_blink files too, or the host simply won't move its mouth.
    """
    sprites_dir = Path(sprites_dir)
    sprites_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in EXPRESSIONS:
        base = sprites_dir / f"{name}.png"
        if not base.exists():
            build_sprite(name).save(base)
            written.append(base)
        placeholder = None
        for suffix, kw in VARIANTS.items():
            if not suffix:
                continue
            p = sprites_dir / f"{name}{suffix}.png"
            if p.exists():
                continue
            if placeholder is None:
                placeholder = _is_placeholder(base, name)
            if placeholder:
                build_sprite(name, **kw).save(p)
                written.append(p)
    return written


if __name__ == "__main__":
    out = Path(__file__).parent / "sprites"
    written = ensure_sprites(out)
    for p in written:
        print("wrote", p)
    if not written:
        print("all sprites already exist in", out)
