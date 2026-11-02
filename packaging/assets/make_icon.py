#!/usr/bin/env python3
"""Gerador dos assets visuais de empacotamento (ícone do app + imagens do
assistente de instalação).

Por que um script em vez de binários commitados "soltos": os ícones precisam
existir em uma dúzia de tamanhos/formatos (PNG para o hicolor do Linux, ICO
multi-resolução para o Windows, BMP para as laterais do wizard do Inno Setup).
Gerar tudo a partir de uma única definição evita que as versões divirjam
quando a identidade visual mudar — basta reexecutar:

    python packaging/assets/make_icon.py

A paleta é a mesma de `ui/styles/dark_theme.qss`: preto levemente quente,
latão envelhecido como acento e teal desaturado. O motivo gráfico é a
perfuração de película de 35mm, o mesmo elemento de assinatura usado em
`ui/widgets/film_progress_delegate.py`.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).parent

BG_TOP = (24, 24, 27)
BG_BOTTOM = (11, 11, 12)
STRIP = (33, 33, 37)
STRIP_EDGE = (46, 46, 51)
BRASS = (200, 155, 60)
TEAL = (79, 163, 160)

MASTER = 1024
SS = 4  # supersampling: desenha grande e reduz, para ter antialiasing.

ICON_PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Gradiente vertical de 1px esticado — mais rápido que desenhar S linhas."""
    column = Image.new("RGB", (1, size))
    draw = ImageDraw.Draw(column)
    for y in range(size):
        t = y / max(size - 1, 1)
        draw.point(
            (0, y),
            fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)),
        )
    return column.resize((size, size), Image.NEAREST)


def render_icon(size: int = MASTER * SS) -> Image.Image:
    """Ícone do app: película de 35mm vertical com seta de download."""
    s = size
    layer = _vertical_gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(layer)

    # Faixa de película atravessando o ícone de ponta a ponta.
    strip_w = int(s * 0.58)
    x0 = (s - strip_w) // 2
    x1 = x0 + strip_w
    draw.rectangle([x0, 0, x1, s], fill=STRIP)
    edge = max(int(s * 0.006), 1)
    draw.rectangle([x0, 0, x0 + edge, s], fill=STRIP_EDGE)
    draw.rectangle([x1 - edge, 0, x1, s], fill=STRIP_EDGE)

    # Perfurações em latão nas duas bordas da película.
    hole_w = int(s * 0.072)
    hole_h = int(s * 0.052)
    hole_r = int(hole_w * 0.3)
    inset = int(s * 0.028)
    count = 7
    pitch = s / count
    for i in range(count):
        cy = pitch * (i + 0.5)
        top = cy - hole_h / 2
        bottom = cy + hole_h / 2
        draw.rounded_rectangle(
            [x0 + inset, top, x0 + inset + hole_w, bottom], radius=hole_r, fill=BRASS
        )
        draw.rounded_rectangle(
            [x1 - inset - hole_w, top, x1 - inset, bottom], radius=hole_r, fill=BRASS
        )

    # Seta de download em teal, no quadro central da película.
    cx = s / 2
    shaft_w = s * 0.105
    shaft_top = s * 0.265
    shaft_bottom = s * 0.565
    draw.rectangle([cx - shaft_w / 2, shaft_top, cx + shaft_w / 2, shaft_bottom], fill=TEAL)
    head_w = s * 0.255
    draw.polygon(
        [
            (cx - head_w / 2, shaft_bottom - s * 0.005),
            (cx + head_w / 2, shaft_bottom - s * 0.005),
            (cx, s * 0.76),
        ],
        fill=TEAL,
    )

    # Recorte com cantos arredondados (estilo ícone de app moderno).
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255
    )
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(layer, (0, 0), mask)
    return out


def render_wizard_panel(width: int, height: int) -> Image.Image:
    """Painel lateral do assistente de instalação (Inno Setup / QWizard).

    Mesma linguagem visual do ícone, mas em formato retrato: a película corre
    na vertical pela borda esquerda, deixando o resto livre para o texto.
    """
    img = _vertical_gradient(max(width, height), BG_TOP, BG_BOTTOM).resize((width, height))
    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)

    strip_w = int(width * 0.34)
    draw.rectangle([0, 0, strip_w, height], fill=STRIP)
    draw.rectangle([strip_w, 0, strip_w + max(int(width * 0.012), 1), height], fill=BRASS)

    hole_w = int(strip_w * 0.42)
    hole_h = int(height * 0.028)
    inset = int(strip_w * 0.12)
    pitch = hole_h * 2.6
    y = pitch * 0.4
    while y < height:
        draw.rounded_rectangle(
            [inset, y, inset + hole_w, y + hole_h],
            radius=max(int(hole_w * 0.3), 1),
            fill=BRASS,
        )
        draw.rounded_rectangle(
            [strip_w - inset - hole_w, y, strip_w - inset, y + hole_h],
            radius=max(int(hole_w * 0.3), 1),
            fill=BRASS,
        )
        y += pitch
    return img


def render_wizard_badge(size: int) -> Image.Image:
    """Ícone pequeno do canto do wizard — o próprio ícone do app reduzido."""
    return render_icon(size * SS).resize((size, size), Image.LANCZOS)


def _flatten(img: Image.Image, background: tuple[int, int, int] = BG_BOTTOM) -> Image.Image:
    """BMP não tem canal alfa; achata sobre o preto quente da identidade."""
    base = Image.new("RGB", img.size, background)
    base.paste(img, (0, 0), img)
    return base


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = render_icon()

    for size in ICON_PNG_SIZES:
        master.resize((size, size), Image.LANCZOS).save(ASSETS / f"icon_{size}.png")
    master.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")

    # ICO multi-resolução para o executável e o instalador do Windows.
    master.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "icon.ico", sizes=[(s, s) for s in ICO_SIZES]
    )

    # Imagens do wizard do Inno Setup (precisam ser BMP 24-bit).
    for name, (w, h) in {
        "wizard_large.bmp": (164, 314),
        "wizard_large@2x.bmp": (328, 628),
    }.items():
        _flatten(render_wizard_panel(w, h)).save(ASSETS / name)
    for name, px in {"wizard_small.bmp": 55, "wizard_small@2x.bmp": 110}.items():
        _flatten(render_wizard_badge(px)).save(ASSETS / name)

    # Painel do assistente do Linux (QWizard aceita PNG com alfa).
    render_wizard_panel(180, 420).save(ASSETS / "wizard_side.png")

    print(f"Assets gerados em {ASSETS}")


if __name__ == "__main__":
    main()
