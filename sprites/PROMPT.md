# Make your own sprite set

The five files in this folder are the host's expressions:

| File          | Used when the host is…      |
| ------------- | --------------------------- |
| `neutral.png` | stating facts, greeting     |
| `happy.png`   | celebrating, inviting       |
| `smug.png`    | being pleased with itself   |
| `shocked.png` | seeing the view count       |
| `sad.png`     | apologising, bad stats      |

The PNGs shipped with the project are placeholders drawn in code by
`make_sprites.py`. To make the show yours, replace them:

1. **One character, five expressions.** Keep the same character, outfit and
   framing in every file — only the face changes. Consistency is what makes
   the character recognisable.
2. **Format:** PNG with a transparent background, roughly 4:5 portrait
   (the placeholders are 448×560). The renderer scales by height and anchors
   the sprite's feet to the bottom of the dialogue box.
3. **Image-generation prompt that works well** (for Midjourney / SDXL /
   ComfyUI / any image model):

   > pixel art chibi girl, long orange hair, white blouse with black ribbon,
   > orange skirt, full body, standing, front view, game sprite,
   > transparent background, clean silhouette, expression: happy

   Run it five times, once per expression (`neutral`, `happy`, `smug`,
   `shocked`, `sad`). If your tool cannot do transparent backgrounds, ask
   for a plain white background and remove it with any background-remover,
   or draw over a solid color and key it out.
4. **Live2D / real art also works** — any PNG with transparency is fine.
   Pixel art is only the placeholder style, not a requirement.
5. Drop the files in here with the exact names above. `diary.py` only
   generates placeholders for files that are missing, so yours are never
   overwritten.
