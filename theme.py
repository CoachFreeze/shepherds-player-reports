"""
Per-program color themes. A program's dashboard and reports pick up its school colors automatically:

  1. a coach/admin override saved on the Team Dashboard (data/team/<program>.json -> "theme"), else
  2. colors read from the school's logo in assets/schools/ (plus the badge background when it's a color, e.g. Long Beach State's gold), else
  3. the default ShepSavant teal.

A theme is two picked colors (brand = dark header color, accent = buttons, links and highlights). Everything else is derived so text stays
readable on every background: accent_ink (accent darkened for text on white), on_accent (text on an accent button), accent_dark (hover),
accent_on_dark (accent for text on the brand-colored header).
"""
import colorsys
import functools
import os
import re

DEFAULT = {'brand': '#22303a', 'accent': '#5c97a8'}
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


# ------------------------------------------------------------------ color math
def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(c))) for c in rgb)


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hls(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _from_hls(h, l, s):
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s))))


def _shift(rgb, target_bg, want, direction):
    """Moves lightness (darker or lighter) until the color has `want` contrast against target_bg."""
    h, l, s = _hls(rgb)
    for _ in range(40):
        if contrast(_from_hls(h, l, s), target_bg) >= want:
            break
        l += 0.02 * direction
        if l <= 0.04 or l >= 0.96:
            break
    return _from_hls(h, l, s)


# ------------------------------------------------------------------ reading a logo
@functools.lru_cache(maxsize=64)
def _from_logo(path, badge_bg):
    """(brand hex, accent hex) from a logo PNG; None if it has no usable color."""
    from PIL import Image
    try:
        im = Image.open(path).convert('RGBA')
    except Exception:
        return None
    im.thumbnail((140, 140))
    px = [p for p in im.getdata() if p[3] > 200]
    if not px:
        return None
    dark_neutral = 0
    sectors = {}
    for r, g, b, _ in px:
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if l > 0.93 or (s < 0.12 and l > 0.25):          # white and gray: not a team color
            continue
        if s < 0.2 and l <= 0.25:
            dark_neutral += 1
            continue
        if s >= 0.35 and 0.1 < l < 0.8:
            k = int(h * 12) % 12                          # 30-degree hue sectors merge a color's shades
            a = sectors.setdefault(k, [0, 0, 0, 0])
            a[0] += 1
            a[1] += r
            a[2] += g
            a[3] += b
    chroma_n = sum(a[0] for a in sectors.values())
    clusters = sorted(([a[0], (a[1] / a[0], a[2] / a[0], a[3] / a[0])] for a in sectors.values() if a[0] >= 0.02 * max(chroma_n, 1)), key=lambda c: -c[0])
    total = len(px)
    if not clusters and not dark_neutral:
        return None
    top = clusters[0][1] if clusters else None
    if top is not None and _hls(top)[1] < 0.32:
        brand = top
    elif dark_neutral / total >= 0.15 or top is None:
        brand = (22, 25, 28)
    else:
        h, l, s = _hls(top)
        brand = _from_hls(h, 0.2, min(s, 0.6))
    neutral_brand = brand == (22, 25, 28)
    accent = _rgb(badge_bg) if (badge_bg and badge_bg.upper() != '#FFFFFF') else None
    if accent is None and top is not None:
        if neutral_brand:
            accent = top                                   # black + a color: the color is the accent
        else:
            th = _hls(top)[0]
            for n, c in clusters[1:]:                      # a real second team color (gold next to cardinal, orange next to navy)
                if n >= 0.08 * chroma_n and 0.3 < _hls(c)[1] < 0.85 and abs(((_hls(c)[0] - th + 0.5) % 1) - 0.5) > 0.11:
                    accent = c
                    break
            if accent is None:                             # one-color logo: the accent is that color, kept bright enough to read as a color
                h, l, s = _hls(top)
                accent = _from_hls(h, min(max(l, 0.42), 0.55), max(s, 0.55))
    if accent is None:
        accent = _rgb(DEFAULT['accent'])
    return _hex(brand), _hex(accent)


# ------------------------------------------------------------------ public API
def _valid(c):
    return bool(c) and bool(_HEX.match(c))


def _build(brand, accent):
    b, a = _rgb(brand), _rgb(accent)
    white = (255, 255, 255)
    ink = _shift(a, white, 4.5, -1)
    on_dark = _shift(a, b, 4.5, +1) if contrast(a, b) < 4.5 else a
    on_accent = '#ffffff' if contrast(white, a) >= contrast((27, 27, 27), a) else '#1b1b1b'
    h, l, s = _hls(a)
    return {'brand': _hex(b), 'accent': _hex(a), 'accent_ink': _hex(ink), 'accent_dark': _hex(_from_hls(h, l * 0.88, s)),
            'accent_on_dark': _hex(on_dark), 'on_accent': on_accent}


# Official school colors where the logo can't give them (Biola: red header with a blue stripe). A coach's saved override still wins.
PROGRAM_DEFAULTS = {'biola_university': ('#d2373f', '#5f9dda')}


def default_pair(program):
    """(brand, accent, source) the program would get with no override: logo colors, else the ShepSavant default."""
    import pipeline
    import store
    if program in PROGRAM_DEFAULTS:
        return PROGRAM_DEFAULTS[program][0], PROGRAM_DEFAULTS[program][1], 'school'
    entry = pipeline._badge_entry(store.program_label(program), program) if program else None
    if entry:
        fname, bg = entry
        got = _from_logo(os.path.join(pipeline.APP_DIR, 'assets', 'schools', fname), bg)
        if got:
            return got[0], got[1], 'logo'
    return DEFAULT['brand'], DEFAULT['accent'], 'default'


def for_program(program):
    """The full theme dict for a program (see module doc)."""
    brand, accent, src = default_pair(program)
    if program:
        try:
            import team
            ov = team.load(program).get('theme') or {}
            if _valid(ov.get('brand')) and _valid(ov.get('accent')):
                brand, accent, src = ov['brand'], ov['accent'], 'custom'
        except Exception:
            pass
    t = _build(brand, accent)
    t['source'] = src
    return t


def css(t):
    return (f":root{{--brand:{t['brand']};--accent:{t['accent']};--accent-ink:{t['accent_ink']};--accent-dark:{t['accent_dark']};"
            f"--accent-on-dark:{t['accent_on_dark']};--on-accent:{t['on_accent']};--accent-teal:{t['accent_ink']};}}")


def style_tag(program):
    return '<style>' + css(for_program(program)) + '</style>'
