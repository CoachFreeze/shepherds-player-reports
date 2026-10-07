"""
Original recreations of three Baseball Savant-style visual components,
built from scratch (not copied source) to match their visual language:

  1. percentile_bars_html()   -- the diverging blue->red percentile rank bars
  2. movement_plot_svg()      -- horizontal/vertical break scatter
  3. spin_clock_row_svg()     -- per-pitch "spin direction" clock faces

Each returns a standalone HTML/SVG fragment you can drop into any page.
"""
import math

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
                      r24_frac=None, font_scale=1.0, pt_r=7):
    """
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

    svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
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
                svg.append(
                    f'<circle class="mv-pt" cx="{x:.1f}" cy="{y:.1f}" r="{pt_r}" fill="{color}" fill-opacity="0.7" '
                    f'stroke="{color}" stroke-width="1" data-tip="{tip}" data-ptype="{p["type"]}" data-pcolor="{color}" '
                    f'data-pvelo="{velo:.1f}" data-pivb="{vb:.1f}" data-phb="{hb:.1f}"/>' if velo else
                    f'<circle class="mv-pt" cx="{x:.1f}" cy="{y:.1f}" r="{pt_r}" fill="{color}" fill-opacity="0.7" '
                    f'stroke="{color}" stroke-width="1" data-tip="{tip}" data-ptype="{p["type"]}" data-pcolor="{color}" '
                    f'data-pivb="{vb:.1f}" data-phb="{hb:.1f}"/>')
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
        cells_header.append(f'<div class="ml-cell ml-name">{p["type"]}</div>')
        cells_pill.append(f'<div class="ml-cell"><span class="ml-pill" style="width:{pill_w}px;background:{color};"></span></div>')
        cells_usage.append(f'<div class="ml-cell">{pct:.0f}%</div>')
        cells_mph.append(f'<div class="ml-cell">{p["velo"]:.1f}</div>' if p.get('velo') is not None else '<div class="ml-cell">&mdash;</div>')
        cells_top.append(f'<div class="ml-cell">{p["top_velo"]:.1f}</div>' if p.get('top_velo') is not None else '<div class="ml-cell">&mdash;</div>')
    return (
        '<div class="movement-legend">'
        f'<div class="ml-row ml-header"><div class="ml-label"></div>{"".join(cells_header)}</div>'
        f'<div class="ml-row ml-pills"><div class="ml-label"></div>{"".join(cells_pill)}</div>'
        f'<div class="ml-row"><div class="ml-label">USAGE</div>{"".join(cells_usage)}</div>'
        f'<div class="ml-row"><div class="ml-label">MPH</div>{"".join(cells_mph)}</div>'
        f'<div class="ml-row"><div class="ml-label ml-italic">TOP MPH</div>{"".join(cells_top)}</div>'
        '</div>'
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
    if ev < 70: return '#3388d6'
    if ev < 80: return '#e0723c'
    if ev < 90: return '#7a56c9'
    if ev < 100: return '#e0b23c'
    return '#c94f8d'

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
            f'style="cursor:pointer;" data-ev="{ev_txt}" data-dist="{dist_txt}"/>'
        )
    svg.append('</svg>')
    return ''.join(svg)


def spray_chart_interactive_html(points, width=380, height=340):
    """spray_chart_svg() wrapped with a hover/click tooltip -- no external
    JS libraries, just a small inline script scoped to this chart's own
    wrapper id (safe even if a page ever has more than one)."""
    import random
    uid = f'sc{random.randint(100000, 999999)}'
    svg_html = spray_chart_svg(points, width=width, height=height)
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
        tip.innerHTML = "EV: <b>" + dot.getAttribute("data-ev") + "</b><br>Dist: <b>" + dot.getAttribute("data-dist") + "</b>";
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
    items = [('<70 mph', '#3388d6'), ('70-79 mph', '#e0723c'), ('80-89 mph', '#7a56c9'), ('90-99 mph', '#e0b23c'), ('100+ mph', '#c94f8d')]
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

    def heat(pts, bw=0.45, step=0.14):
        gx = [x0 + i * step for i in range(int((x1 - x0) / step))]
        gy = [y0 + j * step for j in range(int((y1 - y0) / step))]
        cells, mx = [], 0.0
        for xx in gx:
            for yy in gy:
                d = sum(math.exp(-(((xx + step / 2 - l['side']) ** 2 + (yy + step / 2 - l['height']) ** 2) / (2 * bw * bw)))
                        for l in pts)
                cells.append((xx, yy, d))
                mx = max(mx, d)
        out = []
        for xx, yy, d in cells:
            t = d / mx if mx else 0
            if t < 0.07:
                continue
            (r, g, b), op = _heat_color(t)
            out.append(f'<rect x="{X(xx):.1f}" y="{Y(yy + step):.1f}" width="{step * k + 1.4:.1f}" height="{step * k + 1.4:.1f}" '
                       f'fill="rgb({r},{g},{b})" fill-opacity="{op:.2f}"/>')
        return ''.join(out)

    view_names = ['All'] + [p['type'] for p in pitches]

    def one_chart(side_code, title, uid2):
        # catcher's view: a righty stands left of the plate, a lefty right
        mirror = side_code == 'L'
        locs = [(p, l) for p in pitches for l in p['loc'] if l.get('bats') == side_code]
        svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
               f'font-family="ProximaNova,Helvetica Neue,Arial,sans-serif" style="display:block;width:100%;height:auto;">',
               f'<defs><filter id="{uid2}-blur" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="3.5"/></filter>'
               f'<clipPath id="{uid2}-clip"><rect width="{width}" height="{height}"/></clipPath></defs>',
               f'<rect width="{width}" height="{height}" fill="#f4f8fa"/>']
        svg.append(_batter_outline_svg(X(1.68 if mirror else -1.68), Y(0.0), k, mirror))
        for i, name in enumerate(view_names):
            pts = [l for p, l in locs if name == 'All' or p['type'] == name]
            svg.append(f'<g class="{uid}-heat" data-view="{name}" clip-path="url(#{uid2}-clip)" style="display:{"block" if i == 0 else "none"}">'
                       f'<g filter="url(#{uid2}-blur)">{heat(pts) if pts else ""}</g></g>')
        zl, zr, zt, zb = X(-_ZONE_X), X(_ZONE_X), Y(_ZONE_TOP), Y(_ZONE_BOT)
        for m in (1, 2):
            svg.append(f'<line x1="{zl + (zr - zl) * m / 3:.1f}" y1="{zt:.1f}" x2="{zl + (zr - zl) * m / 3:.1f}" y2="{zb:.1f}" stroke="#7c96a5" stroke-width="1" stroke-dasharray="3,3" opacity=".7"/>')
            svg.append(f'<line x1="{zl:.1f}" y1="{zt + (zb - zt) * m / 3:.1f}" x2="{zr:.1f}" y2="{zt + (zb - zt) * m / 3:.1f}" stroke="#7c96a5" stroke-width="1" stroke-dasharray="3,3" opacity=".7"/>')
        svg.append(f'<rect x="{zl:.1f}" y="{zt:.1f}" width="{zr - zl:.1f}" height="{zb - zt:.1f}" fill="none" stroke="#5c7585" stroke-width="2"/>')
        py0, py1, cx, pw = Y(0.0), Y(-0.38), X(0), X(_ZONE_X) - X(0)
        svg.append(f'<polygon points="{cx - pw:.1f},{py0:.1f} {cx + pw:.1f},{py0:.1f} {cx + pw:.1f},{(py0 + py1) / 2:.1f} {cx:.1f},{py1:.1f} {cx - pw:.1f},{(py0 + py1) / 2:.1f}" fill="#fff" stroke="#5c7585" stroke-width="1.8"/>')
        for p, l in locs:
            call = _CALL_LABELS.get(l['call'], l['call'] or 'No result')
            tip = (f'{p["type"]} \u00b7 {call} \u00b7 {l["count"]} \u00b7 side {l["side"]:+.2f} ft, height {l["height"]:.2f} ft'
                   + (f' \u00b7 {l["velo"]:.1f} mph' if l.get('velo') else ''))
            svg.append(f'<circle class="mv-pt {uid}-dot" data-type="{p["type"]}" cx="{X(l["side"]):.1f}" cy="{Y(l["height"]):.1f}" r="5.5" '
                       f'fill="{p["color"]}" fill-opacity="0.85" stroke="#fff" stroke-width="1.2" data-tip="{tip}" '
                       f'data-ptype="{p["type"]}" data-pcolor="{p["color"]}"'
                       + (f' data-pvelo="{l["velo"]:.1f}"' if l.get('velo') else '')
                       + f' data-psub="{call} \u00b7 {l["count"]}"/>')
        svg.append('</svg>')

        def stat(name):
            pts = [l for p, l in locs if name == 'All' or p['type'] == name]
            n = len(pts)
            if not n:
                return 'No pitches'
            z = sum(1 for l in pts if _in_zone(l['side'], l['height']))
            return f'{n} pitches &middot; {z} in zone ({z / n * 100:.0f}%)'
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
    js = (f'<script>(function(){{var uid="{uid}",view="All",mode="both";'
          f'var vb=document.querySelectorAll("."+uid+"-btn:not(."+uid+"-mbtn)"),mb=document.querySelectorAll("."+uid+"-mbtn");'
          f'function render(){{vb.forEach(function(b){{b.classList.toggle("on",b.dataset.view===view)}});'
          f'mb.forEach(function(b){{b.classList.toggle("on",b.dataset.mode===mode)}});'
          f'document.querySelectorAll("."+uid+"-heat").forEach(function(g){{g.style.display=(g.dataset.view===view&&mode!=="dots")?"block":"none"}});'
          f'document.querySelectorAll("."+uid+"-stat").forEach(function(g){{g.style.display=g.dataset.view===view?"block":"none"}});'
          f'document.querySelectorAll("."+uid+"-dot").forEach(function(d){{d.style.display=((view==="All"||d.dataset.type===view)&&mode!=="heat")?"":"none"}});}}'
          f'vb.forEach(function(b){{b.addEventListener("click",function(){{view=b.dataset.view;render()}})}});'
          f'mb.forEach(function(b){{b.addEventListener("click",function(){{mode=b.dataset.mode;render()}})}});}})();</script>')
    modes = ''.join(f'<button type="button" class="{uid}-btn {uid}-mbtn{" on" if m == "both" else ""}" data-mode="{m}">{lbl}</button>'
                    for m, lbl in (('dots', 'Dots Only'), ('heat', 'Heat Map'), ('both', 'Both')))
    return (css + f'<div class="{uid}-btns">{modes}</div><div class="{uid}-btns">{btns}</div><div class="{uid}-row">'
            + one_chart('R', 'vs Right Handed Batter', uid + 'R')
            + one_chart('L', 'vs Left Handed Batter', uid + 'L')
            + '</div>' + js)
