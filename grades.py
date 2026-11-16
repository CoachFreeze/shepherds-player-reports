"""Stuff+ and Location+.

Stuff+ grades each pitch on its physical shape alone (velocity, movement, how it plays off his fastball, and how the movement compares
with what hitters expect from his arm slot), so it works from bullpens. The yardstick is the MLB pitch-arsenal reference already in the
app (data/mlb_arsenals_*.csv): 100 = the average MLB pitch of that type, and every 10 points is one standard deviation among MLB
pitchers. The reference holds shapes, not results, so the weights below are set by hand from how each trait is known to matter, not
fitted to outcomes: treat Stuff+ as an estimate.

Location+ grades where his pitches end up. Every pitch location is worth some number of runs depending on the count; those values are
measured from all the tracked pitches stored in the app (pooled, demo data left out) and refit as data comes in. A pitcher's Location+
is how his average location value compares with the other pitchers in the app: 100 = average here, every 10 points one standard
deviation. It is relative to the app's pitchers, not to MLB."""
import math

import arsenal_comps as ac
import cache
import extract as e

# ---- Stuff+ : weights per pitch type on standardized traits (each trait is in MLB standard deviations, + = better)
#   velo      raw velocity for the pitch type
#   ride      induced vertical break above what his arm slot predicts (carry)
#   sink      induced vertical break below what his arm slot predicts
#   run       arm-side movement beyond what his arm slot predicts
#   cut/sweep glove-side movement
#   depth     drop (less induced vertical break)
#   gap       velocity taken off his fastball (changeups / splitters)
#   tight     velocity kept close to his fastball (cutters, sliders)
#   sep       movement distance from his fastball
STUFF_W = {
    'ff': {'velo': 0.55, 'ride': 0.35, 'odd_hb': 0.10},
    'si': {'velo': 0.45, 'sink': 0.30, 'run': 0.25},
    'fc': {'velo': 0.40, 'cut': 0.25, 'ride_raw': 0.15, 'tight': 0.20},
    'sl': {'velo': 0.35, 'sweep': 0.20, 'depth': 0.20, 'sep': 0.15, 'tight': 0.10},
    'st': {'sweep': 0.45, 'velo': 0.30, 'sep': 0.15, 'depth': 0.10},
    'sv': {'sweep': 0.30, 'depth': 0.30, 'velo': 0.25, 'sep': 0.15},
    'cu': {'depth': 0.40, 'velo': 0.30, 'sweep': 0.15, 'sep': 0.15},
    'ch': {'drop_sep': 0.35, 'gap': 0.25, 'run_raw': 0.25, 'velo': 0.15},
    'fs': {'drop_sep': 0.40, 'gap': 0.25, 'velo': 0.20, 'run_raw': 0.15},
}
MIN_STUFF_PITCHES = 8        # tracked pitches of a type before it gets a Stuff+
_REF = {}


def _ms(v):
    m = sum(v) / len(v)
    return m, max((sum((a - m) ** 2 for a in v) / len(v)) ** 0.5, 1e-6)


def _linfit(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs) or 1e-9
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def _traits(code, p, fb, angle, slot_fit):
    """Raw (unstandardized) trait values for one pitch; None where it can't be measured."""
    t = {'velo': p.get('velo')}
    ivb, hb = p.get('ivb'), p.get('hb')
    exp = slot_fit.get(code)
    if exp and angle is not None and ivb is not None and hb is not None:
        ei, eh = exp['ivb'][0] + exp['ivb'][1] * angle, exp['hb'][0] + exp['hb'][1] * angle
    else:
        ei = eh = None
    if ivb is not None and hb is not None:
        t['ride_raw'], t['depth'], t['run_raw'], t['cut'], t['sweep'] = ivb, -ivb, hb, -hb, -hb
        if ei is not None:
            t['ride'], t['sink'], t['run'], t['odd_hb'] = ivb - ei, ei - ivb, hb - eh, abs(hb - eh)
        if fb and fb is not p and fb.get('ivb') is not None and fb.get('hb') is not None:
            t['sep'] = math.hypot(ivb - fb['ivb'], hb - fb['hb'])
            t['drop_sep'] = fb['ivb'] - ivb
    if fb and fb is not p and fb.get('velo') and p.get('velo'):
        g = fb['velo'] - p['velo']
        t['gap'] = min(g, 12.0)                      # past ~12 mph a changeup just looks slow
        t['tight'] = -g
    return t


def _reference():
    if _REF:
        return _REF
    rows, _stats = ac.load_reference()
    slot_fit, raw = {}, {}
    for c in ac.CODES:
        pts = [(r['arm_angle'], r['pitches'][c]) for r in rows if c in r['pitches'] and r.get('arm_angle') is not None
               and r['pitches'][c].get('ivb') is not None and r['pitches'][c].get('hb') is not None]
        if len(pts) > 30:
            xs = [a for a, _ in pts]
            slot_fit[c] = {'ivb': _linfit(xs, [p['ivb'] for _, p in pts]), 'hb': _linfit(xs, [p['hb'] for _, p in pts])}
    for r in rows:
        fb = r['pitches'].get('ff') or r['pitches'].get('si')
        for c, p in r['pitches'].items():
            raw.setdefault(c, []).append(_traits(c, p, fb, r.get('arm_angle'), slot_fit))
    norm, comp = {}, {}
    for c, lst in raw.items():
        norm[c] = {}
        for k in STUFF_W.get(c, {}):
            v = [t[k] for t in lst if t.get(k) is not None]
            if len(v) > 20:
                norm[c][k] = _ms(v)
        scores = [s for s in (_composite(c, t, norm) for t in lst) if s is not None]
        if len(scores) > 20:
            comp[c] = _ms(scores)
    _REF.update(slot_fit=slot_fit, norm=norm, comp=comp)
    return _REF


def _composite(code, traits, norm):
    w = STUFF_W.get(code)
    if not w:
        return None
    tot = wsum = 0.0
    for k, wt in w.items():
        if traits.get(k) is None or k not in norm.get(code, {}):
            continue
        m, sd = norm[code][k]
        tot += wt * max(-4.0, min(4.0, (traits[k] - m) / sd))
        wsum += wt
    if wsum < 0.6 or traits.get('velo') is None:      # needs velocity and most of its traits
        return None
    return tot / wsum


def stuff(arsenal, throws='R', arm_angle=None):
    """arsenal: the same list the comps use ([{'type','pct','velo','hb','ivb', 'n'?}]). Returns
    {'by_type': {label: Stuff+}, 'overall': usage-weighted Stuff+ or None}."""
    ref = _reference()
    ours = ac._normalise(arsenal, throws)
    counts = {p.get('type'): p.get('n') for p in arsenal}
    fb = ours.get('ff') or ours.get('si')
    out, tot, wsum = {}, 0.0, 0.0
    for code, p in ours.items():
        n = counts.get(p['label'])
        if n is not None and n < MIN_STUFF_PITCHES:
            continue
        s = _composite(code, _traits(code, p, fb, arm_angle, ref['slot_fit']), ref['norm'])
        if s is None or code not in ref['comp']:
            continue
        m, sd = ref['comp'][code]
        val = max(20.0, min(180.0, 100 + 10 * (s - m) / sd))
        out[p['label']] = round(val)
        tot += val * (p.get('pct') or 0)
        wsum += p.get('pct') or 0
    return {'by_type': out, 'overall': round(tot / wsum) if wsum >= 50 else None}


# ---- Location+
MIN_LOC_PITCHES = 60         # located pitches before a pitcher gets a Location+
MIN_LOC_TYPE = 25            # ... and before one pitch type does
SHRINK_LOC = 60              # pitches' worth of pull toward the average
RV_BALL, RV_STRIKE, RV_WALK, RV_K = 0.055, -0.065, 0.30, -0.27     # run value to the hitter of a ball / strike, by standard linear weights
REGIONS = ('heart', 'edge_in', 'edge_out', 'chase', 'waste')
COUNTS = ('first', 'ahead', 'even', 'behind', 'two')


def region(x, z):
    import hitting as H
    r = H.region(x, z)
    if r == 'shadow':
        return 'edge_in' if (abs(x) <= H.ZX and H.ZB <= z <= H.ZT) else 'edge_out'
    return r


def count_class(balls, strikes):
    """From the pitcher's side. None when the file has no count (bullpens)."""
    try:
        b, s = int(balls), int(strikes)
    except (TypeError, ValueError):
        return None
    if s == 2:
        return 'two'
    if b == 0 and s == 0:
        return 'first'
    return 'ahead' if s > b else ('behind' if b > s else 'even')


def _pitch_rv(r, env):
    """Runs to the hitter from what happened on this pitch (results don't need tagging: contact is valued by exit velocity / launch angle)."""
    import advanced
    oc = e._outcome(r)
    b, s = r.get('Balls'), r.get('Strikes')
    if oc == 'ball':
        return RV_WALK if b == '3' else RV_BALL
    if oc == 'hbp':
        return RV_WALK
    if oc in ('cs', 'whiff'):
        return RV_K if s == '2' else RV_STRIKE
    if oc == 'foul':
        return 0.0 if s == '2' else RV_STRIKE
    if oc == 'inplay':
        v = advanced.batted_value(e._fnum(r.get('ExitSpeed')), e._fnum(r.get('Angle')))
        return None if v is None else (v - env['lg_woba']) / 1.2
    return None


def _loc_xy(r):
    x, z = e._fnum(r.get('PlateLocSide')), e._fnum(r.get('PlateLocHeight'))
    return (x, z) if x is not None and z is not None else None


@cache.memo
def location_model():
    """{'cells': {(region, count class or None): runs}, 'pop': (mean, sd) of pitcher scores, 'n': pitches used}."""
    import runenv
    env = runenv.environment()
    sums, by_pitcher = {}, {}
    rows = runenv._rows()
    for _d, r in rows:
        xy = _loc_xy(r)
        if not xy:
            continue
        rv = _pitch_rv(r, env)
        if rv is None:
            continue
        reg = region(*xy)
        for k in ((reg, count_class(r.get('Balls'), r.get('Strikes'))), (reg, None)):
            a = sums.setdefault(k, [0.0, 0])
            a[0] += rv
            a[1] += 1
    cells = {}
    for reg in REGIONS:
        base_s, base_n = sums.get((reg, None), (0.0, 0))
        base = base_s / base_n if base_n else 0.0
        cells[(reg, None)] = base
        for cc in COUNTS:
            s, n = sums.get((reg, cc), (0.0, 0))
            cells[(reg, cc)] = (s + 40 * base) / (n + 40)          # a thin count cell leans on the region's overall value
    for _d, r in rows:                                             # the app's pitchers, to set the scale
        xy = _loc_xy(r)
        if xy and r.get('Pitcher'):
            a = by_pitcher.setdefault(r['Pitcher'], [0.0, 0])
            a[0] += cells[(region(*xy), count_class(r.get('Balls'), r.get('Strikes')))]
            a[1] += 1
    allv = sum(s for s, _ in by_pitcher.values()) / max(1, sum(n for _, n in by_pitcher.values()))
    scores = [(s + SHRINK_LOC * allv) / (n + SHRINK_LOC) for s, n in by_pitcher.values() if n >= MIN_LOC_PITCHES]
    pop = _ms(scores) if len(scores) >= 8 else None
    return {'cells': cells, 'pop': pop, 'mean': allv, 'n': sum(n for _, n in by_pitcher.values()), 'pitchers': len(scores)}


def location(rows, type_of=None):
    """rows: raw pitch rows for one pitcher. type_of(row) -> pitch label for the per-type split.
    Returns {'overall': Location+ or None, 'n', 'by_type': {label: Location+}}."""
    m = location_model()
    if not m['pop']:
        return {'overall': None, 'n': 0, 'by_type': {}}
    mean, sd = m['pop']

    def grade(vals, minimum):
        if len(vals) < minimum:
            return None
        sc = (sum(vals) + SHRINK_LOC * m['mean']) / (len(vals) + SHRINK_LOC)
        return round(max(20.0, min(180.0, 100 - 10 * (sc - mean) / sd)))        # fewer runs to the hitter = better

    allv, by = [], {}
    for r in rows:
        xy = _loc_xy(r)
        if not xy:
            continue
        v = m['cells'][(region(*xy), count_class(r.get('Balls'), r.get('Strikes')))]
        allv.append(v)
        if type_of:
            by.setdefault(type_of(r), []).append(v)
    return {'overall': grade(allv, MIN_LOC_PITCHES), 'n': len(allv),
            'by_type': {k: g for k, g in ((k, grade(v, MIN_LOC_TYPE)) for k, v in by.items() if k) if g is not None}}
