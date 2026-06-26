#!/usr/bin/env python3
"""Genera corrector_editorial.ico usando solo PIL (sin dependencias externas)."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import math

def crear_icono():
    sizes = [256, 128, 64, 48, 32, 16]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Fondo redondeado color vino/editorial
        r = int(size * 0.18)
        bg_color = (45, 20, 60, 255)         # púrpura oscuro
        accent   = (203, 166, 247, 255)       # lavanda
        page_col = (240, 235, 250, 255)       # casi blanco
        mark_red = (230, 37, 37, 255)         # rojo corrección

        # Fondo con esquinas redondeadas
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=bg_color)

        # Página interior (rectángulo blanco)
        m = int(size * 0.18)
        pw = size - m * 2
        ph = int(pw * 1.28)
        py = (size - ph) // 2
        corner = max(2, int(size * 0.04))
        draw.rounded_rectangle([m, py, m + pw, py + ph], radius=corner, fill=page_col)

        # Líneas de texto simuladas
        lx1 = m + int(pw * 0.12)
        lx2 = m + int(pw * 0.88)
        line_h = max(2, int(ph * 0.07))
        gap    = int(ph * 0.13)
        line_color = (180, 170, 200, 200)
        for li in range(4):
            ly = py + int(ph * 0.18) + li * gap
            # acortar la última línea
            x2 = lx2 if li < 3 else (lx1 + (lx2 - lx1) * 2 // 3)
            draw.rectangle([lx1, ly, x2, ly + line_h], fill=line_color)

        # Marca de corrección (ondulado rojo) — simplificado como línea gruesa roja
        wave_y = py + int(ph * 0.52)
        wave_w = max(2, int(size * 0.04))
        for xi in range(lx1, lx2, max(1, int(size * 0.06))):
            yo = int(math.sin((xi - lx1) / max(1, size * 0.04) * math.pi) * wave_w)
            x2c = min(xi + max(1, int(size * 0.06)), lx2)
            draw.line([(xi, wave_y + yo), (x2c, wave_y - yo)], fill=mark_red,
                      width=max(1, int(size * 0.025)))

        # Nota adhesiva en esquina superior derecha
        ns = int(size * 0.28)
        nx = m + pw - ns + int(size * 0.04)
        ny = py - int(size * 0.04)
        note_color = (250, 179, 135, 230)   # naranja claro
        draw.polygon([
            (nx, ny),
            (nx + ns, ny),
            (nx + ns, ny + ns),
            (nx + int(ns * 0.7), ny + ns),
            (nx, ny + int(ns * 0.7)),
        ], fill=note_color)
        # doblez de la nota
        fold = int(ns * 0.3)
        draw.polygon([
            (nx, ny + int(ns * 0.7)),
            (nx + fold, ny + ns),
            (nx + int(ns * 0.7), ny + ns),
        ], fill=(200, 140, 100, 200))

        images.append(img)

    out = Path(__file__).parent / "corrector_editorial.ico"
    images[0].save(str(out), format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=images[1:])
    print(f"Ícono guardado: {out}")
    return str(out)


if __name__ == "__main__":
    crear_icono()
