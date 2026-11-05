"""Exit Velocity by Quadrant: the strike zone cut into 9 pockets (catcher's view), each showing how hard the ball was hit there and how often hitters swung and missed.
One grid per pitch type plus an All view; a row of buttons switches between them."""
import extract as e
import pitchfx

HALF = 17 / 24                     # half the plate, feet
BOT, TOP = 1.5, 3.5                # generic zone height, feet
COLS = ('Glove side' , 'Middle', 'Arm side')
ROWS = ('Up', 'Middle', 'Down')


def _cell(side, height):
    """(row, col) of the pocket for a pitch inside the zone, else None. side is PlateLocSide as stored (+ = catcher's left); the chart is drawn from the catcher's view."""
    x = -side
    if not (-HALF <= x <= HALF and BOT <= height <= TOP):
        return None
    c = min(2, int((x + HALF) / (2 * HALF) * 3))
    r = min(2, int((TOP - height) / (TOP - BOT) * 3))
    return r, c


def _ev_color(v):
    """Cool blue for soft contact up to hot red for hard contact (hard contact is the bad outcome for a pitcher)."""
    lo, mid, hi = 78.0, 86.0, 94.0
    v = max(lo, min(hi, v))
    if v <= mid:
        t = (v - lo) / (mid - lo)
        a, b = (74, 127, 181), (245, 245, 245)
    else:
        t = (v - mid) / (hi - mid)
        a, b = (245, 245, 245), (205, 70, 52)
    rgb = [round(a[i] + (b[i] - a[i]) * t) for i in range(3)]
    dark = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 150
    return 'rgb(%d,%d,%d)' % tuple(rgb), ('#fff' if dark else '#22303a')


def _grid(rows, label):
    cells = [[{'evs': [], 'sw': 0, 'wh': 0, 'n': 0} for _ in range(3)] for _ in range(3)]
    for r in rows:
        s, h = e._fnum(r.get('PlateLocSide')), e._fnum(r.get('PlateLocHeight'))
        if s is None or h is None:
            continue
        rc = _cell(s, h)
        if not rc:
            continue
        c = cells[rc[0]][rc[1]]
        c['n'] += 1
        o = e._outcome(r)
        if o in ('whiff', 'foul', 'inplay'):
            c['sw'] += 1
        if o == 'whiff':
            c['wh'] += 1
        if o == 'inplay' and (r.get('HitType') or '') != 'Bunt':
            v = e._fnum(r.get('ExitSpeed'))
            if v:
                c['evs'].append(v)
    total = sum(c['n'] for row in cells for c in row)
    if not total:
        return ''
    h = ['<div class="zg-wrap"><div class="zg-top">3B side &larr; catcher\'s view &rarr; 1B side</div><div class="zg-row"><div class="zg-side"><span>Up</span><span>Mid</span><span>Down</span></div><div class="zg">']
    for row in cells:
        for c in row:
            n_b = len(c['evs'])
            ev = sum(c['evs']) / n_b if n_b else None
            wh = 100.0 * c['wh'] / c['sw'] if c['sw'] else None
            bg, fg = _ev_color(ev) if ev is not None else ('#f1f3f4', '#8a98a0')
            thin = ' zg-thin' if (n_b < 3 and c['sw'] < 5) else ''
            tip = f"{c['n']} pitches in this pocket &middot; {n_b} balls in play &middot; {c['wh']} of {c['sw']} swings missed"
            h.append(f'<div class="zg-c{thin}" style="background:{bg};color:{fg}" title="{tip}"><b>{ev:.1f}</b><small>mph &middot; {n_b} BIP</small>' if ev is not None
                     else f'<div class="zg-c{thin}" style="background:{bg};color:{fg}" title="{tip}"><b>&mdash;</b><small>no balls in play</small>')
            h.append(f'<em>{wh:.0f}% whiff <i>({c["wh"]}/{c["sw"]})</i></em></div>' if wh is not None else '<em>no swings</em></div>')
    h.append('</div></div></div>')
    return ''.join(h)


def build(rows, order, colors):
    """-> {'views': [{'key','label','color','html'}]} (All first) or None when no pitch landed in the zone."""
    views = []
    allh = _grid(rows, 'All')
    if not allh:
        return None
    views.append({'key': 'all', 'label': 'All pitches', 'color': None, 'html': allh, 'n': len(rows)})
    by = {}
    for r in rows:
        t = pitchfx._label(r)
        if t:
            by.setdefault(t, []).append(r)
    if len(by) > 1 or (by and 'Untagged' not in by):
        for t in order:
            if t in by and t != 'Untagged':
                g = _grid(by[t], t)
                if g:
                    views.append({'key': t, 'label': t, 'color': colors.get(t, '#555'), 'html': g, 'n': len(by[t])})
    return {'views': views}
