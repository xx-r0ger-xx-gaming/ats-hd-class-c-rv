"""Contact sheet from rendered PNGs using Blender's image API + numpy (bundled with Blender).

Rows = variants, columns = views, each cell labelled with a built-in 5x7 pixel font (no deps).
"""
import numpy as np

import bpy

_GLYPHS = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    "_": "00000 00000 00000 00000 00000 00000 11111", "-": "00000 00000 00000 11111 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100", " ": "00000 00000 00000 00000 00000 00000 00000",
}


def _draw_text(canvas, text, x, y_top, scale=3, color=(1, 1, 1, 1)):
    """Draw uppercase text into an (H, W, 4) float array whose row 0 is the BOTTOM of the image."""
    h = canvas.shape[0]
    cx = x
    for ch in text.upper():
        rows = _GLYPHS.get(ch, _GLYPHS[" "]).split()
        for r, bits in enumerate(rows):
            for c, b in enumerate(bits):
                if b == "1":
                    y0 = h - (y_top + (r + 1) * scale)
                    canvas[y0:y0 + scale, cx + c * scale: cx + (c + 1) * scale] = color
        cx += 6 * scale


def _load_rgba(path, w, h):
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        img.scale(w, h)
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        return px.reshape(h, w, 4)
    finally:
        bpy.data.images.remove(img)


def make_contact_sheet(rows, views, out_path, cell=(640, 360), pad=12, label_h=34):
    """rows: [(variant_name, {view: png_path or None})]; writes out_path (PNG)."""
    cw, ch = cell
    ncol, nrow = len(views), len(rows)
    W = pad + ncol * (cw + pad)
    H = pad + nrow * (ch + label_h + pad)
    canvas = np.zeros((H, W, 4), dtype=np.float32)
    canvas[:, :] = (0.06, 0.06, 0.065, 1.0)
    for ri, (name, paths) in enumerate(rows):
        top = pad + ri * (ch + label_h + pad)
        for ci, view in enumerate(views):
            left = pad + ci * (cw + pad)
            _draw_text(canvas, f"{name}  {view}", left + 2, top + 8, scale=3, color=(0.92, 0.92, 0.9, 1))
            p = paths.get(view)
            y0 = H - (top + label_h + ch)
            if p is None:
                canvas[y0:y0 + ch, left:left + cw] = (0.12, 0.12, 0.13, 1)
                continue
            canvas[y0:y0 + ch, left:left + cw] = _load_rgba(p, cw, ch)
    img = bpy.data.images.new("contact_sheet", W, H, alpha=False)
    img.pixels.foreach_set(canvas.ravel())
    img.filepath_raw = str(out_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return W, H
