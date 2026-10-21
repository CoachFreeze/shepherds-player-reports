"""
Realistic baseball field for the spray chart, drawn in true feet so every distance is to scale.

Home plate is the origin; +y is toward center field, +x toward right field. A ball hit `distance` ft at `direction`
degrees (0 = center, + = right-field side) lands at x = d*sin(a), y = d*cos(a).
"""
import math

from savant_components import _ev_bucket_color

# outfield fence: 330 ft down the lines, about 375 in the gaps, 400 to center, one smooth curve
def fence_r(deg):
    a = max(-45.0, min(45.0, deg))
    return 330 + 70 * math.cos(a * math.pi / 90) ** 1.3


BASE = 63.64            # first base is 90 ft from home along the 45 degree line
MOUND = 60.5
THEMES = {
    'classic': {'bg': '#eef2ee', 'foul': '#e3eae3', 'grass_a': '#78b46f', 'grass_b': '#6aa764', 'dirt': '#c9a875', 'dirt_line': '#b99863',
                'track': '#b8975f', 'fence': '#31504f', 'chalk': '#ffffff', 'stripes': True, 'track_on': True, 'label': '#6c8a82'},
    'clean': {'bg': '#ffffff', 'foul': '#f3f6f4', 'grass_a': '#b2dfdb', 'grass_b': '#b2dfdb', 'dirt': '#c9aa73', 'dirt_line': '#b8985e',
              'track': '#b8985e', 'fence': '#7fb3ae', 'chalk': '#ffffff', 'stripes': False, 'track_on': False, 'label': '#7fb3ae'},
}


def make_svg(points, width=420, style='classic', fielders=None):
    """`fielders` (optional): [{'x', 'y' (feet), 'label', 'home_x', 'home_y'}] drawn over the field as a defensive alignment; the batted balls then become small quiet dots."""
    th = THEMES.get(style, THEMES['classic'])
    pad = 40
    xmax = fence_r(45) * math.sin(math.radians(45))
    k = (width - 2 * pad) / (2 * xmax)                     # px per foot
    top_ft, bottom_ft = 430, -28
    height = int((top_ft - bottom_ft) * k)
    cx = width / 2

    def P(x, y):
        return cx + x * k, (top_ft - y) * k

    def polar(dist, deg):
        r = math.radians(deg)
        return P(dist * math.sin(r), dist * math.cos(r))

    def pts(seq):
        return ' '.join(f'{x:.1f},{y:.1f}' for x, y in seq)

    degs = [d * 0.5 for d in range(-90, 91)]
    fence = [polar(fence_r(d), d) for d in degs]
    inner = [polar(fence_r(d) - 16, d) for d in degs]
    home = P(0, 0)
    fair = [home] + [polar(fence_r(-45), -45)] + fence + [polar(fence_r(45), 45)]
    s = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
         f'style="display:block;max-width:100%;height:auto;" font-family="Barlow,Arial,sans-serif">',
         '<defs><clipPath id="fairclip"><polygon points="' + pts(fair) + '"/></clipPath></defs>',
         f'<rect width="{width}" height="{height}" fill="{th["bg"]}"/>']
    # foul ground: a soft arc behind and beside the field
    fl, fr = polar(fence_r(-45) + 26, -45), polar(fence_r(45) + 26, 45)
    s.append(f'<polygon points="{pts([P(-18, -22), P(18, -22), fr, fr])}" fill="none"/>')
    foul = [P(0, -24)] + [P(-(fence_r(-45) + 22) * math.sin(math.radians(45)) - 6, (fence_r(-45) + 22) * math.cos(math.radians(45)))] \
        + [polar(fence_r(d) + 22, d) for d in degs[::4]] + [P((fence_r(45) + 22) * math.sin(math.radians(45)) + 6, (fence_r(45) + 22) * math.cos(math.radians(45)))]
    s.append(f'<polygon points="{pts(foul)}" fill="{th["foul"]}"/>')
    # fair territory grass (optionally mowed in arcs)
    s.append(f'<polygon points="{pts(fair)}" fill="{th["grass_a"]}"/>')
    if th['stripes']:
        s.append('<g clip-path="url(#fairclip)">')
        r, i = 440, 0
        while r > 0:
            if i % 2:
                s.append(f'<circle cx="{home[0]:.1f}" cy="{home[1]:.1f}" r="{r * k:.1f}" fill="{th["grass_b"]}"/>')
            r, i = r - 22, i + 1
        s.append('</g>')
    if th['track_on']:
        band = fence + inner[::-1]
        s.append(f'<polygon points="{pts(band)}" fill="{th["track"]}" fill-opacity=".85"/>')
    # infield: dirt circle around the mound, grass diamond inside, dirt around home and at the bases
    mx, my = P(0, MOUND)
    s.append(f'<g clip-path="url(#fairclip)"><circle cx="{mx:.1f}" cy="{my:.1f}" r="{95 * k:.1f}" fill="{th["dirt"]}" stroke="{th["dirt_line"]}" stroke-width=".6"/></g>')
    s.append(f'<circle cx="{home[0]:.1f}" cy="{home[1]:.1f}" r="{13.5 * k:.1f}" fill="{th["dirt"]}"/>')
    ctr = (0, BASE)
    dia = [(0, 0), (BASE, BASE), (0, 2 * BASE), (-BASE, BASE)]
    shrink = [P(ctr[0] + (x - ctr[0]) * 0.88, ctr[1] + (y - ctr[1]) * 0.88) for x, y in dia]
    s.append(f'<polygon points="{pts(shrink)}" fill="{th["grass_a"]}" stroke="{th["grass_a"]}" stroke-width="{7 * k:.1f}" stroke-linejoin="round"/>')
    for bx, by in [(BASE, BASE), (0, 2 * BASE), (-BASE, BASE)]:
        x, y = P(bx, by)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{9 * k:.1f}" fill="{th["dirt"]}"/>')
    s.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="{9 * k:.1f}" fill="{th["dirt"]}" stroke="{th["dirt_line"]}" stroke-width=".5"/>')
    s.append(f'<rect x="{mx - 2.2 * k:.1f}" y="{my - 0.5 * k:.1f}" width="{4.4 * k:.1f}" height="{1.0 * k:.1f}" fill="#fff"/>')
    # foul lines, fence, bases
    for a in (-45, 45):
        x, y = polar(fence_r(a), a)
        s.append(f'<line x1="{home[0]:.1f}" y1="{home[1]:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{th["chalk"]}" stroke-width="1.6" stroke-linecap="round"/>')
    s.append(f'<polyline points="{pts(fence)}" fill="none" stroke="{th["fence"]}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>')
    for bx, by in [(BASE, BASE), (0, 2 * BASE), (-BASE, BASE)]:
        x, y = P(bx, by)
        s.append(f'<rect x="{x - 3.3:.1f}" y="{y - 3.3:.1f}" width="6.6" height="6.6" fill="#fff" stroke="#b9c8c5" stroke-width=".6" transform="rotate(45 {x:.1f} {y:.1f})"/>')
    hx, hy = home
    s.append(f'<polygon points="{hx - 3.2:.1f},{hy - 1.5:.1f} {hx + 3.2:.1f},{hy - 1.5:.1f} {hx + 3.2:.1f},{hy + 1.6:.1f} {hx:.1f},{hy + 4.6:.1f} {hx - 3.2:.1f},{hy + 1.6:.1f}" fill="#fff" stroke="#b9c8c5" stroke-width=".6"/>')
    # distance labels just outside the fence
    for deg, d in [(-45, 330), (-22, 375), (0, 400), (22, 375), (45, 330)]:
        x, y = polar(fence_r(deg) + 20, deg)
        anchor = 'middle' if deg == 0 else ('end' if deg < 0 else 'start')
        s.append(f'<text x="{x:.1f}" y="{y + 3:.1f}" font-size="10.5" font-weight="700" fill="{th["label"]}" text-anchor="{anchor}">{d}</text>')
    # batted balls
    for pt in points:
        d = max(8, min(pt['distance'], fence_r(pt['direction']) + 18))
        x, y = polar(d, max(-50, min(50, pt['direction'])))
        if fielders:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#22303a" fill-opacity=".38"/>')
            continue
        ev = pt.get('ev')
        ev_txt = f'{ev:.1f} mph' if ev is not None else '—'
        dist_txt = f'{pt["distance"]:.0f} ft'
        la = '' if pt.get('la') is None else format(pt['la'], '.0f') + '°'
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="{_ev_bucket_color(ev)}" fill-opacity="0.92" stroke="#fff" stroke-width="1"/>')
        s.append(f'<circle class="bb-hit" cx="{x:.1f}" cy="{y:.1f}" r="9" fill="transparent" style="cursor:pointer;" data-ev="{ev_txt}" data-dist="{dist_txt}" '
                 f'data-la="{la}" data-type="{pt.get("type") or ""}" data-xba="{pt.get("xba") or ""}"/>')
    for fd in fielders or []:
        gx, gy = P(fd['home_x'], fd['home_y'])
        x, y = P(fd['x'], fd['y'])
        if abs(fd['x'] - fd['home_x']) + abs(fd['y'] - fd['home_y']) > 5:           # moved from the standard spot: ghost + dashed move
            s.append(f'<line x1="{gx:.1f}" y1="{gy:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#fff" stroke-width="1.3" stroke-dasharray="3 2.5" stroke-opacity=".9"/>')
            s.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="6.2" fill="none" stroke="#fff" stroke-width="1.2" stroke-opacity=".85"/>')
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.2" fill="#22303a" stroke="#fff" stroke-width="1.6"/>')
        s.append(f'<text x="{x:.1f}" y="{y + 3.6:.1f}" text-anchor="middle" font-size="10.5" font-weight="800" fill="#fff">{fd["label"]}</text>')
    s.append('</svg>')
    return ''.join(s)
