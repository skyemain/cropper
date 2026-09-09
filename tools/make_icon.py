"""Generate the application icon (assets/icon.png + assets/icon.ico).

Design: an ID-photo frame with a face outline and an eye-alignment line.
Run once at development time; the generated files are committed so the build
never depends on downloading or regenerating assets.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

BG = (30, 64, 124)  # deep blue
FRAME = (240, 244, 250)
FACE = (255, 214, 170)
HAIR = (68, 48, 34)
SHIRT = (88, 140, 200)
GUIDE = (80, 200, 120)


def draw_icon(size: int = 512) -> Image.Image:
    s = size / 512.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded background card.
    d.rounded_rectangle([16 * s, 16 * s, 496 * s, 496 * s], radius=88 * s, fill=BG)
    # Photo frame.
    d.rounded_rectangle([96 * s, 64 * s, 416 * s, 448 * s], radius=28 * s,
                        fill=FRAME, outline=(200, 210, 224), width=max(1, int(6 * s)))
    # Shoulders.
    d.pieslice([128 * s, 300 * s, 384 * s, 560 * s], 180, 360, fill=SHIRT)
    # Neck.
    d.rectangle([232 * s, 268 * s, 280 * s, 330 * s], fill=FACE)
    # Head.
    d.ellipse([176 * s, 120 * s, 336 * s, 312 * s], fill=FACE)
    # Hair.
    d.chord([176 * s, 104 * s, 336 * s, 240 * s], 180, 360, fill=HAIR)
    d.rectangle([176 * s, 168 * s, 200 * s, 216 * s], fill=HAIR)
    d.rectangle([312 * s, 168 * s, 336 * s, 216 * s], fill=HAIR)
    # Eyes.
    eye_y = 210 * s
    for ex in (222, 290):
        d.ellipse([(ex - 10) * s, eye_y - 10 * s, (ex + 10) * s, eye_y + 10 * s],
                  fill=(40, 40, 48))
    # Eye alignment guide line with end ticks.
    d.line([120 * s, eye_y, 392 * s, eye_y], fill=GUIDE, width=max(1, int(10 * s)))
    for tx in (120, 392):
        d.line([tx * s, eye_y - 22 * s, tx * s, eye_y + 22 * s],
               fill=GUIDE, width=max(1, int(10 * s)))
    # Crop corner marks.
    for cx, cy, dx, dy in ((60, 40, 1, 1), (452, 40, -1, 1),
                           (60, 472, 1, -1), (452, 472, -1, -1)):
        d.line([cx * s, cy * s, (cx + dx * 52) * s, cy * s],
               fill=FRAME, width=max(1, int(14 * s)))
        d.line([cx * s, cy * s, cx * s, (cy + dy * 52) * s],
               fill=FRAME, width=max(1, int(14 * s)))
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon(512)
    master.save(ASSETS / "icon.png")
    master.save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icon written to {ASSETS / 'icon.png'} and {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
