"""Blind A/B visual analysis of the rendered launcher screenshots.

Measures things a geometry audit cannot see:
  1. Large blank/empty regions in the content area (a view that renders mostly
     empty when data exists looks broken next to CF/Modrinth).
  2. Text contrast — sample non-background pixels and check they are bright
     enough against the dark theme.
  3. Composition — sidebar band vs content band proportions, and how much of
     the window is background vs cards.

Run:  pyqt/.venv/Scripts/python.exe pyqt/visual_ab.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PIL import Image
except ImportError:
    print("PIL not installed in pyqt/.venv — skipping pixel analysis")
    sys.exit(0)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


def analyze(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    # Sample grid of pixels (every 8px) for region stats.
    samples = []
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            samples.append((x, y, px[x, y]))
    # Page background is #111315 (17,19,21). CARDS are #191C1F (25,28,31) —
    # only the raw page bg counts as "empty", cards count as content.
    def is_page_bg(c):
        r, g, b = c
        return r <= 19 and g <= 21 and b <= 23

    def lum(c):
        r, g, b = c
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    content_frac = sum(1 for _, _, c in samples if not is_page_bg(c)) / len(samples)
    # Text-ish pixels: bright (>140 luminance) — measure contrast presence.
    bright = sum(1 for _, _, c in samples if lum(c) > 140) / len(samples)
    # Blank-region detection: largest contiguous page-bg blob inside the
    # CONTENT area only (right of the ~240px sidebar, below the ~70px topbar).
    grid = {}
    for x, y, c in samples:
        grid[(x // 8, y // 8)] = is_page_bg(c)
    content = [(x // 8, y // 8) for x, y, _ in samples if x > 240 and y > 70]
    if not content:
        return None
    seen = set()
    max_blob = 0
    for start in content:
        if start in seen or not grid.get(start):
            continue
        stack, blob = [start], 0
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            # Neighbours stay INSIDE the content region (never the sidebar).
            if not grid.get(p):
                continue
            blob += 1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                np_ = (p[0] + dx, p[1] + dy)
                if np_ in content and not seen.__contains__(np_):
                    stack.append(np_)
        max_blob = max(max_blob, blob)
    # blob cells are 8x8 px samples with 8px stride → each ≈ 64 px² area.
    blank_area_px = max_blob * 64
    content_area = (w - 240) * (h - 70)
    return {
        "size": f"{w}x{h}",
        "content_frac": round(content_frac, 2),
        "bright_frac": round(bright, 2),
        "largest_blank_area": blank_area_px,
        "largest_blank_pct": round(100 * blank_area_px / content_area, 1) if content_area > 0 else 0,
    }


def main():
    files = sorted(f for f in os.listdir(OUT) if f.endswith(".png"))
    if not files:
        print("no screenshots found in", OUT)
        return
    print("View                          content% text%  largest-blank")
    for f in files:
        r = analyze(os.path.join(OUT, f))
        if not r:
            continue
        flag = ""
        if r["largest_blank_pct"] > 45:
            flag += "  <-- LARGE EMPTY REGION"
        if r["bright_frac"] < 0.04:
            flag += "  <-- VERY LITTLE TEXT/UI"
        print(f"{f:<28} {r['content_frac']*100:5.1f}  {r['bright_frac']*100:5.1f}  {r['largest_blank_pct']:5.1f}%{flag}")


if __name__ == "__main__":
    main()
