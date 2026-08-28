#!/usr/bin/env python
"""Deterministic generator for the calibration reference corpus.

Reproduces the four placeholder_*.jpg images. Usage:

    python generate_corpus.py [outdir]
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.ImageFilter import GaussianBlur

W = H = 1024


def coarse_noise(seed, scale, contrast=1.0):
    random.seed(seed)
    s = W // scale
    img = Image.new("L", (s, s))
    img.putdata(
        [int(128 + random.randint(-128, 127) * contrast) for _ in range(s * s)]
    )
    return img.resize((W, H), Image.LANCZOS).convert("RGB")


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    outdir.mkdir(parents=True, exist_ok=True)

    def save(img, name):
        img.save(outdir / name, quality=92)

    # placeholder_bokeh_subject.jpg
    bg = coarse_noise(1, 4).filter(GaussianBlur(22))
    subj = coarse_noise(2, 8, 0.5)
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    r = int(W * 0.5 / 2)
    cx, cy = W // 2, H // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    mask = mask.filter(GaussianBlur(6))
    save(Image.composite(subj, bg, mask), "placeholder_bokeh_subject.jpg")

    # placeholder_uniform_blur.jpg
    save(coarse_noise(3, 8, 0.5).filter(GaussianBlur(14)), "placeholder_uniform_blur.jpg")

    # placeholder_sharp.jpg
    save(coarse_noise(4, 8, 0.6), "placeholder_sharp.jpg")

    # placeholder_blur_with_speck.jpg
    img = coarse_noise(5, 8, 0.5).filter(GaussianBlur(14))
    draw = ImageDraw.Draw(img)
    for i in range(0, 24, 2):
        draw.line((980 + i % 12, 980, 980 + i % 12, 1004), fill=(255 if i % 4 else 0,) * 3)
    save(img, "placeholder_blur_with_speck.jpg")


if __name__ == "__main__":
    main()
