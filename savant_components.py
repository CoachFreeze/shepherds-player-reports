"""
Original recreations of three Baseball Savant-style visual components,
built from scratch (not copied source) to match their visual language:

  1. percentile_bars_html()   -- the diverging blue->red percentile rank bars
  2. movement_plot_svg()      -- horizontal/vertical break scatter
  3. spin_clock_row_svg()     -- per-pitch "spin direction" clock faces

Each returns a standalone HTML/SVG fragment you can drop into any page.
"""
import math
from html import escape

# ---------------------------------------------------------------------------
# 1. PERCENTILE RANKING BARS
# ---------------------------------------------------------------------------
# Savant's real chart uses a fixed diverging color scale across the WHOLE
# track (blue = 0th pctl, pale near the middle, red = 100th pctl), with a
# circular badge marking the player's value at its position. This differs
# from a simple "fill to X%" bar (which is what a generic percentile bar
# looks like) -- the gradient itself carries the scale, the badge is just a
# pointer on top of it.

_TRACK_BG = '#cddfdc'

# Continuous diverging scale matching the reference image: a smooth
# blue -> light gray/beige (~50) -> red (0-100) gradient, not the old
# discrete 5/6-bucket fill. Three RGB stops, linearly interpolated in
# between so every percentile value (not just bucket edges) gets its own
# shade.
_SCALE_STOPS = [
    (0,   (36, 90, 158)),    # blue
    (50,  (238, 232, 214)),  # light gray/beige midpoint
    (100, (185, 41, 42)),    # red
]

def _bucket_color(pct):
    pct = max(0, min(100, pct))
    for (p0, c0), (p1, c1) in zip(_SCALE_STOPS, _SCALE_STOPS[1:]):
        if p0 <= pct <= p1:
            t = (pct - p0) / (p1 - p0) if p1 != p0 else 0
            r = round(c0[0] + (c1[0] - c0[0]) * t)
            g = round(c0[1] + (c1[1] - c0[1]) * t)
            b = round(c0[2] + (c1[2] - c0[2]) * t)
            return f'#{r:02x}{g:02x}{b:02x}'
    return '#{:02x}{:02x}{:02x}'.format(*_SCALE_STOPS[-1][1])

def percentile_bars_html(rows, title=None, css_classes=True, badge_size=37, compact=False):
    """
    rows: list of {'label': str, 'pctl': int 0-100}
    Renders the ShepSavant-style bar: pale mint track, solid fill from left
    up to the player's percentile, and a circular badge at that position --
    matching the classes already defined in report.css (.scale-labels,
    .metric-row, .metric-track, .metric-fill, .metric-badge, .metric-value).

    badge_size must match whatever .metric-badge actually renders at in the
    calling context (report.css has a smaller override for the pitcher
    report's narrower 3-column layout) -- it's baked into this inline calc()
    so the badge stays centered on the percentile position instead of
    poking past the track edge. compact=True abbreviates "AVERAGE" to "AVG"
    for that same narrow column, where the full word would overlap POOR/GREAT.
    """
    # Reference ticks at 10/50/90% -- same x-positions as the POOR/AVERAGE/
    # GREAT header labels below -- drawn on every row so the eye can line
    # a bar's badge up against the scale without re-reading the header.
    ticks_html = ''.join(f'<span class="metric-tick" style="left:{x}%;"></span>' for x in (10, 50, 90))
    half = badge_size / 2

    bar_rows = []
    for r in rows:
        pctl = max(0, min(100, r['pctl']))
        color = _bucket_color(pctl)
        value_display = r.get('value_display', '')
        bar_rows.append(f'''
        <div class="metric-row">
          <div class="metric-label">{r['label']}</div>
          <div class="metric-track" style="background:{_TRACK_BG};">
            <div class="metric-fill" style="width:{pctl}%; background:{color};"></div>
            {ticks_html}
            <div class="metric-badge" style="left:calc({half:.0f}px + (100% - {badge_size:.0f}px) * {pctl} / 100); background:{color};">{pctl}</div>
          </div>
          <div class="metric-value">{value_display}</div>
        </div>''')
    # Header labels sit over the SAME track column as the bars (spacer +
    # track + spacer, matching .metric-row's label/track/value widths), so
    # 10/50/90% here land on the identical x-position as the ticks above.
    avg_label = 'AVG' if compact else 'AVERAGE'
    header = f'''
        <div class="scale-labels">
          <div class="scale-spacer-l"></div>
          <div class="scale-track">
            <div class="scale-mark poor" style="left:10%;">POOR<span class="tri"></span></div>
            <div class="scale-mark avg" style="left:50%;">{avg_label}<span class="tri"></span></div>
            <div class="scale-mark great" style="left:90%;">GREAT<span class="tri"></span></div>
          </div>
          <div class="scale-spacer-r"></div>
        </div>'''
    footnote = '<div class="footnote">*Percentiles vs. D2 benchmarks (Baseball America, NCAA, Baseball Savant)</div>'
    return f'{header}{"".join(bar_rows)}{footnote}'


# ---------------------------------------------------------------------------
# 2. PITCH MOVEMENT SCATTER (horizontal break vs vertical break)
# ---------------------------------------------------------------------------
# Savant's real "Pitch Movement" plot is a circular radar grid, not a square
# one: concentric rings at 6/12/18/24", a horizontal/vertical axis crosshair,
# "1B <- MOVES TOWARD -> 3B" along the top (fixed to the field, unlike
# arm-side/glove-side which flips with a pitcher's handedness), and
# "MORE RISE" / "MORE DROP" stacked labels down the left side.

def movement_plot_svg(pitches, width=340, height=340, max_range=24, all_pitches=False,
                      r24_frac=None, font_scale=1.0, pt_r=7, arm_badge=None):
    """
    arm_badge: {'angle': deg, 'throws': 'R'|'L'} -> Savant-style arm-angle badge in the bottom
    corner (right for a righty, left for a lefty).
    pitches: list of {'type': str, 'color': '#hex', 'hb': float, 'vb': float,
                       'points': [(hb, vb), ...]}  # optional individual pitches
    hb/vb in inches, raw (no handedness flip): +hb = toward 1B, -hb = toward 3B.
    all_pitches=True: plots every individual pitch in `points` as a 70%-opacity
    dot carrying data-* attributes (and an SVG <title>) so the page can show
    an IVB/HB tooltip on hover, and skips the bold per-type average marker.
    In that mode points are (hb, vb) or (hb, vb, velo) tuples.
    r24_frac: if set, the 24" ring takes that fraction of the canvas half-width
    and the wash/crosshair stop at the canvas edge -- the "fill the whole
    canvas" layout used for the big Trackman-report plot (default layout
    reserves a fixed 48px margin instead). font_scale/pt_r scale labels and
    dot size to match.
    """
    cx, cy = width / 2, height / 2
    # r24 is the true 24" ring's pixel radius, and scale (px per inch) is
    # derived from it directly -- NOT from max_range. The rings drawn below
    # are always at the fixed 6/12/18/24" marks regardless of max_range, so
    # tying scale to max_range (previously 64/20 = 3.2 px/in) made the "24"
    # ring actually render at 24*3.2 = 76.8px while r24=64 was used for the
    # wash/axis math -- a hidden 20% mismatch. Deriving scale from the real
    # 24" ring instead means every ring, tick label, and plotted pitch point
    # uses one consistent inches-to-pixels conversion.
    # r24 scales with the canvas (fixed 48px margin reserved outside it for
    # the wash/axis/label extension) rather than being a hardcoded pixel
    # value, so bumping width/height up also grows the ring automatically.
    if r24_frac:
        half = min(width, height) / 2
        r24 = half * r24_frac
        wash_r = min(r24 * 1.25, half - 2)
        axis_end = wash_r
    else:
        r24 = min(width, height) / 2 - 48
        wash_r = r24 * 1.25
        axis_end = wash_r * 1.15
    scale = r24 / 24

    def to_xy(hb, vb):
        return cx + hb * scale, cy - vb * scale

    # single unified slate-blue for every line/label in the chart, plus a
    # pale wash fill behind the rings, matching the client's reference chart
    # exactly (previously this used two different tones for rings vs axis).
    line_col = '#7c96a5'
    wash_fill = '#e9f1f4'
    label_col = line_col

    svg = [f'<svg class="{"mv-plot" if all_pitches else ""}" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'xmlns="http://www.w3.org/2000/svg" font-family="ProximaNova,Helvetica Neue,Arial,sans-serif">']

    # pale wash fill -- sits outside the 24" ring rather than stopping
    # flush at it, and the crosshair extends past the wash's outer edge too
    svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{wash_r:.1f}" fill="{wash_fill}" stroke="none"/>')

    # concentric rings at 6/12/18/24", alternating dashed/solid like the real chart
    for d in (6, 12, 18, 24):
        r = d * scale
        dash = '' if d in (12, 24) else ' stroke-dasharray="3,3"'
        svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{line_col}" stroke-width="1.3"{dash}/>')

    # axis crosshair extends past the 24" ring by axis_ext, so the outermost
    # tick label has room to sit past the ring instead of on top of its stroke
    svg.append(f'<line x1="{cx-axis_end:.1f}" y1="{cy:.1f}" x2="{cx+axis_end:.1f}" y2="{cy:.1f}" stroke="{line_col}" stroke-width="1.6"/>')
    svg.append(f'<line x1="{cx:.1f}" y1="{cy-axis_end:.1f}" x2="{cx:.1f}" y2="{cy+axis_end:.1f}" stroke="{line_col}" stroke-width="1.6"/>')

    # horizontal tick labels: all four rings (6/12/18/24") on the 1B (left)
    # side, only 12/24" on the 3B (right) side, matching the reference.
    # Every label sits at its TRUE ring radius (d*scale) -- same rule for
    # all four -- so each number actually marks where that ring is, rather
    # than the 24" label floating out at the decorative axis extension.
    # Font sizes bumped ~30% across the whole chart for legibility, since
    # the canvas itself is capped by the column width it has to fit in.
    tick_fs = 11 * font_scale
    for d in (6, 12, 18, 24):
        x = cx - d * scale
        svg.append(f'<text x="{x:.1f}" y="{cy-7:.1f}" font-size="{tick_fs}" fill="{label_col}" text-anchor="middle">{d}&quot;</text>')
    for d in (12, 24):
        x = cx + d * scale
        svg.append(f'<text x="{x:.1f}" y="{cy-7:.1f}" font-size="{tick_fs}" fill="{label_col}" text-anchor="middle">{d}&quot;</text>')
    # vertical tick labels at 12/24", also at their true ring radius
    for d in (12, 24):
        for sign in (1, -1):
            y = cy - sign * d * scale
            svg.append(f'<text x="{cx+9:.1f}" y="{y+4:.1f}" font-size="{tick_fs}" fill="{label_col}" text-anchor="start">{d}&quot;</text>')

    # "MORE RISE" / "MORE DROP" stacked labels, sitting clear outside the
    # 24" ring (not just outside the canvas margin), and laid out as exact
    # mirror images of each other around the horizontal axis (cy) so the
    # pair reads as centered on it rather than the drop block hanging lower
    # than the rise block sits high.
    label_fs, tri_fs = 12 * font_scale, 13 * font_scale
    if r24_frac:
        # sit just inside the wash's left edge at the label's own height
        label_x = cx - math.sqrt(max(wash_r ** 2 - (r24 * 0.55 + 20) ** 2, 0)) + 8
    else:
        label_x = max(6, cx - axis_end - 32)
    rise_y = cy - r24 * 0.55
    svg.append(f'<text x="{label_x}" y="{rise_y-13:.1f}" font-size="{label_fs}" font-weight="700" fill="{label_col}">MORE</text>')
    svg.append(f'<text x="{label_x}" y="{rise_y+4:.1f}" font-size="{label_fs}" font-weight="700" fill="{label_col}">RISE</text>')
    svg.append(f'<text x="{label_x}" y="{rise_y+19:.1f}" font-size="{tri_fs}" fill="{label_col}">&#9650;</text>')
    drop_y = cy + r24 * 0.55
    svg.append(f'<text x="{label_x}" y="{drop_y-19:.1f}" font-size="{tri_fs}" fill="{label_col}">&#9660;</text>')
    svg.append(f'<text x="{label_x}" y="{drop_y-4:.1f}" font-size="{label_fs}" font-weight="700" fill="{label_col}">MORE</text>')
    svg.append(f'<text x="{label_x}" y="{drop_y+13:.1f}" font-size="{label_fs}" font-weight="700" fill="{label_col}">DROP</text>')

    if all_pitches:
        for p in pitches:
            color = p['color']
            if not p.get('points'):
                # no individual pitches for this type (e.g. placeholder data) -> keep the bold average marker
                x, y = to_xy(p['hb'], p['vb'])
                svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{pt_r + 0.8}" fill="{color}" fill-opacity="0.7" stroke="#fff" stroke-width="1.7"/>')
            for pt in p.get('points', []):
                hb, vb = pt[0], pt[1]
                velo = pt[2] if len(pt) > 2 else None
                x, y = to_xy(hb, vb)
                tip = f'{p["type"]}  IVB {vb:.1f}\u2033 \u00b7 HB {hb:.1f}\u2033' + (f' \u00b7 {velo:.1f} mph' if velo else '')
                extra = (f' data-uid="{escape(str(pt[3]), quote=True)}" data-date="{escape(str(pt[4]), quote=True)}"' if len(pt) > 4 else '')
                svg.append(
                    f'<circle class="mv-pt" cx="{x:.1f}" cy="{y:.1f}" r="{pt_r}" fill="{color}" fill-opacity="0.7" '
                    f'stroke="{color}" stroke-width="1" data-tip="{tip}" data-ptype="{p["type"]}" data-pcolor="{color}" '
                    + (f'data-pvelo="{velo:.1f}" ' if velo else '') + f'data-pivb="{vb:.1f}" data-phb="{hb:.1f}"{extra}/>')
        # hover-isolate layer: one hidden group per pitch type -- a big circle at the type's average movement with lines out to
        # the axes (shown by the legend's hover script, see MOVEMENT_ISO_JS). Drawn last so it sits above the dimmed dots.
        throws = (arm_badge or {}).get('throws') or 'R'
        for p in pitches:
            if p.get('hb') is None or p.get('vb') is None:
                continue
            color, hb, vb = p['color'], p['hb'], p['vb']
            x, y = to_xy(hb, vb)
            arm_side = (hb < 0) if throws == 'L' else (hb > 0)
            rise = f'{vb:.1f}" IVB'
            run = f'{hb:.1f}" HB'
            fs = 12 * font_scale
            halo = 'paint-order="stroke" stroke="#fff" stroke-width="4" stroke-linejoin="round"'
            hx = (x + cx) / 2
            vy = (y + cy) / 2
            svg.append(
                f'<g class="mv-hl" data-ptype="{p["type"]}" style="display:none;pointer-events:none">'
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="3"/>'
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{cy:.1f}" stroke="{color}" stroke-width="3"/>'
                f'<text x="{cx + (-9 if x >= cx else 9):.1f}" y="{y + fs * 0.36:.1f}" font-size="{fs:.1f}" font-weight="800" fill="{color}" text-anchor="{"end" if x >= cx else "start"}" {halo}>{rise}</text>'
                f'<text x="{x:.1f}" y="{cy + (fs + 8 if y <= cy else -9):.1f}" font-size="{fs:.1f}" font-weight="800" fill="{color}" text-anchor="middle" {halo}>{run}</text>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{pt_r * 2.7:.1f}" fill="{color}" stroke="#fff" stroke-width="2.5"/>'
                f'<text x="{x:.1f}" y="{y + fs * 0.36:.1f}" font-size="{fs:.1f}" font-weight="800" fill="#fff" text-anchor="middle" '
                f'style="text-shadow:0 0 3px rgba(0,0,0,.35)">AVG</text></g>')
        svg.append(_arm_badge_svg(arm_badge, width, height))
        svg.append('</svg>')
        return ''.join(svg)

    # individual pitch cloud (light) then bold average marker per type
    for p in pitches:
        color = p['color']
        for (hb, vb) in p.get('points', []):
            x, y = to_xy(hb, vb)
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" fill-opacity="0.4"/>')
    for p in pitches:
        x, y = to_xy(p['hb'], p['vb'])
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7.8" fill="{p["color"]}" stroke="#fff" stroke-width="1.7"/>')

    svg.append(_arm_badge_svg(arm_badge, width, height))
    svg.append('</svg>')
    return ''.join(svg)


def movement_plot_caption_html():
    """'1B <- MOVES TOWARD -> 3B' subtitle, sits above the SVG (outside it) so
    it reuses the report's real heading font/colors. No rule under it, per
    the client's reference chart -- just the caption directly under the
    chart title."""
    return ('<div class="movement-caption">'
            '1B &#9666; MOVES TOWARD &#9656; 3B'
            '</div>')


MOVEMENT_ISO_JS = '''<style>.movement-legend [data-ptype]{cursor:pointer;transition:opacity .12s;} .mv-plot .mv-pt{transition:opacity .12s;}</style>
<script>(function(){document.querySelectorAll('.movement-legend:not([data-iso])').forEach(function(lg){lg.setAttribute('data-iso','1');
var box=lg.parentNode,svg=box.querySelector('svg.mv-plot');if(!svg)return;
var pts=svg.querySelectorAll('.mv-pt'),hls=svg.querySelectorAll('.mv-hl'),cells=lg.querySelectorAll('[data-ptype]'),cur=null;
function on(t){cur=t;pts.forEach(function(p){p.style.opacity=p.getAttribute('data-ptype')===t?'1':'.15';});hls.forEach(function(h){h.style.display=h.getAttribute('data-ptype')===t?'block':'none';});cells.forEach(function(c){c.style.opacity=c.getAttribute('data-ptype')===t?'1':'.25';});}
function off(){cur=null;pts.forEach(function(p){p.style.opacity='';});hls.forEach(function(h){h.style.display='none';});cells.forEach(function(c){c.style.opacity='';});}
cells.forEach(function(c){c.addEventListener('mouseenter',function(){on(c.getAttribute('data-ptype'));});c.addEventListener('click',function(e){e.stopPropagation();var t=c.getAttribute('data-ptype');if(cur===t)off();else on(t);});});
lg.addEventListener('mouseleave',off);document.addEventListener('click',function(e){if(cur&&!lg.contains(e.target))off();});
});})();</script>'''


def pitch_usage_legend_html(pitches):
    """
    pitches: list of {'type': str, 'color': '#hex', 'pct': float (0-100),
                       'velo': float|None, 'top_velo': float|None}, already
    sorted by usage descending.
    Renders the color-pill + USAGE/MPH/TOP MPH mini-table that sits under
    the movement plot, matching the reference layout: a colored pill per
    pitch (width scaled to usage%) over a 3-row stat table.
    """
    if not pitches:
        return ''
    max_pct = max((p.get('pct') or 0) for p in pitches) or 1
    cells_header, cells_pill, cells_usage, cells_mph, cells_top = [], [], [], [], []
    for p in pitches:
        pct = p.get('pct') or 0
        pill_w = 20 + round(38 * (pct / max_pct))
        color = p['color']
        d = f'data-ptype="{p["type"]}"'
        cells_header.append(f'<div class="ml-cell ml-name" {d}>{p["type"]}</div>')
        cells_pill.append(f'<div class="ml-cell" {d}><span class="ml-pill" style="width:{pill_w}px;background:{color};"></span></div>')
        cells_usage.append(f'<div class="ml-cell" {d}>{pct:.1f}%</div>')
        cells_mph.append(f'<div class="ml-cell" {d}>{p["velo"]:.1f}</div>' if p.get('velo') is not None else f'<div class="ml-cell" {d}>&mdash;</div>')
        cells_top.append(f'<div class="ml-cell" {d}>{p["top_velo"]:.1f}</div>' if p.get('top_velo') is not None else f'<div class="ml-cell" {d}>&mdash;</div>')
    return (
        '<div class="movement-legend">'
        f'<div class="ml-row ml-header"><div class="ml-label"></div>{"".join(cells_header)}</div>'
        f'<div class="ml-row ml-pills"><div class="ml-label"></div>{"".join(cells_pill)}</div>'
        f'<div class="ml-row"><div class="ml-label">USAGE</div>{"".join(cells_usage)}</div>'
        f'<div class="ml-row"><div class="ml-label">MPH</div>{"".join(cells_mph)}</div>'
        f'<div class="ml-row"><div class="ml-label ml-italic">TOP MPH</div>{"".join(cells_top)}</div>'
        '</div>' + MOVEMENT_ISO_JS
    )


# ---------------------------------------------------------------------------
# 3. SPIN DIRECTION CLOCK FACES
# ---------------------------------------------------------------------------
# Savant plots, for each pitch type, a small clock: "spin-based" direction
# (what the spin axis alone would predict, shown as a hollow/dashed marker)
# vs. "observed" direction (the actual measured movement axis, shown solid),
# with the numeric deviation between them in degrees.

def _clock_to_angle(clock_str):
    """'7:15' -> degrees clockwise from 12 o'clock."""
    h, m = clock_str.split(':')
    h, m = int(h) % 12, int(m)
    total_min = h * 60 + m
    return total_min / 720 * 360

def _clock_point(cx, cy, r, clock_str):
    angle = math.radians(_clock_to_angle(clock_str) - 90)
    return cx + r * math.cos(angle), cy + r * math.sin(angle)

def spin_clock_svg(pitch_type, spin_based, observed, deviation_deg, color, size=110):
    cx, cy = size / 2, size / 2
    r = size / 2 - 16
    svg = [f'<svg width="{size}" height="{size+34}" viewBox="0 0 {size} {size+34}" xmlns="http://www.w3.org/2000/svg" font-family="ProximaNova,Helvetica Neue,Arial,sans-serif">']
    svg.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="#ccc" stroke-width="1.5"/>')
    # tick marks at each hour
    for h in range(12):
        a = math.radians(h * 30 - 90)
        x1, y1 = cx + (r - 4) * math.cos(a), cy + (r - 4) * math.sin(a)
        x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
        svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ccc" stroke-width="1"/>')
    # spin-based: dashed line + hollow marker
    sx, sy = _clock_point(cx, cy, r - 8, spin_based)
    svg.append(f'<line x1="{cx}" y1="{cy}" x2="{sx:.1f}" y2="{sy:.1f}" stroke="#999" stroke-width="1.5" stroke-dasharray="3,2"/>')
    svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="#fff" stroke="#999" stroke-width="2"/>')
    # observed: solid line + filled marker (pitch color)
    ox, oy = _clock_point(cx, cy, r - 8, observed)
    svg.append(f'<line x1="{cx}" y1="{cy}" x2="{ox:.1f}" y2="{oy:.1f}" stroke="{color}" stroke-width="2"/>')
    svg.append(f'<circle cx="{ox:.1f}" cy="{oy:.1f}" r="5.5" fill="{color}" stroke="#fff" stroke-width="1"/>')
    svg.append(f'<circle cx="{cx}" cy="{cy}" r="2" fill="#333"/>')
    # labels below
    svg.append(f'<text x="{cx}" y="{size+14}" font-size="11" font-weight="700" fill="#222" text-anchor="middle">{pitch_type}</text>')
    svg.append(f'<text x="{cx}" y="{size+28}" font-size="9" fill="#888" text-anchor="middle">{deviation_deg}&#176; deviation</text>')
    svg.append('</svg>')
    return ''.join(svg)

def spin_clock_row_svg(pitches):
    """pitches: list of {'type','spin_based','observed','deviation','color'}"""
    cells = [spin_clock_svg(p['type'], p['spin_based'], p['observed'], p['deviation'], p['color']) for p in pitches]
    legend = '''
    <div style="font:500 9.5px Arial,sans-serif;color:#666;margin-top:14px;padding-top:10px;border-top:1px solid #eee;">
      <span style="margin-right:20px;">&#9675; dashed = spin-based (expected)</span>
      <span>&#9679; solid = observed (actual)</span>
    </div>'''
    cell_html = ''.join(f'<div style="display:inline-block;margin-right:18px;vertical-align:top;">{c}</div>' for c in cells)
    return f'<div><div>{cell_html}</div>{legend}</div>'


# ---------------------------------------------------------------------------
# 4. SPRAY CHART (hitter batted-ball location, colored by exit velo bucket)
# ---------------------------------------------------------------------------

def _ev_bucket_color(ev):
    if ev is None: return '#9aa4a8'
    if ev < 70: return '#f4f1e8'
    if ev < 80: return '#ffd23f'
    if ev < 90: return '#ff8c42'
    if ev < 100: return '#e63946'
    return '#7b2cbf'

def spray_chart_svg(points, width=380, height=340):
    """Reference-matched fan-shaped outfield: an asymmetric arc that's
    deepest in straightaway center (380') and shallower down the lines
    (310'), with 345' at the gaps -- not a simple circular arc. Field
    fill/labels use the report's existing pale-teal palette."""
    margin_top = 34     # room for the "380" label above the arc apex
    margin_bottom = 16
    home = (width / 2, height - margin_bottom)
    max_dist = 380
    scale = (height - margin_top - margin_bottom) / max_dist

    def field_r(deg):
        """Wall distance (ft) at a given angle off dead center, matching
        the 310 (foul line) / 345 (gap) / 380 (center) reference stops."""
        a = abs(deg)
        if a <= 22.5:
            return 380 - (380 - 345) * (a / 22.5)
        return 345 - (345 - 310) * ((a - 22.5) / 22.5)

    def polar(dist, deg):
        rad = math.radians(deg)
        x = home[0] + dist * scale * math.sin(rad)
        y = home[1] - dist * scale * math.cos(rad)
        return x, y

    def wall_pt(deg):
        return polar(field_r(deg), deg)

    fl_l, fl_r = wall_pt(-45), wall_pt(45)
    arc_deg = [d * 0.5 for d in range(-90, 91)]  # -45..45 in 0.5-degree steps
    arc_pts = ' '.join(f'{wall_pt(d)[0]:.1f},{wall_pt(d)[1]:.1f}' for d in arc_deg)

    field_teal = '#b2dfdb'       # Baseball Savant's actual grass fill (#grass)
    field_line = '#93c7c2'
    label_col = '#7fb3ae'

    svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    svg.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    svg.append(f'<polygon points="{home[0]:.1f},{home[1]:.1f} {fl_l[0]:.1f},{fl_l[1]:.1f} {arc_pts} {fl_r[0]:.1f},{fl_r[1]:.1f}" fill="{field_teal}" stroke="{field_line}" stroke-width="1"/>')
    svg.append(f'<line x1="{home[0]:.1f}" y1="{home[1]:.1f}" x2="{fl_l[0]:.1f}" y2="{fl_l[1]:.1f}" stroke="#ffffff" stroke-width="1.1"/>')
    svg.append(f'<line x1="{home[0]:.1f}" y1="{home[1]:.1f}" x2="{fl_r[0]:.1f}" y2="{fl_r[1]:.1f}" stroke="#ffffff" stroke-width="1.1"/>')

    # Distance markers (310 / 345 / 380), positioned just outside the wall
    # along the same radial angle as their measurement.
    fs = max(8.5, width / 21)
    for deg, dist in [(-45, 310), (-22.5, 345), (0, 380), (22.5, 345), (45, 310)]:
        lx, ly = polar(field_r(deg) + 15, deg)
        anchor = 'middle' if deg == 0 else ('end' if deg < 0 else 'start')
        dy = -2 if deg == 0 else 3
        svg.append(f'<text x="{lx:.1f}" y="{ly + dy:.1f}" font-family="Arial,sans-serif" font-size="{fs:.1f}" font-weight="700" fill="{label_col}" text-anchor="{anchor}">{dist}</text>')

    # Infield dirt (tan "infield_sand" shape, pixel-sampled from Savant's
    # own SVG path): a rounded sector, deepest behind 2B and tapering into
    # lanes down to a home-plate circle, with a subtle notch at each base
    # where its cutout circle meets the boundary. A teal infield-grass
    # diamond sits inset inside it -- since the diamond is drawn on top,
    # the dirt sector fill only needs to be the pie-slice from home to the
    # arc; the diamond covers the middle, leaving the dirt visible as a
    # frame around it, same as the source shape.
    hx, hy = home
    base_dist = 90
    b2_dist = base_dist * math.sqrt(2)
    r_corner, r_top = base_dist + 55, b2_dist + 40  # dirt-sector radii
    dirt_fill = '#c9aa73'    # tan/sand -- placeholder until the real hex is confirmed
    dirt_line = '#b8985e'

    def dirt_r(deg):
        # Smooth outer arc -- no notches here. The source shape's scallops
        # are on the INNER edge (where the grass diamond's corners meet
        # the dirt), not the outer boundary, which stays a clean curve.
        t0, t45 = math.cos(0), math.cos(math.radians(45))
        return r_corner + (r_top - r_corner) * (math.cos(math.radians(deg)) - t45) / (t0 - t45)

    dirt_deg = [d * 0.5 for d in range(-90, 91)]
    dirt_pts = ' '.join(f'{polar(dirt_r(d), d)[0]:.1f},{polar(dirt_r(d), d)[1]:.1f}' for d in dirt_deg)
    dirt_l, dirt_r_pt = polar(dirt_r(-45), -45), polar(dirt_r(45), 45)
    svg.append(f'<polygon points="{hx:.1f},{hy:.1f} {dirt_l[0]:.1f},{dirt_l[1]:.1f} {dirt_pts} {dirt_r_pt[0]:.1f},{dirt_r_pt[1]:.1f}" fill="{dirt_fill}" stroke="{dirt_line}" stroke-width="0.5"/>')
    # Round out the sharp point where the lanes converge at home into a
    # circular plate patch, matching the source shape's rounded home tip.
    svg.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="9" fill="{dirt_fill}" stroke="{dirt_line}" stroke-width="0.5"/>')

    p1b, p2b, p3b = polar(base_dist, 45), polar(b2_dist, 0), polar(base_dist, -45)

    # Infield grass diamond -- same color as the outfield, no border, so it
    # reads as a hole in the dirt rather than a separate sticker on top.
    svg.append(f'<polygon points="{hx:.1f},{hy:.1f} {p1b[0]:.1f},{p1b[1]:.1f} {p2b[0]:.1f},{p2b[1]:.1f} {p3b[0]:.1f},{p3b[1]:.1f}" fill="{field_teal}"/>')

    # Small notches where the diamond's own corners meet the dirt (base
    # cutouts), and the pitcher's mound as a dirt circle inset in the grass.
    for corner in (p1b, p2b, p3b):
        svg.append(f'<circle cx="{corner[0]:.1f}" cy="{corner[1]:.1f}" r="3.2" fill="{dirt_fill}"/>')
    mound = polar(60.5, 0)
    svg.append(f'<circle cx="{mound[0]:.1f}" cy="{mound[1]:.1f}" r="4.5" fill="{dirt_fill}" stroke="{dirt_line}" stroke-width="0.5"/>')

    # Home plate: white marker on top of the rounded dirt patch at home.
    svg.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="3.4" fill="#ffffff" stroke="#b7c9c6" stroke-width="0.6"/>')

    for pt in points:
        x, y = polar(min(pt['distance'], max_dist), max(-48, min(48, pt['direction'])))
        ev = pt.get('ev')
        ev_txt = f'{ev:.1f} mph' if ev is not None else '—'
        dist_txt = f'{pt["distance"]:.0f} ft' if pt.get('distance') is not None else '—'
        # Visible dot, plus a larger transparent circle on top purely to
        # give hover/tap a forgiving target without changing how big the
        # dot looks.
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{_ev_bucket_color(ev)}" fill-opacity="0.85" stroke="#fff" stroke-width="0.6"/>')
        svg.append(
            f'<circle class="bb-hit" cx="{x:.1f}" cy="{y:.1f}" r="8" fill="transparent" '
            f'style="cursor:pointer;" data-ev="{ev_txt}" data-dist="{dist_txt}" '
            f'data-la="{"" if pt.get("la") is None else format(pt["la"], ".0f") + "°"}" data-type="{pt.get("type") or ""}" data-xba="{pt.get("xba") or ""}"/>'
        )
    svg.append('</svg>')
    return ''.join(svg)


def spray_chart_interactive_html(points, width=380, height=340, svg_fn=None):
    """spray_chart_svg() wrapped with a hover/click tooltip -- no external
    JS libraries, just a small inline script scoped to this chart's own
    wrapper id (safe even if a page ever has more than one)."""
    import random
    uid = f'sc{random.randint(100000, 999999)}'
    svg_html = svg_fn(points) if svg_fn else spray_chart_svg(points, width=width, height=height)
    script = f'''
    <script>
    (function() {{
      var wrap = document.getElementById("{uid}");
      if (!wrap) return;
      var tip = wrap.querySelector(".bb-tooltip");
      var pinned = null;
      function place(evt, dot) {{
        var wr = wrap.getBoundingClientRect();
        var x = evt.clientX - wr.left, y = evt.clientY - wr.top;
        tip.style.left = x + "px";
        tip.style.top = Math.max(0, y - 12) + "px";
        var la = dot.getAttribute("data-la"), ty = dot.getAttribute("data-type"), xb = dot.getAttribute("data-xba");
        tip.innerHTML = "EV: <b>" + dot.getAttribute("data-ev") + "</b><br>Dist: <b>" + dot.getAttribute("data-dist") + "</b>" + (la ? "<br>LA: <b>" + la + "</b>" : "") + (ty ? " <b>" + ty + "</b>" : "") + (xb ? "<br>xBA: <b>" + xb + "</b>" : "");
        tip.style.display = "block";
      }}
      function hide() {{ if (!pinned) tip.style.display = "none"; }}
      Array.prototype.forEach.call(wrap.querySelectorAll(".bb-hit"), function(dot) {{
        dot.addEventListener("mouseenter", function(e) {{ if (!pinned) place(e, dot); }});
        dot.addEventListener("mousemove", function(e) {{ if (!pinned) place(e, dot); }});
        dot.addEventListener("mouseleave", hide);
        dot.addEventListener("click", function(e) {{
          e.stopPropagation();
          if (pinned === dot) {{ pinned = null; hide(); }} else {{ pinned = dot; place(e, dot); }}
        }});
      }});
      document.addEventListener("click", function() {{ pinned = null; hide(); }});
    }})();
    </script>'''
    return (
        f'<div id="{uid}" class="bb-spray-wrap" style="position:relative;display:inline-block;">'
        f'{svg_html}'
        f'<div class="bb-tooltip" style="display:none;position:absolute;transform:translate(-50%,-100%);'
        f'background:rgba(30,38,40,0.92);color:#fff;font:600 10.5px Arial,sans-serif;padding:5px 8px;'
        f'border-radius:5px;white-space:nowrap;pointer-events:none;z-index:5;line-height:1.4;"></div>'
        f'{script}</div>'
    )

def spray_chart_legend_html():
    items = [('<70 mph', '#f4f1e8'), ('70-79 mph', '#ffd23f'), ('80-89 mph', '#ff8c42'), ('90-99 mph', '#e63946'), ('100+ mph', '#7b2cbf')]
    dots = ''.join(
        f'<div style="display:flex;align-items:center;margin-right:16px;white-space:nowrap;">'
        f'<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:{c};margin-right:5px;flex:none;"></span>{label}</div>'
        for label, c in items
    )
    return (f'<div style="display:flex;flex-wrap:wrap;justify-content:center;'
            f'font:500 10px Arial,sans-serif;color:#555;margin-top:10px;">{dots}</div>')


# ---------------------------------------------------------------------------
# 4. PITCH LOCATION HEAT MAP (Trackman plate location)
# ---------------------------------------------------------------------------
_CALL_LABELS = {'StrikeCalled': 'Called strike', 'BallCalled': 'Ball', 'InPlay': 'In play',
                'StrikeSwinging': 'Swinging strike', 'FoulBall': 'Foul', 'FoulBallNotFieldable': 'Foul',
                'FoulBallFieldable': 'Foul', 'HitByPitch': 'Hit by pitch', 'BallinDirt': 'Ball in dirt'}

# strike zone as drawn (17" plate, generic 1.5-3.5 ft) and the "in zone" test
# that lets the ball's edge touch it (plate half-width .708 ft + ball radius .12)
_ZONE_X, _ZONE_BOT, _ZONE_TOP = 0.708, 1.5, 3.5
_IN_X, _IN_BOT, _IN_TOP = 0.83, 1.38, 3.62


def _in_zone(side, height):
    return abs(side) <= _IN_X and _IN_BOT <= height <= _IN_TOP


# ---------------------------------------------------------------- smooth contour maps (Savant-style filled density / value maps)
def smooth_field(pts, x0, x1, y0, y1, step, bw):
    """Gaussian-smoothed sums on a grid. pts: [(x, y, weight_or_None)]. Returns (xs, ys, dens, num): dens[j][i] = sum of kernel weights,
    num[j][i] = sum of kernel * value (value = the point's third element, or 1)."""
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    xs = [x0 + i * step for i in range(nx)]
    ys = [y0 + j * step for j in range(ny)]
    dens = [[0.0] * nx for _ in range(ny)]
    num = [[0.0] * nx for _ in range(ny)]
    r = int(3 * bw / step) + 1
    two = 2 * bw * bw
    for x, y, v in pts:
        ci, cj = round((x - x0) / step), round((y - y0) / step)
        if not (-r <= ci < nx + r and -r <= cj < ny + r):
            continue
        gx = {i: math.exp(-((xs[0] + i * step - x) ** 2) / two) for i in range(max(0, ci - r), min(nx, ci + r + 1))}
        for j in range(max(0, cj - r), min(ny, cj + r + 1)):
            gy = math.exp(-((ys[0] + j * step - y) ** 2) / two)
            if gy < 1e-4:
                continue
            row_d, row_n = dens[j], num[j]
            for i, g in gx.items():
                w = g * gy
                row_d[i] += w
                if v is not None:
                    row_n[i] += w * v
    return xs, ys, dens, num


def _contour_rings(F, xs, ys, L):
    """Marching squares: closed rings (lists of (x, y)) bounding the region where F >= L. The grid's border must be below L."""
    ny, nx = len(F), len(F[0])
    segs = {}

    def pt(e):
        k, i, j = e
        if k == 'h':
            a, b = F[j][i], F[j][i + 1]
            t = (L - a) / (b - a) if b != a else .5
            return (xs[i] + (xs[i + 1] - xs[i]) * t, ys[j])
        a, b = F[j][i], F[j + 1][i]
        t = (L - a) / (b - a) if b != a else .5
        return (xs[i], ys[j] + (ys[j + 1] - ys[j]) * t)
    cases = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 0), (1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)],
             9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(1, 2)], 12: [(1, 3)], 13: [(0, 1)], 14: [(3, 0)]}
    for j in range(ny - 1):
        for i in range(nx - 1):
            idx = (F[j][i] >= L) | ((F[j][i + 1] >= L) << 1) | ((F[j + 1][i + 1] >= L) << 2) | ((F[j + 1][i] >= L) << 3)
            if idx in cases:
                edges = (('h', i, j), ('v', i + 1, j), ('h', i, j + 1), ('v', i, j))
                for a, b in cases[idx]:
                    ea, eb = edges[a], edges[b]
                    segs.setdefault(ea, []).append(eb)
                    segs.setdefault(eb, []).append(ea)
    rings, seen = [], set()
    for start in list(segs):
        if start in seen:
            continue
        ring, cur, prev = [], start, None
        while cur not in seen:
            seen.add(cur)
            ring.append(pt(cur))
            nxt = [n for n in segs[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _chaikin(ring, rounds=2):
    for _ in range(rounds):
        out = []
        n = len(ring)
        for k in range(n):
            (x0_, y0_), (x1_, y1_) = ring[k], ring[(k + 1) % n]
            out.append((0.75 * x0_ + 0.25 * x1_, 0.75 * y0_ + 0.25 * y1_))
            out.append((0.25 * x0_ + 0.75 * x1_, 0.25 * y0_ + 0.75 * y1_))
        ring = out
    return ring


def contour_layers(F, xs, ys, levels, colors, X, Y, opacity=1.0):
    """Stacked filled contour regions (lowest level first). X / Y turn feet into pixels. Returns SVG <path> markup."""
    out = []
    for L, col in zip(levels, colors):
        d = []
        for ring in _contour_rings(F, xs, ys, L):
            ring = _chaikin(ring)
            d.append('M' + 'L'.join(f'{X(x):.1f},{Y(y):.1f}' for x, y in ring) + 'Z')
        if d:
            out.append(f'<path d="{"".join(d)}" fill="{col}" fill-opacity="{opacity}" fill-rule="evenodd" stroke="#fff" stroke-opacity=".35" stroke-width=".6"/>')
    return ''.join(out)


def _lerp_stops(stops, t):
    t = max(0.0, min(1.0, t))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            f = (t - a) / (b - a) if b > a else 0
            return 'rgb(' + ','.join(str(round(ca[i] + (cb[i] - ca[i]) * f)) for i in range(3)) + ')'
    return 'rgb(' + ','.join(str(v) for v in stops[-1][1]) + ')'


# blue -> pale -> red, like the Savant location maps
DENSITY_STOPS = [(0.0, (66, 110, 186)), (0.3, (140, 172, 222)), (0.5, (232, 236, 245)), (0.7, (240, 160, 158)), (1.0, (212, 36, 50))]
EV_STOPS = [(0.0, (36, 90, 158)), (0.5, (238, 232, 214)), (1.0, (185, 41, 42))]


def density_contours(pts, x0, x1, y0, y1, X, Y, bw=0.45, step=0.1, n_levels=11):
    """pts: [(x, y)]. Savant-style filled density contours (blue rim to red core) for one set of pitch locations."""
    if not pts:
        return ''
    xs, ys, dens, _ = smooth_field([(x, y, None) for x, y in pts], x0, x1, y0, y1, step, bw)
    mx = max(max(r) for r in dens)
    if mx <= 0:
        return ''
    F = [[v / mx for v in r] for r in dens]
    for j in range(len(F)):                       # close every contour inside the frame
        F[j][0] = F[j][-1] = 0.0
    F[0] = [0.0] * len(F[0])
    F[-1] = [0.0] * len(F[0])
    levels = [0.07 + k * (0.88 / n_levels) for k in range(n_levels)]
    colors = [_lerp_stops(DENSITY_STOPS, (L - 0.07) / 0.88 * 0.95 + 0.02) for L in levels]
    return contour_layers(F, xs, ys, levels, colors, X, Y)


def _heat_color(t):
    """t in 0..1 -> (rgb, opacity): transparent pale blue -> yellow -> red."""
    stops = [(0.0, (120, 170, 215)), (0.35, (250, 235, 150)), (0.7, (240, 150, 70)), (1.0, (205, 50, 50))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            f = (t - a) / (b - a)
            rgb = tuple(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
            break
    else:
        rgb = stops[-1][1]
    return rgb, min(0.85, 0.12 + 0.78 * t)


def _batter_outline_svg(cx_px, base_y_px, px_per_ft, mirror):
    """Batter silhouette standing in his box, feet on y=0 and ~5.85 ft tall
    including the bat. batter_art holds the right-handed figure (catcher's
    view); the left-handed batter is that same image reflected. Falls back to
    nothing if the art module is missing, so a chart can never crash on it."""
    try:
        import batter_art
    except ImportError:
        return ''
    h = 5.85 * px_per_ft
    w = h * batter_art.ASPECT
    img = (f'<image href="{batter_art.BATTER_RHB_PNG}" x="{cx_px - w / 2:.1f}" y="{base_y_px - h:.1f}" '
           f'width="{w:.1f}" height="{h:.1f}" preserveAspectRatio="xMidYMid meet"/>')
    if mirror:
        return f'<g transform="translate({2 * cx_px:.1f},0) scale(-1,1)">{img}</g>'
    return img


def _call_kind(call):
    c = (call or '').strip().lower()
    if c == 'strikeswinging':
        return 'swing'
    if c == 'inplay':
        return 'inplay'
    if c == 'strikecalled':
        return 'called'
    return 'other'


def _ink_on(hex_color):
    """Black or white, whichever reads on this fill colour."""
    n = int(hex_color.lstrip('#'), 16)
    lum = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255
    return '#1a1a1a' if lum > 0.62 else '#fff'


def _marker_legend(uid):
    g = '#5c7585'
    def icon(inner):
        return f'<svg width="16" height="16" viewBox="-8 -8 16 16" style="vertical-align:-3px;margin-right:4px">{inner}</svg>'
    items = [
        (icon(f'<circle r="5" fill="{g}"/>'), 'Ball / other'),
        (icon(f'<circle r="7" fill="{g}"/><text transform="translate(0,.3) scale(-1,1)" text-anchor="middle" dominant-baseline="central" font-family="Arial" font-size="11" font-weight="800" fill="#fff">K</text>'), 'Called strike'),
        (icon(f'<rect x="-6" y="-6" width="12" height="12" fill="{g}"/>'), 'Swing &amp; miss'),
        (icon(f'<circle r="7" fill="{g}"/><path d="M-3.2 -3.2L3.2 3.2M3.2 -3.2L-3.2 3.2" stroke="#fff" stroke-width="1.9" stroke-linecap="round"/>'), 'Ball in play'),
    ]
    return (f'<div style="display:flex;gap:16px;flex-wrap:wrap;justify-content:center;margin:2px 0 8px;font:600 11.5px/1 var(--f-heading);color:#26343b;">'
            + ''.join(f'<span>{i}{t}</span>' for i, t in items) + '</div>')


def location_heatmap_html(pitches, width=340, uid='loc'):
    """Outing-style location view: TWO catcher's-view charts side by side --
    vs left-handed batters (left) and vs right-handed batters (right), each a
    smoothed density heat map with every pitch as a hoverable dot (class
    mv-pt) and a batter outline standing in his box. One row of buttons
    switches both charts between All and each pitch type.
    pitches: [{'type','color','loc':[{'side','height','velo','call','count','bats'}]}]"""
    pitches = [p for p in pitches if p.get('loc')]
    if not pitches:
        return ''
    x0, x1, y0, y1 = -2.75, 2.75, -0.45, 5.9
    k = width / (x1 - x0)                      # px per ft
    height = round((y1 - y0) * k)
    X = lambda v: (v - x0) * k
    Y = lambda v: (y1 - v) * k

    def heat(pts):
        return density_contours([(l['side'], l['height']) for l in pts], x0, x1, y0, y1, X, Y)

    view_names = ['All'] + [p['type'] for p in pitches]

    def one_chart(side_code, title, uid2):
        # catcher's view: a righty stands left of the plate, a lefty right
        mirror = side_code == 'L'
        locs = [(p, l) for p in pitches for l in p['loc'] if l.get('bats') == side_code]
        svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
               f'font-family="ProximaNova,Helvetica Neue,Arial,sans-serif" style="display:block;width:100%;height:auto;">',
               f'<defs><clipPath id="{uid2}-clip"><rect width="{width}" height="{height}"/></clipPath></defs>',
               f'<rect width="{width}" height="{height}" fill="#fff"/>']
        for i, name in enumerate(view_names):
            pts = [l for p, l in locs if name == 'All' or p['type'] == name]
            svg.append(f'<g class="{uid}-heat" data-view="{name}" clip-path="url(#{uid2}-clip)" opacity=".7" style="display:{"block" if i == 0 else "none"}">'
                       f'{heat(pts) if pts else ""}</g>')
        svg.append(_batter_outline_svg(X(1.68 if mirror else -1.68), Y(0.0), k, mirror))      # in front of the heat map
        zl, zr, zt, zb = X(-_ZONE_X), X(_ZONE_X), Y(_ZONE_TOP), Y(_ZONE_BOT)
        for m in (1, 2):                                   # subtle 3 x 3 inside the zone
            svg.append(f'<line x1="{zl + (zr - zl) * m / 3:.1f}" y1="{zt:.1f}" x2="{zl + (zr - zl) * m / 3:.1f}" y2="{zb:.1f}" stroke="#22303a" stroke-opacity=".3" stroke-width="1"/>')
            svg.append(f'<line x1="{zl:.1f}" y1="{zt + (zb - zt) * m / 3:.1f}" x2="{zr:.1f}" y2="{zt + (zb - zt) * m / 3:.1f}" stroke="#22303a" stroke-opacity=".3" stroke-width="1"/>')
        svg.append(f'<rect x="{zl:.1f}" y="{zt:.1f}" width="{zr - zl:.1f}" height="{zb - zt:.1f}" fill="none" stroke="#22303a" stroke-width="1.6"/>')
        py0, py1, cx, pw = Y(0.0), Y(-0.38), X(0), X(_ZONE_X) - X(0)
        svg.append(f'<polygon points="{cx - pw:.1f},{py0:.1f} {cx + pw:.1f},{py0:.1f} {cx + pw:.1f},{(py0 + py1) / 2:.1f} {cx:.1f},{py1:.1f} {cx - pw:.1f},{(py0 + py1) / 2:.1f}" fill="#fff" stroke="#5c7585" stroke-width="1.8"/>')
        for p, l in locs:
            call = _CALL_LABELS.get(l['call'], l['call'] or 'No result')
            tip = (f'{p["type"]} \u00b7 {call} \u00b7 {l["count"]} \u00b7 side {l["side"]:+.2f} ft, height {l["height"]:.2f} ft'
                   + (f' \u00b7 {l["velo"]:.1f} mph' if l.get('velo') else ''))
            cx_, cy_, col = X(l["side"]), Y(l["height"]), p["color"]
            ink = _ink_on(col)
            kind = _call_kind(l['call'])
            attrs = (f'class="mv-pt {uid}-dot" data-type="{p["type"]}" data-tip="{tip}" data-ptype="{p["type"]}" data-pcolor="{col}"'
                     + (f' data-pvelo="{l["velo"]:.1f}"' if l.get('velo') else '')
                     + f' data-pn="{l.get("n", "")}" data-psub="{call} \u00b7 {l["count"]}" fill="{col}" fill-opacity="0.9" stroke="#fff" stroke-width="1.2"')
            if kind == 'swing':       # swing & miss: square
                svg.append(f'<rect {attrs} x="{cx_ - 6:.1f}" y="{cy_ - 6:.1f}" width="12" height="12"/>')
            elif kind == 'inplay':    # ball in play: dot with an X
                svg.append(f'<g {attrs.replace(" fill=", " data-f=")}><circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="7" fill="{col}" fill-opacity="0.9" stroke="#fff" stroke-width="1.2"/>'
                           f'<path d="M{cx_ - 3.2:.1f} {cy_ - 3.2:.1f}L{cx_ + 3.2:.1f} {cy_ + 3.2:.1f}M{cx_ + 3.2:.1f} {cy_ - 3.2:.1f}L{cx_ - 3.2:.1f} {cy_ + 3.2:.1f}" '
                           f'stroke="{ink}" stroke-width="1.9" stroke-linecap="round" fill="none"/></g>')
            elif kind == 'called':    # called strike: backwards K
                svg.append(f'<g {attrs.replace(" fill=", " data-f=")}><circle cx="{cx_:.1f}" cy="{cy_:.1f}" r="7.5" fill="{col}" fill-opacity="0.9" stroke="#fff" stroke-width="1.2"/>'
                           f'<text transform="translate({cx_:.1f},{cy_ + 0.3:.1f}) scale(-1,1)" text-anchor="middle" dominant-baseline="central" '
                           f'font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="800" fill="{ink}" stroke="none">K</text></g>')
            else:
                svg.append(f'<circle {attrs} cx="{cx_:.1f}" cy="{cy_:.1f}" r="5.5"/>')
        svg.append('</svg>')

        def stat(name):
            pts = [l for p, l in locs if name == 'All' or p['type'] == name]
            n = len(pts)
            if not n:
                return 'No pitches'
            z = sum(1 for l in pts if _in_zone(l['side'], l['height']))
            return f'{n} pitches &middot; {z} in zone ({z / n * 100:.1f}%)'
        stats = ''.join(f'<div class="{uid}-stat" data-view="{name}" style="display:{"block" if i == 0 else "none"}">{stat(name)}</div>'
                        for i, name in enumerate(view_names))
        return (f'<div class="{uid}-col"><div class="{uid}-title">{title}</div>' + ''.join(svg) +
                f'<div class="{uid}-stats">{stats}</div></div>')

    btns = ''.join(f'<button type="button" class="{uid}-btn{" on" if i == 0 else ""}" data-view="{name}"'
                   + (f' style="--c:{pitches[i - 1]["color"]}"' if i else '') + f'>{name}</button>'
                   for i, name in enumerate(view_names))
    css = (f'<style>.{uid}-btns{{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin:2px 0 8px;}}'
           f'.{uid}-btn{{font:600 12px/1 var(--f-heading);border:1.5px solid var(--c,#5c7585);background:#fff;color:#26343b;border-radius:999px;padding:6px 12px;cursor:pointer;}}'
           f'.{uid}-btn.on{{background:var(--c,#5c7585);color:#fff;}}'
           f'.{uid}-row{{display:flex;gap:10px;}} .{uid}-col{{flex:1 1 0;min-width:0;}}'
           f'.{uid}-title{{font:700 13px/1 var(--f-heading);text-align:center;color:#26343b;margin:0 0 6px;letter-spacing:.02em;}}'
           f'.{uid}-stats{{font:500 11.5px/1.3 var(--f-heading);color:var(--muted);text-align:center;margin-top:6px;}}</style>')
    js = (f'<script>(function(){{var uid="{uid}",view="All",mode="heat";'
          f'var vb=document.querySelectorAll("."+uid+"-btn:not(."+uid+"-mbtn)"),mb=document.querySelectorAll("."+uid+"-mbtn");'
          f'function render(){{vb.forEach(function(b){{b.classList.toggle("on",b.dataset.view===view)}});'
          f'mb.forEach(function(b){{b.classList.toggle("on",b.dataset.mode===mode)}});'
          f'document.querySelectorAll("."+uid+"-heat").forEach(function(g){{g.style.display=(g.dataset.view===view&&mode!=="dots")?"block":"none"}});'
          f'document.querySelectorAll("."+uid+"-stat").forEach(function(g){{g.style.display=g.dataset.view===view?"block":"none"}});'
          f'document.querySelectorAll("."+uid+"-dot").forEach(function(d){{d.style.display=((view==="All"||d.dataset.type===view)&&mode!=="heat")?"":"none"}});}}'
          f'vb.forEach(function(b){{b.addEventListener("click",function(){{view=b.dataset.view;render()}})}});'
          f'mb.forEach(function(b){{b.addEventListener("click",function(){{mode=b.dataset.mode;render()}})}});render();}})();</script>')
    modes = ''.join(f'<button type="button" class="{uid}-btn {uid}-mbtn{" on" if m == "heat" else ""}" data-mode="{m}">{lbl}</button>'
                    for m, lbl in (('dots', 'Dots Only'), ('heat', 'Heat Map'), ('both', 'Both')))
    return (css + f'<div class="{uid}-btns">{modes}</div><div class="{uid}-btns">{btns}</div>' + _marker_legend(uid) + f'<div class="{uid}-row">'
            + one_chart('R', 'vs Right Handed Batter', uid + 'R')
            + one_chart('L', 'vs Left Handed Batter', uid + 'L')
            + '</div>' + js)


# ---------------------------------------------------------------- MLB arsenal comps / pitch ideas
def _hb_txt(v):
    return f'{abs(v):.1f}\u2033 {"arm" if v >= 0 else "glove"}-side'


def _mlb_head(pid, w=64):
    return (f'https://img.mlbstatic.com/mlb-photos/image/upload/w_{w * 2},d_people:generic:headshot:silo:current.png,'
            f'q_auto:best,f_auto/v1/people/{pid}/headshot/67/current')


def _hb_short(v):
    """'17.7\u2033 A' (arm-side) or '1.4\u2033 G' (glove-side)."""
    return f'{abs(v):.1f}\u2033 {"A" if v >= 0 else "G"}'


def arsenal_comps_html(comps, ours, throws, colors):
    """comps: arsenal_comps.find_arsenal_comps(); ours: [{'type','velo','ivb','hb'(Trackman sign),...}]."""
    if not comps:
        return ''
    sgn = 1 if (throws or 'R').upper().startswith('R') else -1
    mine = {o['type']: o for o in ours}
    cards = []
    for c in comps:
        rows = ''
        for m in c['matches']:
            o, t = mine.get(m['ours']), m['mlb']
            col = colors.get(m['ours'], '#555')
            if not o:
                continue
            same = m['theirs'] == m['ours']
            rows += (f'<tr class="ac-me"><td class="ac-pt"><i style="background:{col}"></i>{m["ours"]}</td>'
                     f'<td>{o["velo"]:.1f}</td><td>{o["ivb"]:.1f}\u2033</td><td>{_hb_short(sgn * o["hb"])}</td></tr>'
                     f'<tr class="ac-them"><td class="ac-pt">\u21b3 {c["name"].split()[-1] if same else m["theirs"]}</td>'
                     f'<td>{(t["velo"] or 0):.1f}</td><td>{t["ivb"]:.1f}\u2033</td><td>{_hb_short(t["hb"])}</td></tr>')
        vc = c.get('velo_ctx')
        if vc:
            d = vc['diff']
            vline = ('Similar fastball velocity' if abs(d) < 2.5 else
                     f'Fastball {abs(d):.0f} mph {"faster" if d > 0 else "slower"} than yours')
            vline = f'<div class="ac-vc">{vline} ({vc["theirs"]:.1f} vs {vc["ours"]:.1f})</div>'
        else:
            vline = ''
        ang = f'<div class="ac-sub">{c["arm_angle"]:.0f}\u00b0 arm angle</div>' if c.get('arm_angle') is not None else ''
        cards.append(
            f'<a class="ac-card" href="https://baseballsavant.mlb.com/savant-player/{c["id"]}" target="_blank" rel="noopener">'
            f'<div class="ac-head"><img src="{_mlb_head(c["id"])}" alt="" onerror="this.style.visibility=\'hidden\'">'
            f'<div><div class="ac-name">{c["name"]}</div><div class="ac-sub"><b>{c.get("quality", "Match")}</b> &middot; {c["match"]}</div>{ang}</div></div>{vline}'
            f'<table class="ac-tbl"><colgroup><col style="width:37%"><col style="width:20%"><col style="width:20%"><col style="width:23%"></colgroup>'
            f'<tr><th style="text-align:left;">Pitch</th><th>Velo</th><th>IVB</th><th>HB</th></tr>{rows}</table></a>')
    css = ('<style>.ac-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;} '
           '.ac-card{border:1px solid #d3dee6;border-radius:12px;padding:14px;text-decoration:none;color:#26343b;background:#fff;min-width:0;}'
           '.ac-card:hover{border-color:var(--accent-teal);}'
           '.ac-head{display:flex;gap:12px;align-items:center;margin-bottom:8px;} .ac-head img{width:56px;height:56px;border-radius:50%;object-fit:cover;background:#e8eef2;flex:none;}'
           '.ac-name{font:700 16px/1.15 var(--f-heading);} .ac-sub{font:500 12px/1.3 var(--f-heading);color:var(--muted);margin-top:2px;} .ac-sub b{color:#26343b;}'
           '.ac-vc{font:600 12px/1.3 var(--f-heading);color:var(--accent-teal);margin:0 0 8px;padding:6px 9px;background:#f1f6f8;border-radius:6px;}'
           '.ac-tbl{width:100%;table-layout:fixed;border-collapse:collapse;font:600 13px/1.3 var(--f-heading);} .ac-tbl th{font:700 10.5px var(--f-heading);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);text-align:center;padding:2px 0 5px;}'
           '.ac-tbl td{text-align:center;padding:4px 2px;white-space:nowrap;} .ac-tbl td.ac-pt{text-align:left;overflow:hidden;text-overflow:ellipsis;}'
           '.ac-me td{border-top:1px solid #e3e8ea;font-weight:700;} .ac-me td.ac-pt i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:0;}'
           '.ac-them td{color:#5c7585;font-weight:500;font-size:12px;padding-top:0;padding-bottom:6px;}'
           '.ac-note{font:400 12px/1.5 var(--f-heading);color:var(--muted);margin-top:12px;}</style>')
    return (css + '<div class="ac-row">' + ''.join(cards) + '</div>'
            '<div class="ac-note">Matched on pitch shape: induced vertical break and horizontal break, with spin counting less, against 2026 MLB pitch-arsenal data and weighted by how often each pitch is thrown. '
            'Velocity is not part of the match, so a comp can throw harder and still be the right model for the movement. '
            'HB: A = arm-side, G = glove-side, so lefties and righties compare directly.'
            + ('<br><b>Heads up:</b> none of these are a close match, so read them as the nearest shape family, not a true comp.' if comps and comps[0].get('match', 100) < 40 else '') + '</div>')


def _savant_video_url(pid, code, year=2026):
    """Baseball Savant Statcast Search filtered to one pitcher's pitches of one type (individual pitches there have video)."""
    return ('https://baseballsavant.mlb.com/statcast_search?hfPT=' + code.upper() + '%7C&hfSea=' + str(year) +
            '%7C&player_type=pitcher&pitchers_lookup%5B%5D=' + str(pid) + '&type=details&sort_col=pitch_number_thisgame&sort_order=desc')


_VIDEO_CACHE = None


def _pitch_videos():
    """data/pitch_videos.json: {"<savant pitcher id>|<pitch code>": [clip, ...]}, best-matching clips pulled from Baseball Savant."""
    global _VIDEO_CACHE
    if _VIDEO_CACHE is None:
        import json, os
        try:
            with open(os.path.join(os.path.dirname(__file__), 'data', 'pitch_videos.json'), encoding='utf-8') as f:
                _VIDEO_CACHE = json.load(f)
        except (OSError, ValueError):
            _VIDEO_CACHE = {}
    return _VIDEO_CACHE


def _clip_line(c):
    last = c['pitcher'].split()[-1] if c.get('pitcher') else ''
    swing = 'swinging' in (c.get('call') or '')
    if c.get('event') == 'strikeout':
        what = f'{last} strikes out {c["batter"]} ' + ('swinging' if swing else 'looking')
    else:
        what = f'{last} gets a {"swing and miss" if swing else "called strike"} from {c["batter"]}'
    mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    y, m, d = c['date'].split('-')
    sub = (f'{c["velo"]:.1f} mph &middot; {abs(c["hb"]):.0f}\u2033 {"glove" if c["hb"] < 0 else "arm"}-side &middot; '
           f'{c["ivb"]:.0f}\u2033 IVB &middot; {mo[int(m) - 1]} {int(d)}')
    return (f'<a class="ai-clip" href="https://baseballsavant.mlb.com/sporty-videos?playId={c["playId"]}" target="_blank" rel="noopener">'
            f'<span class="ai-play">&#9654;</span><span><b>{what}</b><br><span class="ai-cs">{sub}</span></span></a>')


def arsenal_ideas_html(ideas, colors, fb_velo=None, throws='R'):
    if not ideas:
        return ''
    cards = []
    for s in ideas:
        t = s['target']
        col = colors.get(s['type'], '#5c7585')
        bits = [f'~{t["velo"]:.0f} mph ({t["velo_gap"]:.0f} off the fastball)' if t.get('velo') else f'{t["velo_gap"]:.0f} mph off the fastball',
                f'{t["ivb"]:.0f}\u2033 IVB', _hb_txt(t['hb']), f'~{t["spin"]:,.0f} rpm']
        vids = _pitch_videos()
        clips = []
        for e in s['examples']:
            cl = vids.get(f'{e["id"]}|{s["code"]}') or []
            if cl:
                clips.append(_clip_line(cl[0]))
        if len(clips) < 3:                                   # second clip from the best-matching pitcher if fewer than 3 pitchers have video
            for e in s['examples']:
                cl = vids.get(f'{e["id"]}|{s["code"]}') or []
                if len(cl) > 1 and len(clips) < 3:
                    clips.append(_clip_line(cl[1]))
        if clips:
            ex = '<div class="ai-clips">' + ''.join(clips) + '</div>'
        else:
            ex = ', '.join(f'<a href="/clip/{e["id"]}/{s["code"]}/{e.get("year") or 2026}" target="_blank" rel="noopener">{e["name"]} &#9654;</a>' for e in s['examples'] if e.get('id'))
        why = (f'{s["n_users"]} of the {s["n_neighbours"]} MLB pitchers with the most similar fastball and arm slot throw it. '
               f'It would move about {s["contrast"]:.0f}\u2033 differently from your closest current pitch.')
        try:
            import arsenal_comps as _ac
            wl = ''.join(f'<li>{x}</li>' for x in _ac.why_it_helps(s, throws)) if s.get('ctx') else ''
        except ImportError:
            wl = ''
        whyblock = f'<div class="ai-wh"><div class="ai-t" style="margin-top:0;">Why it helps</div><ul>{wl}</ul></div>' if wl else ''
        cards.append(
            f'<div class="ai-card"><div class="ai-h" style="background:{col};color:{_ink_on(col)};">{s["type"]}</div>'
            f'<div class="ai-b"><div class="ai-why">{s["blurb"].capitalize()}.</div>'
            f'<div class="ai-t">Target shape</div><div class="ai-v">{" &middot; ".join(bits)}</div>'
            f'<div class="ai-why" style="margin-top:6px;">{why}</div>'
            f'{whyblock}'
            f'<div class="ai-ex"><b>Watch it:</b> {ex}</div></div></div>')
    css = ('<style>.ai-row{display:flex;gap:10px;flex-wrap:wrap;} .ai-card{flex:1 1 200px;min-width:200px;border:1px solid #d3dee6;border-radius:8px;overflow:hidden;background:#fff;}'
           '.ai-h{font:700 15px/1 var(--f-heading);text-align:center;padding:9px 6px;} .ai-b{padding:9px 11px 11px;font:500 11.5px/1.4 var(--f-heading);color:#26343b;}'
           '.ai-t{font:700 10px/1 var(--f-heading);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-top:8px;} .ai-v{font:700 12px/1.45 var(--f-heading);margin-top:3px;}'
           '.ai-why{color:#4a5d68;} .ai-ex{margin-top:6px;color:#4a5d68;line-height:1.7;} .ai-ex a{color:var(--accent-teal);font-weight:700;text-decoration:none;white-space:nowrap;} .ai-ex a:hover{text-decoration:underline;}'
           '.ai-wh{margin-top:8px;background:#f1f6f8;border-left:3px solid var(--accent-teal);border-radius:0 6px 6px 0;padding:7px 9px;} .ai-wh ul{margin:4px 0 0;padding-left:15px;} .ai-wh li{margin:0 0 3px;color:#26343b;line-height:1.35;}'
           '.ai-clips{margin-top:4px;} .ai-ex a.ai-clip{display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-top:1px solid #e6eef2;white-space:normal;color:#26343b!important;font-weight:500!important;line-height:1.3;} .ai-clip:first-child{border-top:0;} .ai-clip b{font-weight:700;color:var(--accent-teal);} .ai-clip>span:last-child{min-width:0;} .ai-play{flex:0 0 18px;height:18px;border-radius:50%;background:var(--accent-teal);color:#fff;font-size:8px;line-height:18px;text-align:center;margin-top:1px;} .ai-cs{font-size:10px;color:var(--muted);}</style>')
    return (css + '<div class="ai-row">' + ''.join(cards) + '</div>'
            '<div style="font:400 10.5px/1.4 var(--f-heading);color:var(--muted);margin-top:8px;">Ranked by how common the pitch is among MLB pitchers with a similar fastball shape and arm slot, '
            'how differently it would move from the current arsenal, how well his spin suits it, and whether the arsenal is missing a breaking ball or offspeed pitch. Target shapes are the MLB averages for that group; the speed gap off the fastball is scaled to his own fastball, and the clips show the shape to copy, not the velocity. '
            'Video clips are real 2026 MLB pitches of this type from Baseball Savant, picked for the closest shape to the target and a swing-and-miss or strikeout result; each opens the clip on Savant.</div>')


# ---------------------------------------------------------------- arm-angle badge (Savant style)
# Bar geometry, in the supplied master-bar art's pixels with the SHOULDER end of the bar at the
# origin and the bar running along +x to the ring: length to ring centre, half-width at the shoulder
# end and where it meets the ring, ring radii.
_BAR_L, _BAR_HW0, _BAR_HW1, _BAR_R_OUT, _BAR_R_IN = 835.35, 75.0, 33.6, 70.0, 31.7


def _bar_svg(px, py, k, angle):
    r = 18.0                                              # corner rounding: inset polygon + round-join stroke
    pts = f'{r},{-(_BAR_HW0 - r)} {_BAR_L},{-(_BAR_HW1 - r)} {_BAR_L},{_BAR_HW1 - r} {r},{_BAR_HW0 - r}'
    return (f'<g transform="translate({px:.1f},{py:.1f}) rotate({-angle:.2f}) scale({k})">'
            f'<polygon points="{pts}" fill="#050505" stroke="#050505" stroke-width="{2 * r}" stroke-linejoin="round"/>'
            f'<circle cx="{_BAR_L}" cy="0" r="{_BAR_R_OUT}" fill="#050505"/>'
            f'<circle cx="{_BAR_L}" cy="0" r="{_BAR_R_IN}" fill="#e8f1f4"/></g>')


def arm_angle_badge(angle, throws='R'):
    """-> (svg_inner, w, h): the arm-angle graphic in its own canvas units. Static body art (one of two
    poses: 0-40 degrees and 40.5-90 degrees), a live bar rotated to `angle`, and live label/number.
    A lefty gets the figure and bar mirrored and the label on the other side, text unmirrored."""
    try:
        import arm_art
    except ImportError:
        return '', 0, 0
    a = max(-80.0, min(90.0, float(angle)))
    b = arm_art.BODIES['A' if a <= 40 else 'B']
    H = b['h']
    # one common canvas width for both poses (wide enough for a horizontal bar and its ring), so the
    # figure doesn't shift when the pose changes
    W = max(max(d['w'], d['pivot'][0] + d['k'] * (_BAR_L + _BAR_R_OUT) + 6) for d in arm_art.BODIES.values())
    px, py = b['pivot']
    lefty = (throws or 'R').upper().startswith('L')
    # reference fan: a sector from the horizontal (0 deg) up to the arm angle, drawn live so it always
    # reaches the bar, plus the horizontal reference line, both anchored at the shoulder apex
    ax_, ay_ = b['apex']
    R_ = b['wedge_r']
    ar = math.radians(a)
    ex_, ey_ = ax_ + R_ * math.cos(ar), ay_ - R_ * math.sin(ar)
    fan = (f'<path d="M{ax_:.1f},{ay_:.1f} L{ax_ + R_:.1f},{ay_:.1f} A{R_},{R_} 0 0 {0 if a >= 0 else 1} {ex_:.1f},{ey_:.1f} Z" fill="#d3dedd"/>'
           f'<line x1="{ax_:.1f}" y1="{ay_:.1f}" x2="{ax_ + b["line_len"]:.1f}" y2="{ay_:.1f}" stroke="#859ba7" stroke-width="6"/>')
    fig = (fan + f'<image href="{b["uri"]}" x="0" y="0" width="{b["w"]}" height="{H}"/>' + _bar_svg(px, py, b['k'], a))
    if lefty:
        fig = f'<g transform="translate({W},0) scale(-1,1)">{fig}</g>'
    ax0, ax1, ay0, ay1 = b['arm']
    gx0, gx1, gy0, gy1 = b['angle']
    nx0, nx1, ny0, ny1 = b['num']
    # label block: lefty -> mirrored to the right-hand side, left-aligned; lefty text starts at the mirrored block edge
    left = (W - gx1) if lefty else gx0
    teal = '#6b98a8'
    fs_a = (ay1 - ay0) / 0.70
    lab = (f'<text x="{left:.1f}" y="{ay1}" font-family="NeuePlakCond,Oswald,sans-serif" font-weight="400" font-size="{fs_a:.0f}" fill="{teal}" '
           f'textLength="{ax1 - ax0}" lengthAdjust="spacingAndGlyphs">ARM</text>'
           f'<text x="{left:.1f}" y="{gy1}" font-family="NeuePlakCond,Oswald,sans-serif" font-weight="400" font-size="{fs_a:.0f}" fill="{teal}" '
           f'textLength="{gx1 - gx0}" lengthAdjust="spacingAndGlyphs">ANGLE</text>')
    # number: heavy digits, one per slot, then a drawn degree ring
    cap = ny1 - ny0
    adv = 0.62 * cap
    txt = f'{round(a):d}'
    n = len(txt)
    ring_r = cap * 0.17
    total = n * adv + ring_r * 2 + 0.06 * cap
    cx_num = (left + (nx0 + nx1) / 2 - gx0) if lefty else (nx0 + nx1) / 2
    if lefty:
        cx_num = left + ((nx0 + nx1) / 2 - gx0)
    start = cx_num - total / 2
    xs = ' '.join(f'{start + adv * (i + 0.5):.1f}' for i in range(n))
    num = (f'<text x="{xs}" y="{ny1}" text-anchor="middle" font-family="AspiraXXXNar,Oswald,Arial Narrow,sans-serif" font-weight="900" '
           f'font-size="{cap / 0.72:.0f}" fill="#050505">{" ".join(txt)}</text>'.replace(' </text>', '</text>'))
    # (digits are spaced by the x list, so join with no real spaces)
    num = (f'<text x="{xs}" y="{ny1}" text-anchor="middle" font-family="AspiraXXXNar,Oswald,Arial Narrow,sans-serif" font-weight="900" '
           f'font-size="{cap / 0.72:.0f}" fill="#050505">' + ''.join(f'<tspan>{ch}</tspan>' for ch in txt) + '</text>')
    ring = (f'<circle cx="{start + n * adv + 0.06 * cap + ring_r:.1f}" cy="{ny0 + ring_r + cap * 0.04:.1f}" r="{ring_r * 0.78:.1f}" '
            f'fill="none" stroke="#050505" stroke-width="{cap * 0.075:.1f}"/>')
    return fig + lab + num + ring, W, H


def _arm_badge_svg(arm_badge, width, height, frac=0.205, pad=(6, 2)):
    if not arm_badge or arm_badge.get('angle') is None:
        return ''
    inner, W, H = arm_angle_badge(arm_badge['angle'], arm_badge.get('throws', 'R'))
    if not inner:
        return ''
    bw = width * frac
    bh = bw * H / W
    lefty = (arm_badge.get('throws') or 'R').upper().startswith('L')
    x = pad[0] if lefty else width - bw - pad[0]
    y = height - bh - pad[1]
    return f'<g transform="translate({x:.1f},{y:.1f}) scale({bw / W:.5f})">{inner}</g>'
