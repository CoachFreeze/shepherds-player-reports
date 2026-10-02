"""
Builds the @font-face CSS block with real font files inlined as base64
data URIs, so every generated report stays a single self-contained HTML
file (same reasoning as assets.py for photos) — no dependency on the
fonts/ directory sitting next to the output file at render time.

"""
import os
import base64

FONTS_DIR = os.path.join(os.path.dirname(__file__), 'fonts')

# (family, filename, mime, format, weight)
_FONT_FILES = [
    ('KommonGrotesk', 'KommonGrotesk-Regular.ttf', 'font/ttf', 'truetype', 400),
    ('AspiraXXXNar', 'AspiraXXXNar-Heavy.otf', 'font/otf', 'opentype', 900),
    ('NeuePlakCond', 'NeuePlak-CondBold.ttf', 'font/ttf', 'truetype', 700),
    ('NeuePlakCond', 'NeuePlak-CondSemiBold.ttf', 'font/ttf', 'truetype', 600),
    ('NeuePlakCond', 'NeuePlak-CondRegular.ttf', 'font/ttf', 'truetype', 400),
    ('NeuePlak', 'NeuePlak-SemiBold.ttf', 'font/ttf', 'truetype', 600),
    ('NeuePlakText', 'NeuePlakText-Black.ttf', 'font/ttf', 'truetype', 900),
    ('NeuePlakText', 'NeuePlakText-Light.ttf', 'font/ttf', 'truetype', 300),
    ('Araboto', 'Araboto-Medium.ttf', 'font/ttf', 'truetype', 500),
    # Supplied file is Proxima Nova Condensed Regular (not Semibold as
    # originally pixel-sampled from the PDF) — close enough for the tiny
    # axis/distance tick labels this family is used for; swap in a true
    # Semibold weight later if you get one.
    ('ProximaNova', 'ProximaNova-Semibold.ttf', 'font/ttf', 'truetype', 400),
]


def _data_uri(path, mime):
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')
    return f'data:{mime};base64,{data}'


def build_font_face_css():
    rules = []
    for family, filename, mime, fmt, weight in _FONT_FILES:
        path = os.path.join(FONTS_DIR, filename)
        if not os.path.isfile(path):
            continue
        uri = _data_uri(path, mime)
        rules.append(
            f"@font-face{{ font-family:'{family}'; "
            f"src:url('{uri}') format('{fmt}'); font-weight:{weight}; }}"
        )
    return '\n'.join(rules)
