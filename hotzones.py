"""Each hitter's hot and cold zones, so swing decisions can credit a hitter for sticking to his approach.

The strike zone plus its edge is split 3 x 3 from the hitter's point of view (up / middle / down by in / middle / away). In every box the
value of a swing is its chance of a hit off the exit velocity and launch angle (a whiff counts 0; fouls and balls in play with no tracking
are left out). A hitter with few swings in a box is assumed to be like his team there; his own results take over as they build up
(about K_HITTER swings to be half him, half the team). A box is hot or cold when he does clearly better or worse there than in his
other boxes, measured against what hitters usually do in that box, and only once he has at least MIN_SWINGS of his own there.
A coach can mark a box hot, cold or neither by hand, which always wins."""
import hitting as H

ROWS = ('up', 'mid', 'down')
COLS = ('in', 'mid', 'away')
K_HITTER = 8            # swings that count as much as the team average
K_PROGRAM = 30          # team box average blended with everyone's until it has this many swings
MIN_SWINGS = 3          # his own swings in a box before it can be called hot or cold
GAP = 0.05              # how far above / below his own norm (hits per swing) makes a box hot / cold
TAGS = ('hot', 'cold', 'none')


def cell(p):
    """(row, col) from the hitter's view, or None (no location or batting side, or off the zone's edge)."""
    x, z, side = p.get('x'), H.zone_z(p), p.get('side')
    if x is None or z is None or side not in ('L', 'R'):
        return None
    if H.region(x, z) not in ('heart', 'shadow'):          # his own zone (sized from his height when known)
        return None
    u = -x if side == 'R' else x                 # + = inside (toward the hitter); stored x is + toward the catcher's right
    third_x = H.ZX / 3
    col = 0 if u > third_x else (2 if u < -third_x else 1)
    lo = H.ZB + (H.ZT - H.ZB) / 3
    hi = H.ZB + 2 * (H.ZT - H.ZB) / 3
    row = 0 if z > hi else (2 if z < lo else 1)
    return row, col


def cell_xy(row, col, side):
    """Catcher's-view column (0 = catcher's left) for drawing a hitter-view box."""
    # inside is the catcher's left for a right-handed hitter
    if side == 'L':
        return 2 - col
    return col


def swing_value(p):
    o = p.get('outcome')
    if o == 'whiff':
        return 0.0
    if o == 'inplay' and p.get('hit_type') != 'BUNT':
        return H.hit_prob(p.get('ev'), p.get('la'))
    return None


def _sums(pitches):
    s = {}
    for p in pitches:
        c = cell(p)
        if c is None:
            continue
        v = swing_value(p)
        if v is None:
            continue
        a = s.setdefault(c, [0.0, 0])
        a[0] += v
        a[1] += 1
    return s


def _cells():
    return [(r, c) for r in range(3) for c in range(3)]


def apply(hitters, overrides=None):
    """hitters: {key: {'program', 'pitches'}}. Tags each pitch with p['hz'] = 'hot' / 'cold' / None and gives each hitter
    h['zones'] = 9 boxes (row-major, hitter's view). overrides: {key: {'r,c': 'hot'|'cold'|'none'}}."""
    overrides = overrides or {}
    per = {k: _sums(h['pitches']) for k, h in hitters.items()}
    glob, prog = {}, {}
    for k, h in hitters.items():
        for c, (v, n) in per[k].items():
            for d in (glob.setdefault(c, [0.0, 0]), prog.setdefault((h['program'], c), [0.0, 0])):
                d[0] += v
                d[1] += n
    g_all = sum(v for v, _ in glob.values()) / max(1, sum(n for _, n in glob.values())) if glob else 0.2
    gbase = {c: ((glob[c][0] + 10 * g_all) / (glob[c][1] + 10)) if c in glob else g_all for c in _cells()}
    for k, h in hitters.items():
        mine = per[k]
        ov = overrides.get(k) or {}
        boxes = []
        for c in _cells():
            pv, pn = prog.get((h['program'], c), (0.0, 0))
            base = (pv + K_PROGRAM * gbase[c]) / (pn + K_PROGRAM)
            v, n = mine.get(c, (0.0, 0))
            est = (v + K_HITTER * base) / (n + K_HITTER)
            boxes.append({'r': c[0], 'c': c[1], 'n': n, 'est': est, 'base': base, 'diff': est - base})
        norm = sum(b['diff'] for b in boxes) / len(boxes)       # his overall level, so a good hitter isn't "hot" everywhere
        tags = {}
        for b in boxes:
            b['dev'] = b['diff'] - norm
            auto = None
            if b['n'] >= MIN_SWINGS:
                auto = 'hot' if b['dev'] >= GAP else ('cold' if b['dev'] <= -GAP else None)
            o = ov.get(f"{b['r']},{b['c']}")
            b['auto'], b['override'] = auto, (o if o in TAGS else None)
            b['tag'] = (None if o == 'none' else o) if o in TAGS else auto
            tags[(b['r'], b['c'])] = b['tag']
        h['zones'] = boxes
        for p in h['pitches']:
            c = cell(p)
            p['hz'] = tags.get(c) if c else None
    return hitters


def grid_html(boxes, bats, editable=False):
    """The 3 x 3 hot-zone grid for a hitter's page, drawn from the catcher's view when his side is known (from his own view for a
    switch hitter). editable adds the coach's tap-to-change control."""
    from html import escape
    if not boxes:
        return ''
    by = {(b['r'], b['c']): b for b in boxes}
    flip = bats == 'L'                   # catcher's view: a lefty's inside is on the catcher's right
    cols = [2, 1, 0] if flip else [0, 1, 2]
    head = (['Away', 'Middle', 'In'] if flip else ['In', 'Middle', 'Away']) if bats in ('L', 'R') else ['In', 'Middle', 'Away']
    out = [f'<div class="hz{" hz-ed" if editable else ""}"><div class="hz-c"></div>' + ''.join(f'<div class="hz-c">{h}</div>' for h in head)]
    for r in range(3):
        out.append(f'<div class="hz-r">{("Up", "Middle", "Down")[r]}</div>')
        for c in cols:
            b = by[(r, c)]
            tag = b['tag'] or ''
            src = 'Set by a coach' if b['override'] else ('From his swings' if b['auto'] else '')
            val = ('.' + f"{b['est']:.3f}".split('.')[1]) if b['n'] else '–'
            base_txt = '.' + f"{b['base']:.3f}".split('.')[1]
            title = (f"{('Hot' if tag == 'hot' else 'Cold' if tag == 'cold' else 'Neutral')} zone. "
                     f"{b['n']} tracked swing{'s' if b['n'] != 1 else ''} here; hit chance per swing {val} (team {base_txt})."
                     + (f' {src}.' if src else ''))
            lab = 'Hot' if tag == 'hot' else 'Cold' if tag == 'cold' else ''
            pen = '<i class="hz-pen" title="Set by a coach">&#9998;</i>' if b['override'] else ''
            inner = f'<b>{lab}</b><span>{b["n"]} sw</span>{pen}'
            cls = f'hz-b hz-{tag or "n"}'
            if editable:
                out.append(f'<button type="button" class="{cls}" data-cell="{r},{c}" data-ov="{escape(b["override"] or "auto")}" title="{escape(title)} Tap to change.">{inner}</button>')
            else:
                out.append(f'<div class="{cls}" title="{escape(title)}">{inner}</div>')
    out.append('</div>')
    return ''.join(out)
