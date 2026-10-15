"""
Hitting beta: hitter profiles from tracking-system pitch data.

Layout
  1. ADAPTERS   -- one small function per tracking system that turns a raw CSV row into the common
                   pitch dict below. Trackman is built; FullSwing / Yakkertech / Rapsodo are stubs
                   that only need a column map when their sample CSVs are available.
  2. DECISIONS  -- swing-decision classification (region of the zone x swing/take -> good/bad/neutral)
  3. STATS      -- plate discipline + batted-ball quality for one hitter
  4. CHARTS     -- decision chart (zone map) and spray chart wrapper
  5. STORE      -- hitters are discovered in the stored outings (every Batter in every pitcher file)

Common pitch dict:
  batter, side (L/R/None), date, pitcher, pitch_type, x, z (plate location, ft, catcher's view),
  outcome (ball|cs|whiff|foul|inplay|hbp|unk), ev, la, direction, distance, hit_type, balls, strikes, src
"""
import json
import math
import os
import re

import extract as e
import outings as outings_mod
import savant_components as sc
import store

# ---------------------------------------------------------------- 1. adapters
_HIT_TYPES = {'GroundBall': 'GB', 'LineDrive': 'LD', 'FlyBall': 'FB', 'Popup': 'PU', 'Bunt': 'BUNT'}


def _norm_trackman(r):
    side = {'Right': 'R', 'Left': 'L'}.get(r.get('BatterSide'))
    return {
        'batter': (r.get('Batter') or '').strip(), 'side': side, 'date': (r.get('Date') or '')[:10],
        'pitcher': r.get('Pitcher'), 'pitch_type': r.get('TaggedPitchType'),
        'x': e._fnum(r.get('PlateLocSide')), 'z': e._fnum(r.get('PlateLocHeight')),
        'outcome': e._outcome(r),
        'ev': e._fnum(r.get('ExitSpeed')), 'la': e._fnum(r.get('Angle')),
        'direction': e._fnum(r.get('Direction')), 'distance': e._fnum(r.get('Distance')),
        'hit_type': _HIT_TYPES.get(r.get('HitType')),
        'balls': r.get('Balls'), 'strikes': r.get('Strikes'), 'src': 'trackman',
    }


def _not_ready(name):
    def f(r):
        raise NotImplementedError(f'{name} adapter needs a sample CSV to map columns')
    return f


ADAPTERS = {
    'trackman': _norm_trackman,
    'fullswing': _not_ready('FullSwing'),
    'yakkertech': _not_ready('Yakkertech'),
    'rapsodo': _not_ready('Rapsodo'),
}


def detect_source(row):
    """Guess the tracking system from a row's columns. Only Trackman is live today."""
    if 'PitchUID' in row or 'RelSpeed' in row:
        return 'trackman'
    return 'trackman'


def normalize(rows, source=None):
    out = []
    for r in rows:
        try:
            out.append(ADAPTERS[source or detect_source(r)](r))
        except NotImplementedError:
            raise
        except Exception:
            continue
    return out


# --------------------------------------------------------------- 2. decisions
ZX, ZB, ZT = 0.83, 1.4, 3.6                      # same zone the pitching side uses
HEART_X, HEART_B, HEART_T = 0.55, 1.8, 3.2       # inner ~2/3 of the zone
SHADOW_OUT, CHASE_OUT = 0.25, 0.75               # ft beyond the zone edge
SWING = ('whiff', 'foul', 'inplay')
TAKE = ('ball', 'cs')


def region(x, z):
    if x is None or z is None:
        return None
    if abs(x) <= ZX and ZB <= z <= ZT:
        return 'heart' if (abs(x) <= HEART_X and HEART_B <= z <= HEART_T) else 'shadow'
    dx = max(abs(x) - ZX, 0.0)
    dz = max(ZB - z, z - ZT, 0.0)
    d = math.hypot(dx, dz)
    return 'shadow' if d <= SHADOW_OUT else ('chase' if d <= CHASE_OUT else 'waste')


def judge(p):
    """Returns (region, swung, verdict) with verdict good|bad|neutral, or None if the pitch can't be judged."""
    o = p['outcome']
    reg = region(p['x'], p['z'])
    if reg is None or (o not in SWING and o not in TAKE):
        return None
    swung = o in SWING
    if reg == 'shadow':
        v = 'neutral'
    elif reg == 'heart':
        v = 'good' if swung else 'bad'
    else:
        v = 'bad' if swung else 'good'
    return reg, swung, v


def grade(score):
    if score is None:
        return None
    return 'Elite' if score >= 85 else 'Strong' if score >= 75 else 'Solid' if score >= 65 else 'Developing' if score >= 55 else 'Needs work'


# ------------------------------------------------------------------ 3. stats
def _pct(a, b, d=0):
    if not b:
        return None
    v = round(100 * a / b, d)
    return int(v) if d == 0 else v


def _quantile(vals, q):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def spray_zone(p):
    """pull / center / oppo for one batted ball, relative to the hitter's handedness."""
    d, side = p['direction'], p['side']
    if d is None or side is None:
        return None
    toward_pull = -d if side == 'R' else d          # RHH pulls to left field (negative direction)
    return 'pull' if toward_pull > 15 else 'oppo' if toward_pull < -15 else 'center'


def hitter_stats(pitches):
    n = len(pitches)
    judged = [(p, j) for p in pitches for j in [judge(p)] if j]
    good = sum(1 for _, j in judged if j[2] == 'good')
    bad = sum(1 for _, j in judged if j[2] == 'bad')
    decided = good + bad

    def cnt(reg=None, swung=None, verdict=None):
        return sum(1 for _, j in judged if (reg is None or j[0] in reg) and (swung is None or j[1] == swung)
                   and (verdict is None or j[2] == verdict))

    in_zone = ('heart', 'shadow')
    out_zone = ('chase', 'waste')
    zone_sw, zone_n = cnt(in_zone, True), cnt(in_zone)
    chase_sw, chase_n = cnt(out_zone, True), cnt(out_zone)
    heart_sw, heart_n = cnt(('heart',), True), cnt(('heart',))
    swings = [p for p in pitches if p['outcome'] in SWING]
    whiffs = sum(1 for p in swings if p['outcome'] == 'whiff')
    zone_swings = [p for p, j in judged if j[1] and j[0] in in_zone]
    zone_contact = sum(1 for p in zone_swings if p['outcome'] != 'whiff')
    pa = sum(1 for p in pitches if (p['balls'], p['strikes']) == ('0', '0'))

    bbs = [p for p in pitches if p['outcome'] == 'inplay' and p['ev'] is not None]
    evs = [p['ev'] for p in bbs]
    las = [p['la'] for p in bbs if p['la'] is not None]
    hit_types = [p['hit_type'] for p in bbs if p['hit_type']]
    zones = [spray_zone(p) for p in bbs if spray_zone(p)]
    score = round(100 * good / decided) if decided else None
    return {
        'pitches': n, 'pa': pa, 'decisions': decided,
        'score': score, 'grade': grade(score) if decided >= 15 else None,
        'good': good, 'bad': bad, 'neutral': cnt(verdict='neutral'),
        'swing_pct': _pct(len(swings), len(judged)),
        'zone_swing_pct': _pct(zone_sw, zone_n), 'chase_pct': _pct(chase_sw, chase_n),
        'heart_swing_pct': _pct(heart_sw, heart_n),
        'heart_takes': heart_n - heart_sw, 'chases': chase_sw,
        'zone_contact_pct': _pct(zone_contact, len(zone_swings)), 'whiff_pct': _pct(whiffs, len(swings)),
        'bip': len(bbs),
        'avg_ev': round(sum(evs) / len(evs), 1) if evs else None,
        'max_ev': round(max(evs), 1) if evs else None,
        'ev90': round(_quantile(evs, 0.9), 1) if len(evs) >= 5 else None,
        'hard_hit_pct': _pct(sum(1 for v in evs if v >= 95), len(evs)),
        'avg_la': round(sum(las) / len(las), 1) if las else None,
        'sweet_spot_pct': _pct(sum(1 for v in las if 8 <= v <= 32), len(las)),
        'gb_pct': _pct(hit_types.count('GB'), len(hit_types)), 'ld_pct': _pct(hit_types.count('LD'), len(hit_types)),
        'fb_pct': _pct(hit_types.count('FB') + hit_types.count('PU'), len(hit_types)),
        'pull_pct': _pct(zones.count('pull'), len(zones)), 'center_pct': _pct(zones.count('center'), len(zones)),
        'oppo_pct': _pct(zones.count('oppo'), len(zones)),
    }


def takeaways(s):
    """Plain-English coaching read of the numbers. Only says what the sample can support."""
    out = []
    if s['decisions'] < 15:
        return [f"Small sample ({s['decisions']} judged pitches). Read these numbers as a first look, not a verdict."]
    if s['chase_pct'] is not None and s['chases'] >= 2:
        out.append(f"Chases {s['chase_pct']}% of pitches outside the zone ({s['chases']} swings)." if s['chase_pct'] >= 30
                   else f"Stays disciplined: only {s['chase_pct']}% chase outside the zone." if s['chase_pct'] <= 20 else None)
        out = [x for x in out if x]
    if s['heart_swing_pct'] is not None and s['heart_takes'] >= 2 and s['heart_swing_pct'] < 60:
        out.append(f"Lets {s['heart_takes']} hittable pitches go by (swings at {s['heart_swing_pct']}% of the heart).")
    if s['zone_contact_pct'] is not None and s['zone_contact_pct'] < 75:
        out.append(f"Misses too many in the zone: {s['zone_contact_pct']}% contact on in-zone swings.")
    if s['hard_hit_pct'] is not None and s['bip'] >= 5:
        out.append(f"{s['hard_hit_pct']}% of balls in play are hit 95+ mph (max {s['max_ev']}).")
    return out


# ----------------------------------------------------------------- 4. charts
_GOOD, _BAD, _NEUT = '#2f9e6b', '#d0503f', '#9aa5ab'


def decision_chart_svg(pitches, side=None, width=330, height=360):
    """Catcher's-view zone map. Every pitch the hitter saw: filled dot = swing, ring = take;
    green = good decision, red = bad, grey = neutral (shadow). Heart and shadow outlined."""
    xr, zr = (-2.7, 2.7), (0.4, 4.6)
    k = min(width / (xr[1] - xr[0]), height / (zr[1] - zr[0]))
    ox = (width - k * (xr[1] - xr[0])) / 2

    def X(v):
        return ox + (v - xr[0]) * k

    def Y(v):
        return (zr[1] - v) * k

    h = int(Y(zr[0]))
    svg = [f'<svg viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:auto;" '
           f'font-family="Barlow,Arial,sans-serif"><rect width="{width}" height="{h}" fill="#f4f8fa"/>']
    if side in ('L', 'R'):
        svg.append('<g opacity=".4">' + sc._batter_outline_svg(X(1.68 if side == 'L' else -1.68), Y(0.0), k, side == 'L') + '</g>')
    # chase band, shadow band, zone, heart
    svg.append(f'<rect x="{X(-ZX-CHASE_OUT):.1f}" y="{Y(ZT+CHASE_OUT):.1f}" width="{k*(2*ZX+2*CHASE_OUT):.1f}" height="{k*(ZT-ZB+2*CHASE_OUT):.1f}" rx="14" fill="none" stroke="#c9d3d8" stroke-dasharray="3 4"/>')
    svg.append(f'<rect x="{X(-ZX-SHADOW_OUT):.1f}" y="{Y(ZT+SHADOW_OUT):.1f}" width="{k*(2*ZX+2*SHADOW_OUT):.1f}" height="{k*(ZT-ZB+2*SHADOW_OUT):.1f}" rx="8" fill="#e8eef1" fill-opacity=".6" stroke="none"/>')
    svg.append(f'<rect x="{X(-ZX):.1f}" y="{Y(ZT):.1f}" width="{k*2*ZX:.1f}" height="{k*(ZT-ZB):.1f}" fill="#fff" stroke="#5c6b74" stroke-width="1.6"/>')
    svg.append(f'<rect x="{X(-HEART_X):.1f}" y="{Y(HEART_T):.1f}" width="{k*2*HEART_X:.1f}" height="{k*(HEART_T-HEART_B):.1f}" fill="#f1f7f4" stroke="#b9cfc5" stroke-dasharray="4 3"/>')
    for p in pitches:
        j = judge(p)
        if not j:
            continue
        reg, swung, v = j
        col = {'good': _GOOD, 'bad': _BAD, 'neutral': _NEUT}[v]
        cx, cy = X(max(xr[0], min(xr[1], p['x']))), Y(max(zr[0], min(zr[1], p['z'])))
        tip = f"{(p['pitch_type'] or 'Pitch')} · {'Swing' if swung else 'Take'} · {p['outcome']}"
        if swung:
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.2" fill="{col}" fill-opacity=".88" stroke="#fff" stroke-width="1"><title>{tip}</title></circle>')
        else:
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.6" fill="#fff" fill-opacity=".7" stroke="{col}" stroke-width="2"><title>{tip}</title></circle>')
    svg.append(f'<polygon points="{X(-.35):.1f},{h-8} {X(.35):.1f},{h-8} {X(.35):.1f},{h-13} {X(0):.1f},{h-17} {X(-.35):.1f},{h-13}" fill="#fff" stroke="#9aa5ab"/>')
    svg.append('</svg>')
    return ''.join(svg)


def spray_html(pitches, width=400, height=352):
    pts = []
    for p in pitches:
        if p['outcome'] == 'inplay' and p['direction'] is not None and p['distance'] is not None:
            pts.append({'direction': p['direction'], 'distance': p['distance'], 'ev': p['ev'], 'la': p['la'], 'type': p['hit_type']})
    if not pts:
        return '<div class="empty">No tracked batted balls yet.</div>'
    return sc.spray_chart_interactive_html(pts, width=width, height=height) + sc.spray_chart_legend_html()


# ------------------------------------------------------------------ 5. store
def _slug(name):
    return store.slugify(re.sub(r'\s+', ' ', name))


def _all_pitch_files():
    """(slug, is_demo) for every pitcher with stored outings, real ones first."""
    real = []
    d = outings_mod.OUTINGS_DIR
    if os.path.isdir(d):
        real = sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json'))
    demo = []
    dd = os.path.join(store.DEMO_DIR, 'outings')
    if os.path.isdir(dd):
        demo = sorted(f[:-5] for f in os.listdir(dd) if f.endswith('.json'))
    return [(s, False) for s in real], [(s, True) for s in demo]


def _collect(include_demo):
    """{batter slug: {'name', 'program', 'demo', 'pitches': [...]}}"""
    real, demo = _all_pitch_files()
    out = {}
    for slug, is_demo in real + (demo if include_demo else []):
        if is_demo and any(s == slug for s, _ in real):
            continue
        pl = store.get_player(slug) or {}
        prog = pl.get('program') or ('demo_university' if is_demo else 'shepherds')
        for o in outings_mod.load(slug)['outings']:
            for p in normalize(o['rows']):
                if not p['batter']:
                    continue
                key = _slug(p['batter']) + ('--demo' if is_demo else '')
                h = out.setdefault(key, {'name': p['batter'], 'program': prog, 'demo': is_demo, 'pitches': []})
                h['pitches'].append(p)
    return out


def display_name(n):
    if ',' in n:
        last, first = [x.strip() for x in n.split(',', 1)]
        return f'{first} {last}'.strip()
    return n


def list_hitters(include_demo=True):
    rows = []
    for key, h in _collect(include_demo).items():
        s = hitter_stats(h['pitches'])
        sides = {p['side'] for p in h['pitches'] if p['side']}
        rows.append({'key': key, 'name': display_name(h['name']), 'raw': h['name'], 'program': h['program'], 'demo': h['demo'],
                     'bats': 'S' if len(sides) > 1 else (next(iter(sides)) if sides else '?'), 's': s})
    rows.sort(key=lambda r: (r['demo'], -r['s']['pitches']))
    return rows


def hitter_profile(key, include_demo=True):
    h = _collect(include_demo).get(key)
    if not h:
        return None
    ps = h['pitches']
    sides = {p['side'] for p in ps if p['side']}
    bats = 'S' if len(sides) > 1 else (next(iter(sides)) if sides else None)
    s = hitter_stats(ps)
    import benchmarks as bm
    prow = []
    if s['ev90'] is not None:
        prow.append({'label': 'EV90', 'pctl': bm.interpolate(s['ev90'], bm.HITTER['ev90']), 'value_display': f"{s['ev90']:.1f}"})
    if s['whiff_pct'] is not None and len([p for p in ps if p['outcome'] in SWING]) >= 10:
        prow.append({'label': 'Whiff%', 'pctl': bm.interpolate(s['whiff_pct'], bm.HITTER['whiff_pct']), 'value_display': f"{s['whiff_pct']:.0f}%"})
    return {'pctl_html': sc.percentile_bars_html(prow) if prow else '', 'key': key, 'name': display_name(h['name']), 'program': h['program'], 'demo': h['demo'], 'bats': bats,
            's': s, 'notes': takeaways(s), 'dates': sorted({p['date'] for p in ps if p['date']}),
            'decision_svg': decision_chart_svg(ps, side=bats if bats in ('L', 'R') else None),
            'spray': spray_html(ps)}
