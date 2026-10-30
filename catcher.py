"""Catcher reports (beta): receiving, arm and pitch-calling tendencies, built from the Catcher name Trackman records on each pitch.

Only Game, Scrimmage and Intrasquad pitches count (bullpens rarely name a catcher and aren't a catcher's work). Only our own pitchers' files are used:
a catcher's pitches are the ones thrown to him by our pitchers (opposing pitchers' files carry the other team's catcher).
Horizontal location comes from hitting._norm_trackman, which already flips Trackman's PlateLocSide so + = the catcher's right.
"""
import math
import os
import re

import cache
import extract as e
import hitting
import outings as outings_mod
import stats as stats_mod
import store

SESSIONS = ('Game', 'Scrimmage', 'Intrasquad')
BORDER = 0.25           # ft either side of the zone edge: "borderline" pitches
WINDOW = 0.50           # ft: pitches this close to the edge are in the expected-strike comparison
MIN_BORDER = 25         # borderline takes before receiving numbers are called a rating
POP_RANGE = (1.45, 3.1)  # seconds: outside this a "pop time" is not a steal attempt (a toss back to the pitcher, a miss-read)
MIN_THROW_MPH = 55.0

# pitch families: fastball / breaking / offspeed (stats.FAMILIES holds the pitch-type groupings)
_FAM = {}
for _fid, _ab, _nm, _members, _note in stats_mod.FAMILIES:
    for _m in _members:
        _FAM[_m] = {'fb': 'Fastball', 'cb': 'Breaking', 'sl': 'Breaking', 'ch': 'Offspeed'}[_fid]


def display(name):
    return hitting.display_name((name or '').strip())


def _key(name):
    return hitting._slug(display(name))


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


@cache.memo
def collect(program):
    """{catcher key: {'name', 'rows': [raw rows], 'pitchers': {name}, 'dates': set}} for one program's own pitchers."""
    real, demo = hitting._all_pitch_files()
    out = {}
    for slug, is_demo in real + demo:
        if slug.startswith('opp-') or (is_demo and any(s == slug for s, _ in real)):
            continue
        pl = store.get_player(slug) or {}
        prog = pl.get('program') or ('demo_university' if is_demo else 'shepherds')
        if prog != program:
            continue
        for o in outings_mod.load(slug)['outings']:
            for r in o['rows']:
                if r.get('SessionType') not in SESSIONS:
                    continue
                c = (r.get('Catcher') or '').strip()
                if not c or c.lower() in ('undefined', 'unknown'):
                    continue
                k = _key(c)
                d = out.setdefault(k, {'name': display(c), 'rows': [], 'pitchers': {}, 'dates': set()})
                d['rows'].append(r)
                pn = display(r.get('Pitcher') or pl.get('name') or slug)
                d['pitchers'][pn] = d['pitchers'].get(pn, 0) + 1
                d['dates'].add(str(r.get('Date') or o.get('date') or '')[:10])
    return out


# ---------------------------------------------------------------- receiving
def edge_dist(x, z):
    """Feet from the strike-zone edge: negative inside, positive outside."""
    dx, dz = abs(x) - hitting.ZX, max(hitting.ZB - z, z - hitting.ZT)
    if dx <= 0 and dz <= 0:
        return max(dx, dz)
    return math.hypot(max(dx, 0.0), max(dz, 0.0))


def _takes(rows):
    """[(d, called_strike?, x, z)] for pitches the batter took (ball or called strike) that have a location."""
    out = []
    for r in rows:
        p = hitting._norm_trackman(r)
        if p['outcome'] not in ('ball', 'cs') or p['x'] is None or p['z'] is None:
            continue
        out.append((edge_dist(p['x'], p['z']), p['outcome'] == 'cs', p['x'], p['z']))
    return out


def fit_zone_model(takes):
    """Logistic curve for P(called strike) by distance from the edge, fit to every take near the edge in the pool (our own umpires, our own
    data). Falls back to a typical curve when the pool is small."""
    pts = [(d, 1.0 if cs else 0.0) for d, cs, _, _ in takes if abs(d) <= 0.7]
    a, b = 0.0, 22.0          # p = 1 / (1 + exp(-(a - b d)))
    if len(pts) < 150:
        return a, b
    for _ in range(25):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for d, y in pts:
            p = 1 / (1 + math.exp(-(a - b * d)))
            w = p * (1 - p)
            g0 += y - p
            g1 += -(y - p) * d
            h00 += w
            h01 += -w * d
            h11 += w * d * d
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-9:
            break
        a += (h11 * g0 - h01 * g1) / det
        b += (-h01 * g0 + h00 * g1) / det
        b = max(4.0, min(60.0, b))
    return a, b


def p_strike(model, d):
    a, b = model
    return 1 / (1 + math.exp(-(a - b * d)))


def receiving(rows, model):
    t = _takes(rows)
    near = [x for x in t if abs(x[0]) <= WINDOW]
    border = [x for x in t if abs(x[0]) <= BORDER]
    outside = [x for x in border if x[0] > 0]
    inside = [x for x in border if x[0] <= 0]
    exp = sum(p_strike(model, x[0]) for x in near)
    act = sum(1 for x in near if x[1])
    extra = act - exp
    return {
        'takes': len(t), 'border_n': len(border), 'border_cs': sum(1 for x in border if x[1]),
        'border_pct': round(100 * sum(1 for x in border if x[1]) / len(border), 1) if border else None,
        'out_n': len(outside), 'out_cs': sum(1 for x in outside if x[1]),
        'out_pct': round(100 * sum(1 for x in outside if x[1]) / len(outside), 1) if outside else None,
        'in_n': len(inside), 'in_cs': sum(1 for x in inside if x[1]),
        'in_pct': round(100 * sum(1 for x in inside if x[1]) / len(inside), 1) if inside else None,
        'near_n': len(near), 'extra': round(extra, 1), 'per100': round(100 * extra / len(near), 1) if near else None,
        'rated': len(border) >= MIN_BORDER, 'points': [(x[2], x[3], x[1]) for x in t if abs(x[0]) <= 0.9],
    }


def zone_svg(points, width=360):
    """Catcher's-view picture of every taken pitch near the zone: green = called strike, grey = ball."""
    x0, x1, z0, z1 = -1.9, 1.9, 0.4, 4.6
    k = width / (x1 - x0)
    h = round((z1 - z0) * k)
    X = lambda v: (v - x0) * k
    Y = lambda v: (z1 - v) * k
    zl, zr, zt, zb = X(-hitting.ZX), X(hitting.ZX), Y(hitting.ZT), Y(hitting.ZB)
    s = [f'<svg viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:{width}px;height:auto;display:block;margin:0 auto;" font-family="Barlow,Arial,sans-serif">',
         f'<rect width="{width}" height="{h}" fill="#fff"/>']
    pad = BORDER * k          # the borderline band, a quarter-foot either side of the edge
    s.append(f'<rect x="{zl - pad:.1f}" y="{zt - pad:.1f}" width="{zr - zl + 2 * pad:.1f}" height="{zb - zt + 2 * pad:.1f}" rx="6" fill="#f3f7f8" stroke="#b8c7cd" stroke-dasharray="4 4"/>')
    s.append(f'<rect x="{zl:.1f}" y="{zt:.1f}" width="{zr - zl:.1f}" height="{zb - zt:.1f}" fill="#fff" stroke="#22303a" stroke-width="1.6"/>')
    for m in (1, 2):
        s.append(f'<line x1="{zl + (zr - zl) * m / 3:.1f}" y1="{zt:.1f}" x2="{zl + (zr - zl) * m / 3:.1f}" y2="{zb:.1f}" stroke="#22303a" stroke-opacity=".12"/>')
        s.append(f'<line x1="{zl:.1f}" y1="{zt + (zb - zt) * m / 3:.1f}" x2="{zr:.1f}" y2="{zt + (zb - zt) * m / 3:.1f}" stroke="#22303a" stroke-opacity=".12"/>')
    for x, z, cs in points:
        if cs:
            s.append(f'<circle cx="{X(x):.1f}" cy="{Y(z):.1f}" r="5" fill="#2f9e6b" fill-opacity=".85" stroke="#fff" stroke-width="1"/>')
        else:
            s.append(f'<circle cx="{X(x):.1f}" cy="{Y(z):.1f}" r="4.5" fill="#fff" stroke="#8a97a0" stroke-width="1.6"/>')
    s.append('</svg>')
    return ''.join(s)


# ---------------------------------------------------------------- arm
def arm(rows):
    thr = []
    for r in rows:
        pop = _num(r.get('PopTime'))
        if pop is None or not (POP_RANGE[0] <= pop <= POP_RANGE[1]):
            continue
        mph = _num(r.get('ThrowSpeed'))
        if mph is None or mph < MIN_THROW_MPH:
            continue
        thr.append({'date': str(r.get('Date') or '')[:10], 'pt': pop, 'exch': _num(r.get('ExchangeTime')), 'mph': mph, 'tb': _num(r.get('TimeToBase'))})
    ex = [t['exch'] for t in thr if t['exch'] is not None]
    tb = [t['tb'] for t in thr if t['tb'] is not None]
    return {'n': len(thr), 'best_pop': min((t['pt'] for t in thr), default=None), 'avg_pop': (sum(t['pt'] for t in thr) / len(thr)) if thr else None,
            'best_exch': min(ex, default=None), 'avg_exch': (sum(ex) / len(ex)) if ex else None,
            'avg_mph': (sum(t['mph'] for t in thr) / len(thr)) if thr else None, 'top_mph': max((t['mph'] for t in thr), default=None),
            'avg_tb': (sum(tb) / len(tb)) if tb else None, 'throws': sorted(thr, key=lambda t: t['pt'])}


# ---------------------------------------------------------------- pitch calling
BANDS = [('First pitch (0-0)', lambda b, s: (b, s) == (0, 0)), ('Pitcher ahead (1-2 strikes more than balls, under 2 strikes)', None),
         ('Even count', None), ('Hitter ahead (more balls than strikes)', None), ('Two strikes', lambda b, s: s == 2)]


def _band(b, s):
    if (b, s) == (0, 0):
        return 0
    if s == 2:
        return 4
    if s > b:
        return 1
    if s == b:
        return 2
    return 3


BAND_NAMES = ['First pitch', 'Pitcher ahead', 'Even count', 'Hitter ahead', 'Two strikes']


def calling(rows):
    mix = [{'n': 0, 'Fastball': 0, 'Breaking': 0, 'Offspeed': 0, 'Other': 0} for _ in BAND_NAMES]
    tot = {'n': 0, 'Fastball': 0, 'Breaking': 0, 'Offspeed': 0, 'Other': 0}
    for r in rows:
        fam = _FAM.get(re.sub(r'[^a-z0-9]', '', str(r.get('TaggedPitchType') or '').lower()), 'Other')
        tot['n'] += 1
        tot[fam] += 1
        bs, ss = _num(r.get('Balls')), _num(r.get('Strikes'))
        if bs is None or ss is None:
            continue
        m = mix[_band(int(bs), int(ss))]
        m['n'] += 1
        m[fam] += 1

    def pct(d, f):
        return round(100 * d[f] / d['n'], 1) if d['n'] else None
    return {'overall': {f: pct(tot, f) for f in ('Fastball', 'Breaking', 'Offspeed', 'Other')}, 'n': tot['n'],
            'bands': [{'name': BAND_NAMES[i], 'n': m['n'], **{f: pct(m, f) for f in ('Fastball', 'Breaking', 'Offspeed')}} for i, m in enumerate(mix)]}


RESULT_IDS = [('strike_pct', 'Strike %'), ('zone_pct', 'Zone %'), ('fps_pct', 'First-pitch strike %'), ('whiff_pct', 'Whiff %'), ('chase_pct', 'Chase %'),
              ('csw_pct', 'CSW %'), ('hh_pct', 'Hard-hit % allowed'), ('avg_ev', 'Avg exit velo allowed')]


def results(rows):
    v = stats_mod.compute(rows)
    return {i: (v[i][0] if i in v else '-') for i, _ in RESULT_IDS}


def pitcher_split(c):
    by = {}
    for r in c['rows']:
        by.setdefault(display(r.get('Pitcher') or ''), []).append(r)
    out = []
    for n, rs in by.items():
        v = stats_mod.compute(rs)
        out.append({'name': n or 'Unknown', 'n': len(rs), 'strike': v.get('strike_pct', ('-',))[0], 'whiff': v.get('whiff_pct', ('-',))[0], 'csw': v.get('csw_pct', ('-',))[0]})
    return sorted(out, key=lambda x: -x['n'])


# ---------------------------------------------------------------- everything for one program
@cache.memo
def build(program):
    cs = collect(program)
    all_rows = [r for c in cs.values() for r in c['rows']]
    model = fit_zone_model(_takes(all_rows))
    team_call = calling(all_rows)
    out = {}
    for k, c in cs.items():
        rows = c['rows']
        out[k] = {'key': k, 'name': c['name'], 'n': len(rows), 'games': len({d for d in c['dates'] if d}), 'pitchers': len(c['pitchers']),
                  'recv': receiving(rows, model), 'arm': arm(rows), 'call': calling(rows), 'res': results(rows), 'splits': pitcher_split(c)}
    return {'catchers': out, 'team_call': team_call, 'model': model, 'n_rows': len(all_rows)}
