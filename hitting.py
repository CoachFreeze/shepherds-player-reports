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
import headshots
import github_sync
import field_art
import outings as outings_mod
import roster as roster_mod
import savant_components as sc
import store
import batted
import cache

# ---------------------------------------------------------------- 1. adapters
_HIT_TYPES = {'GroundBall': 'GB', 'LineDrive': 'LD', 'FlyBall': 'FB', 'Popup': 'PU', 'Bunt': 'BUNT'}


def _norm_trackman(r):
    side = {'Right': 'R', 'Left': 'L'}.get(r.get('BatterSide'))
    return {
        'batter': (r.get('Batter') or '').strip(), 'side': side, 'date': (r.get('Date') or '')[:10],
        'pitcher': r.get('Pitcher'), 'p_throws': {'Right': 'R', 'Left': 'L', 'R': 'R', 'L': 'L'}.get(r.get('PitcherThrows') or r.get('Pitcher Throws')), 'pitch_type': r.get('TaggedPitchType'), 'speed': e._fnum(r.get('RelSpeed')),
        'x': e._fnum(r.get('PlateLocSide')), 'z': e._fnum(r.get('PlateLocHeight')),
        'outcome': e._outcome(r),
        'ev': e._fnum(r.get('ExitSpeed')), 'la': e._fnum(r.get('Angle')),
        'bat_speed': e._fnum(r.get('BatSpeed')), 'smash': e._fnum(r.get('SmashFactor')), 'squared': e._fnum(r.get('SquaredUp')), 'pot_ev': e._fnum(r.get('PotExitSpeed')),
        'direction': e._fnum(r.get('Direction')), 'distance': e._fnum(r.get('Distance')),
        'hit_type': _HIT_TYPES.get(r.get('HitType')),
        'balls': r.get('Balls'), 'strikes': r.get('Strikes'), 'src': 'trackman',
        'hit': bool(e._tags(r) & e._HIT_TAGS), 'has_result': any(t.startswith('PR_') for t in e._tags(r)),
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


_HARD = {'Fastball', 'FourSeamFastBall', 'Four-Seam', 'Four-Seam Fastball', 'Sinker', 'Cutter'}


def pitch_class(p):
    """'hard' (fastball family), 'soft' (breaking ball / off-speed), or None when the pitch type is unknown."""
    t = p.get('pitch_type')
    if not t or t in ('Undefined', 'Unknown', 'Other'):
        return None
    return 'hard' if t in _HARD else 'soft'


def count_ctx(p):
    """(balls, strikes) as ints, or None."""
    try:
        return int(p['balls']), int(p['strikes'])
    except (TypeError, ValueError):
        return None


def judge(p):
    """Returns (region, swung, verdict, weight, why) or None if the pitch can't be judged.
    verdict is good|bad|neutral and weight says how much the decision counts, because the same swing or take means
    different things in different counts and against different pitches:
      * taking a heart pitch is bad, and worse for a fastball in a hitter's count (balls > strikes) or with two strikes,
        except a fastball on 3-0, which is never held against him (taking is the right play there);
      * taking a breaking ball / off-speed pitch in the heart early in the count is not held against him (0-0 not at all,
        other early counts at half weight), unless he has two strikes;
      * swinging at a pitch off the zone is bad, a little worse in a hitter's count, and forgiven by half when it is
        close (chase zone) and he has two strikes;
      * taking a pitch off the zone is good, and counts extra with two strikes;
      * swinging at a borderline pitch with two strikes is protecting the plate, a small plus."""
    o = p['outcome']
    reg = region(p['x'], p['z'])
    if reg is None or (o not in SWING and o not in TAKE):
        return None
    swung = o in SWING
    cc = count_ctx(p)
    b, st = cc if cc else (None, None)
    hitters = cc is not None and b > st
    two = st == 2
    early = cc is not None and (b + st) <= 2 and st < 2
    cls = pitch_class(p)
    v, w, why = 'neutral', 0.0, None
    if reg == 'shadow':
        if swung and two:
            v, w, why = 'good', 0.5, 'Protecting the plate with two strikes'
    elif reg == 'heart':
        if swung:
            v, w = 'good', 1.0
        elif cls == 'soft' and early:
            if b + st == 0:
                v, w, why = 'neutral', 0.0, 'Took an off-speed or breaking pitch on 0-0 (not held against him)'
            else:
                v, w, why = 'bad', 0.5, 'Early-count take of an off-speed or breaking pitch (half weight)'
        elif cls == 'hard' and cc == (3, 0):
            v, w, why = 'neutral', 0.0, 'Took a fastball on 3-0 (not held against him)'
        elif cls == 'hard' and hitters:
            v, w, why = 'bad', 2.0, "Took a fastball in the heart in a hitter's count (counts double)"
        elif two:
            v, w, why = 'bad', 1.5, 'Took a hittable pitch with two strikes (counts extra)'
        else:
            v, w = 'bad', 1.0
    else:
        if swung:
            if two and reg == 'chase':
                v, w, why = 'bad', 0.5, 'Chased a close pitch with two strikes (half weight)'
            elif hitters:
                v, w, why = 'bad', 1.25, "Chased in a hitter's count (counts extra)"
            else:
                v, w = 'bad', 1.0
        else:
            v, w = 'good', (1.25 if two else 1.0)
            if two:
                why = 'Laid off a bad pitch with two strikes (counts extra)'
    return reg, swung, v, w, why


def grade(score):
    if score is None:
        return None
    return 'Elite' if score >= 85 else 'Strong' if score >= 75 else 'Solid' if score >= 65 else 'Developing' if score >= 55 else 'Needs work'


_LETTERS = ((93, 'A+'), (88, 'A'), (85, 'A-'), (80, 'B+'), (77, 'B'), (75, 'B-'), (71, 'C+'), (68, 'C'), (65, 'C-'), (61, 'D+'), (58, 'D'), (55, 'D-'))


def letter_grade(score):
    """0-100 -> A+ ... F. The minus grades start exactly where the overall labels do: A- 85 (Elite), B- 75 (Strong), C- 65 (Solid), D- 55 (Developing)."""
    if score is None:
        return None
    for cut, g in _LETTERS:
        if score >= cut:
            return g
    return 'F'


# --------------------------------------------------------------------- xBA
# Hit probability by exit velocity (columns) and launch angle (rows). xba_table.json (fitted to MLB batted balls)
# is used when present; the small hand-made table below is only a fallback. Refit on your own tracked outcomes
# once there is enough data.
_XBA_EV = [50, 60, 70, 80, 90, 100, 110]
_XBA_LA = [-30, -10, 0, 10, 16, 22, 28, 34, 40, 50, 60]
_XBA_TBL = [
    [.03, .04, .05, .06, .08, .10, .12],
    [.08, .10, .13, .17, .24, .32, .38],
    [.12, .15, .20, .26, .34, .45, .52],
    [.18, .24, .33, .45, .60, .72, .78],
    [.28, .38, .52, .68, .80, .86, .88],
    [.25, .35, .48, .62, .72, .80, .85],
    [.08, .15, .25, .38, .52, .68, .85],
    [.03, .06, .10, .17, .30, .55, .82],
    [.02, .03, .05, .09, .17, .40, .70],
    [.01, .02, .03, .05, .08, .15, .30],
    [.01, .01, .02, .02, .03, .05, .08],
]


def _interp_idx(v, nodes):
    v = max(nodes[0], min(nodes[-1], v))
    for i in range(len(nodes) - 1):
        if v <= nodes[i + 1]:
            return i, (v - nodes[i]) / (nodes[i + 1] - nodes[i])
    return len(nodes) - 2, 1.0


def _load_table():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xba_table.json')) as f:
            j = json.load(f)
        return j['ev'], j['la'], j['p']
    except Exception:
        return _XBA_EV, _XBA_LA, _XBA_TBL


_EVN, _LAN, _TBL = _load_table()


def hit_prob(ev, la):
    """Probability that a ball hit at this exit velocity and launch angle is a hit (0-1). No fielders, parks or sprint speed."""
    if ev is None or la is None:
        return None
    i, fi = _interp_idx(la, _LAN)
    j, fj = _interp_idx(ev, _EVN)
    t = _TBL
    top = t[i][j] + (t[i][j + 1] - t[i][j]) * fj
    bot = t[i + 1][j] + (t[i + 1][j + 1] - t[i + 1][j]) * fj
    return top + (bot - top) * fi


def xba(pitches):
    """Expected batting average. At-bats = tracked balls in play (bunts excluded) + strikeouts; walks and HBP are not
    at-bats. Expected hits = sum of hit probabilities. Also returns the real BA when the outcome tags are there."""
    bip = [p for p in pitches if p['outcome'] == 'inplay' and p['hit_type'] != 'BUNT']
    scored = [p for p in bip if hit_prob(p['ev'], p['la']) is not None]
    ks = sum(1 for p in pitches if p['strikes'] == '2' and p['outcome'] in ('whiff', 'cs'))
    ab = len(scored) + ks
    if not ab:
        return {'ab': 0, 'xba': None, 'ba': None, 'xh': 0, 'k': ks}
    xh = sum(hit_prob(p['ev'], p['la']) for p in scored)
    tagged = [p for p in scored if p['has_result']]
    ba = None
    if scored and len(tagged) == len(scored):
        ba = sum(1 for p in scored if p['hit']) / ab
    return {'ab': ab, 'xba': xh / ab, 'ba': ba, 'xh': round(xh, 1), 'k': ks}


# ------------------------------------------------------------------ 3. stats
def _pct(a, b, d=1):
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
    bsv = [p['bat_speed'] for p in pitches if p.get('bat_speed')]          # bat tracking (Full Swing): every swing, contact or not
    sqv = [p['squared'] for p in bbs if p.get('squared') is not None]
    smv = [p['smash'] for p in bbs if p.get('smash')]
    gapv = [p['pot_ev'] - p['ev'] for p in bbs if p.get('pot_ev') and p['ev']]
    hit_types = [p['hit_type'] for p in bbs if p['hit_type']]
    mix = [(p['ev'], p['la']) for p in bbs if p['la'] is not None and p['hit_type'] != 'BUNT']      # Statcast-style: type and barrel from launch angle
    mix_b = [batted.bucket(la) for _, la in mix]
    barrels = sum(1 for ev, la in mix if batted.is_barrel(ev, la))
    zones = [spray_zone(p) for p in bbs if spray_zone(p)]
    xb = xba(pitches)

    def wscore(items):
        """Weighted share of good decisions among items = [(p, j)]; (score or None, number of pitches that counted)."""
        g = sum(j[3] for _, j in items if j[2] == 'good')
        t = sum(j[3] for _, j in items if j[2] in ('good', 'bad'))
        n_ = sum(1 for _, j in items if j[2] in ('good', 'bad'))
        return (round(100 * g / t) if t else None), n_

    disc, disc_n = wscore([(p, j) for p, j in judged if j[0] in ('chase', 'waste')])
    hit, hit_n = wscore([(p, j) for p, j in judged if j[0] == 'heart'])
    dec_w, dec_n = wscore(judged)
    # damage: expected average on balls in play off hittable pitches (heart and shadow)
    hp = [hit_prob(p['ev'], p['la']) for p, j in judged
          if p['outcome'] == 'inplay' and j[0] in ('heart', 'shadow') and p['ev'] is not None and p['la'] is not None and p['hit_type'] != 'BUNT']
    hp = [v for v in hp if v is not None]
    xbacon = sum(hp) / len(hp) if hp else None
    dmg = max(0, min(100, round(68 + (xbacon - 0.33) * 250))) if xbacon is not None and len(hp) >= 3 else None
    parts = [(0.35, disc if disc_n >= 5 else None), (0.35, hit if hit_n >= 5 else None), (0.30, dmg)]
    live = [(w_, v_) for w_, v_ in parts if v_ is not None]
    score = round(sum(w_ * v_ for w_, v_ in live) / sum(w_ for w_, _ in live)) if len(live) >= 2 else dec_w

    def split(label, pred):
        sc, k = wscore([(p, j) for p, j in judged if pred(p)])
        return {'label': label, 'score': sc if k >= 8 else None, 'n': k}

    def ctx(p):
        cc = count_ctx(p)
        return None if cc is None else ('hit' if cc[0] > cc[1] else 'pit' if (cc[1] > cc[0] or cc[1] == 2) else 'even')
    splits = [split('Vs fastballs', lambda p: pitch_class(p) == 'hard'), split('Vs breaking / off-speed', lambda p: pitch_class(p) == 'soft'),
              split("Hitter's counts", lambda p: ctx(p) == 'hit'), split('Even counts', lambda p: ctx(p) == 'even'),
              split("Pitcher's counts / two strikes", lambda p: ctx(p) == 'pit')]
    fb_hc = sum(1 for p, j in judged if j[0] == 'heart' and not j[1] and pitch_class(p) == 'hard' and count_ctx(p) and count_ctx(p)[0] > count_ctx(p)[1] and count_ctx(p) != (3, 0))
    excused = sum(1 for p, j in judged if j[2] == 'neutral' and j[4] and j[0] == 'heart')
    return {
        'disc': disc if disc_n >= 5 else None, 'disc_n': disc_n, 'hit': hit if hit_n >= 5 else None, 'hit_n': hit_n,
        'disc_g': letter_grade(disc if disc_n >= 5 else None), 'hit_g': letter_grade(hit if hit_n >= 5 else None), 'dmg_g': letter_grade(dmg),
        'dmg': dmg, 'dmg_n': len(hp), 'xbacon': xbacon, 'splits': splits, 'fb_hc_takes': fb_hc, 'excused_takes': excused,
        'xba': xb['xba'], 'ba': xb['ba'], 'ab': xb['ab'], 'xh': xb['xh'], 'ks': xb['k'],
        'pitches': n, 'pa': pa, 'decisions': decided,
        'score': score, 'grade': grade(score) if decided >= 15 else None,
        'good': good, 'bad': bad, 'neutral': cnt(verdict='neutral'),
        'swing_pct': _pct(len(swings), len(judged)),
        'zone_swing_pct': _pct(zone_sw, zone_n), 'chase_pct': _pct(chase_sw, chase_n),
        'heart_swing_pct': _pct(heart_sw, heart_n),
        'heart_takes': heart_n - heart_sw, 'chases': chase_sw,
        'zone_contact_pct': _pct(zone_contact, len(zone_swings)), 'whiff_pct': _pct(whiffs, len(swings)),
        'bip': len(bbs), 'swings': len(swings),
        'avg_ev': round(sum(evs) / len(evs), 1) if evs else None,
        'max_ev': round(max(evs), 1) if evs else None,
        'ev90': round(_quantile(evs, 0.9), 1) if len(evs) >= 5 else None,
        'hard_hit_pct': _pct(sum(1 for v in evs if v >= 95), len(evs)),
        'avg_la': round(sum(las) / len(las), 1) if las else None,
        'sweet_spot_pct': _pct(sum(1 for v in las if 8 <= v <= 32), len(las)),
        'gb_pct': _pct(mix_b.count('GB'), len(mix_b)), 'ld_pct': _pct(mix_b.count('LD'), len(mix_b)),
        'fb_pct': _pct(mix_b.count('FB'), len(mix_b)), 'pu_pct': _pct(mix_b.count('PU'), len(mix_b)),
        'brl_pct': _pct(barrels, len(mix)), 'brl': barrels, 'mix_n': len(mix),
        'pull_pct': _pct(zones.count('pull'), len(zones)), 'center_pct': _pct(zones.count('center'), len(zones)),
        'oppo_pct': _pct(zones.count('oppo'), len(zones)),
        'bs_n': len(bsv), 'avg_bs': round(sum(bsv) / len(bsv), 1) if bsv else None, 'max_bs': round(max(bsv), 1) if bsv else None,
        'sq_pct': round(100 * sum(sqv) / len(sqv), 1) if sqv else None, 'avg_smash': round(sum(smv) / len(smv), 2) if smv else None,
        'ev_gap': round(sum(gapv) / len(gapv), 1) if gapv else None,
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
    if s.get('fb_hc_takes', 0) >= 2:
        out.append(f"Took {s['fb_hc_takes']} fastballs in the heart in hitter's counts, the pitch he should be hunting there.")
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
        reg, swung, v = j[0], j[1], j[2]
        col = {'good': _GOOD, 'bad': _BAD, 'neutral': _NEUT}[v]
        cx, cy = X(max(xr[0], min(xr[1], p['x']))), Y(max(zr[0], min(zr[1], p['z'])))
        cc = count_ctx(p)
        tip = f"{(p['pitch_type'] or 'Pitch')} · {'Swing' if swung else 'Take'} · {p['outcome']}" + (f" · count {cc[0]}-{cc[1]}" if cc else '') + (f" · {j[4]}" if j[4] else '')
        if swung:
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.2" fill="{col}" fill-opacity=".88" stroke="#fff" stroke-width="1"><title>{tip}</title></circle>')
        else:
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.6" fill="#fff" fill-opacity=".7" stroke="{col}" stroke-width="2"><title>{tip}</title></circle>')
    svg.append(f'<polygon points="{X(-.35):.1f},{h-8} {X(.35):.1f},{h-8} {X(.35):.1f},{h-13} {X(0):.1f},{h-17} {X(-.35):.1f},{h-13}" fill="#fff" stroke="#9aa5ab"/>')
    svg.append('</svg>')
    return ''.join(svg)


def team_decision_chart_svg(items, width=760, height=840, side=None, dot=1.0):
    """Big catcher's-view plate for a whole team. items = [(player name, pitch)]. Same colours and zone as the single-hitter
    chart (filled = swing, ring = take; green good, red bad, grey neutral). Each dot carries data-* for the hover card."""
    xr, zr = (-2.7, 2.7), (0.4, 4.6)
    k = min(width / (xr[1] - xr[0]), height / (zr[1] - zr[0]))
    ox = (width - k * (xr[1] - xr[0])) / 2

    def X(v):
        return ox + (v - xr[0]) * k

    def Y(v):
        return (zr[1] - v) * k

    h = int(Y(zr[0]))
    svg = [f'<svg id="tdc" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:auto;" '
           f'font-family="Barlow,Arial,sans-serif"><rect width="{width}" height="{h}" fill="#f4f8fa"/>']
    if side in ('L', 'R'):
        svg.append('<g opacity=".4">' + sc._batter_outline_svg(X(1.68 if side == 'L' else -1.68), Y(0.0), k, side == 'L') + '</g>')
    svg.append(f'<rect x="{X(-ZX-CHASE_OUT):.1f}" y="{Y(ZT+CHASE_OUT):.1f}" width="{k*(2*ZX+2*CHASE_OUT):.1f}" height="{k*(ZT-ZB+2*CHASE_OUT):.1f}" rx="18" fill="none" stroke="#c9d3d8" stroke-dasharray="4 5"/>')
    svg.append(f'<rect x="{X(-ZX-SHADOW_OUT):.1f}" y="{Y(ZT+SHADOW_OUT):.1f}" width="{k*(2*ZX+2*SHADOW_OUT):.1f}" height="{k*(ZT-ZB+2*SHADOW_OUT):.1f}" rx="10" fill="#e8eef1" fill-opacity=".6"/>')
    svg.append(f'<rect x="{X(-ZX):.1f}" y="{Y(ZT):.1f}" width="{k*2*ZX:.1f}" height="{k*(ZT-ZB):.1f}" fill="#fff" stroke="#5c6b74" stroke-width="2"/>')
    svg.append(f'<rect x="{X(-HEART_X):.1f}" y="{Y(HEART_T):.1f}" width="{k*2*HEART_X:.1f}" height="{k*(HEART_T-HEART_B):.1f}" fill="#f1f7f4" stroke="#b9cfc5" stroke-dasharray="5 4"/>')
    from html import escape
    n = 0
    for name, p in items:
        j = judge(p)
        if not j:
            continue
        n += 1
        reg, swung, v = j[0], j[1], j[2]
        col = {'good': _GOOD, 'bad': _BAD, 'neutral': _NEUT}[v]
        cx, cy = X(max(xr[0], min(xr[1], p['x']))), Y(max(zr[0], min(zr[1], p['z'])))
        cc = count_ctx(p)
        pt = (p['pitch_type'] or 'Pitch') + (f" {p['speed']:.0f} mph" if p.get('speed') else '')
        d = (f'class="dot" data-n="{escape(name)}" data-c="{f"{cc[0]}-{cc[1]}" if cc else "-"}" data-p="{escape(pt)}" '
             f'data-a="{"Swing" if swung else "Take"}" data-o="{escape(str(p["outcome"]))}" data-v="{v}" data-w="{why_attr(j)}"')
        if swung:
            svg.append(f'<circle {d} cx="{cx:.1f}" cy="{cy:.1f}" r="{8*dot:.1f}" fill="{col}" fill-opacity=".85" stroke="#fff" stroke-width="{1.5*max(dot, .7):.1f}"/>')
        else:
            svg.append(f'<circle {d} cx="{cx:.1f}" cy="{cy:.1f}" r="{7*dot:.1f}" fill="#fff" fill-opacity=".75" stroke="{col}" stroke-width="{2.5*max(dot, .7):.1f}"/>')
    svg.append(f'<polygon points="{X(-.7):.1f},{h-14} {X(.7):.1f},{h-14} {X(.7):.1f},{h-24} {X(0):.1f},{h-32} {X(-.7):.1f},{h-24}" fill="#fff" stroke="#9aa5ab" stroke-width="1.5"/>')
    svg.append('</svg>')
    return ''.join(svg), n


def why_attr(j):
    from html import escape
    return escape(j[4] or '')


def zone_ev_data(pitches):
    """Balls in play with a plate location, drawn as a smooth Savant-style exit-velocity map: the average exit velocity of nearby balls in play,
    blue (soft) to red (hard), one drawing per pitch type so the filter buttons switch instantly. Balls hit off pitches up to a foot outside the zone count."""
    bb = [p for p in pitches if p['outcome'] == 'inplay' and p['ev'] is not None and p['x'] is not None and p['z'] is not None]
    pts = [{'x': round(p['x'], 3), 'z': round(p['z'], 3), 'ev': round(p['ev'], 1), 't': p['pitch_type'] or 'Unknown'} for p in bb]
    RING = 1.0     # feet around the zone that still count
    near = [q for q in pts if abs(q['x']) <= ZX + RING and ZB - RING <= q['z'] <= ZT + RING]
    types = sorted({q['t'] for q in near}, key=lambda t: -sum(1 for q in near if q['t'] == t))
    X0, X1, Z0, Z1, W = -2.9, 2.9, -0.5, 4.9, 400
    k = W / (X1 - X0)
    H = round((Z1 - Z0) * k)
    X = lambda v: (v - X0) * k
    Y = lambda v: (Z1 - v) * k
    FLOOR, EV_LO, EV_HI = 60.0, 70.0, 100.0
    levels = [EV_LO - 2 + n * 3 for n in range(14)]                      # 63 .. 102
    colors = [sc._lerp_stops(sc.EV_STOPS, (L - EV_LO) / (EV_HI - EV_LO)) for L in levels]

    def view(rows):
        if not rows:
            return ''
        xs, zs, dens, num = sc.smooth_field([(q['x'], q['z'], q['ev']) for q in rows], X0, X1, Z0, Z1, 0.08, 0.38)
        F = []
        for j in range(len(zs)):
            row = []
            for i in range(len(xs)):
                d = dens[j][i]
                sup = min(1.0, d / 0.9)                                    # fades out where there are no balls nearby
                row.append(FLOOR + ((num[j][i] / d if d > 1e-9 else FLOOR) - FLOOR) * sup)
            F.append(row)
        for j in range(len(F)):
            F[j][0] = F[j][-1] = FLOOR
        F[0] = [FLOOR] * len(F[0])
        F[-1] = [FLOOR] * len(F[0])
        return sc.contour_layers(F, xs, zs, levels, colors, X, Y)
    zl, zr, zt, zb = X(-ZX), X(ZX), Y(ZT), Y(ZB)
    parts = [f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for name in ['All'] + types:
        rows = near if name == 'All' else [q for q in near if q['t'] == name]
        parts.append(f'<g class="zv" data-view="{name}" opacity=".7" style="display:{"block" if name == "All" else "none"}">{view(rows)}</g>')
    for m in (1, 2):                                   # subtle 3 x 3 inside the zone
        parts.append(f'<line x1="{zl + (zr - zl) * m / 3:.1f}" y1="{zt:.1f}" x2="{zl + (zr - zl) * m / 3:.1f}" y2="{zb:.1f}" stroke="#22303a" stroke-opacity=".3" stroke-width="1"/>'
                     f'<line x1="{zl:.1f}" y1="{zt + (zb - zt) * m / 3:.1f}" x2="{zr:.1f}" y2="{zt + (zb - zt) * m / 3:.1f}" stroke="#22303a" stroke-opacity=".3" stroke-width="1"/>')
    parts.append(f'<rect x="{zl:.1f}" y="{zt:.1f}" width="{zr - zl:.1f}" height="{zb - zt:.1f}" fill="none" stroke="#22303a" stroke-width="1.8"/>')
    py0, py1, cx = Y(0.0), Y(-0.38), X(0)
    pw = zr - cx
    parts.append(f'<polygon points="{cx - pw:.1f},{py0:.1f} {cx + pw:.1f},{py0:.1f} {cx + pw:.1f},{(py0 + py1) / 2:.1f} {cx:.1f},{py1:.1f} {cx - pw:.1f},{(py0 + py1) / 2:.1f}" fill="#fff" stroke="#22303a" stroke-width="1.5"/>')
    svg = f'<svg id="zhm" viewBox="0 0 {W} {H}" style="display:block;width:100%;height:auto;" xmlns="http://www.w3.org/2000/svg">' + ''.join(parts) + '</svg>'
    counts = {'All': len(near)}
    counts.update({t: sum(1 for q in near if q['t'] == t) for t in types})
    return {'pts': near, 'types': types, 'outside': len(pts) - len(near), 'svg': svg, 'counts': counts,
            'geo': {'x0': X0, 'z1': Z1, 'k': k}}


def spray_html(pitches, width=400, height=352, style='classic'):
    pts = []
    for p in pitches:
        if p['outcome'] == 'inplay' and p['direction'] is not None and p['distance'] is not None:
            hp = hit_prob(p['ev'], p['la'])
            pts.append({'direction': p['direction'], 'distance': p['distance'], 'ev': p['ev'], 'la': p['la'], 'type': p['hit_type'], 'xba': None if hp is None else f'{hp:.3f}'.lstrip('0')})
    if not pts:
        return '<div class="empty">No tracked batted balls yet.</div>'
    return sc.spray_chart_interactive_html(pts, svg_fn=lambda p: field_art.make_svg(p, width=width + 20, style=style)) + sc.spray_chart_legend_html()


# ------------------------------------------------------------------ 5. store
def _slug(name):
    return store.slugify(re.sub(r'\s+', ' ', name))


SCOUT = 'scout--'


@cache.memo
def collect_scouting(program=None):
    """Opponent hitters: batters our pitchers faced in Game / Scrimmage uploads, grouped by the opponent entered at upload.
    {key: {'name','program','demo','pitches','opponent','school_override',...}}; key = scout--<program>--<opponent>--<batter>."""
    real, _ = _all_pitch_files()
    out = {}

    def add(prog, opp, p):
        key = f"{SCOUT}{prog}--{store.slugify(opp) or 'unlabeled'}--{_slug(p['batter'])}"
        h = out.get(key)
        if h is None:
            h = out[key] = {'name': p['batter'], 'program': prog, 'demo': False, 'pitches': [], 'roster': None, 'on_roster': False,
                            'opponent': opp, 'opp_slug': store.slugify(opp) or 'unlabeled', 'school_override': opp, 'scouting': True}
        h['pitches'].append(p)

    for slug, _d in real:
        if slug.startswith('opp-'):               # scouting-only uploads: both teams are opponents, so these pitchers' batters are scouted too
            od = outings_mod.load(slug, real_only=True)
            if not od.get('program') or (program and od.get('program') != program):
                continue
            for o in od['outings']:
                for r_ in o['rows']:
                    if r_.get('SessionType') != 'Scouting' or not r_.get('BatterTeamLabel'):
                        continue
                    ps = normalize([r_])
                    if ps and ps[0]['batter']:
                        add(od['program'], r_['BatterTeamLabel'], ps[0])
            continue
        pl = store.get_real_player(slug)
        if not pl or (program and pl.get('program') != program):
            continue
        prog = pl.get('program')
        _pp = ((pl.get('roles') or {}).get('pitch') or {}).get('position')
        _hand = 'R' if _pp == 'RHP' else ('L' if _pp == 'LHP' else None)
        for o in outings_mod.load(slug, real_only=True)['outings']:
            for r_ in o['rows']:
                if r_.get('SessionType') not in ('Game', 'Scrimmage'):
                    continue
                ps = normalize([r_])
                if not ps or not ps[0]['batter']:
                    continue
                p = ps[0]
                if not p.get('p_throws'):
                    p['p_throws'] = _hand
                add(prog, r_.get('Opponent') or 'Unlabeled opponent', p)
    return out


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


@cache.memo
def _collect(include_demo, include_hidden=False):
    """{batter slug: {'name', 'program', 'demo', 'pitches': [...]}}"""
    real, demo = _all_pitch_files()
    out = {}
    rosters = roster_mod.all_rosters()
    for slug, is_demo in real + (demo if include_demo else []):
        if is_demo and any(s == slug for s, _ in real):
            continue
        pl = store.get_player(slug) or {}
        is_opp = slug.startswith('opp-')
        prog = outings_mod.load(slug, real_only=True).get('program') if is_opp else None
        prog = prog or pl.get('program') or ('demo_university' if is_demo else 'shepherds')
        _pp = ((pl.get('roles') or {}).get('pitch') or {}).get('position')          # fallback for the pitcher's hand
        _hand = 'R' if _pp == 'RHP' else ('L' if _pp == 'LHP' else None)
        for o in outings_mod.load(slug)['outings']:
            for r_, p in ((r_, ps[0]) for r_ in o['rows'] for ps in [normalize([r_])] if ps):
                if not p['batter']:
                    continue
                st = r_.get('SessionType')
                if st in ('Bullpen', 'Scouting') or (st in ('Scrimmage', 'Game') and not is_opp):
                    continue          # bullpens have no hitters; our pitchers' hitters in a game are the opponent's
                if not p.get('p_throws'):
                    p['p_throws'] = _hand
                key = _slug(p['batter']) + ('--demo' if is_demo else '')
                h = out.get(key)
                if h is None:
                    hit = None if is_demo else roster_mod.find_anywhere(p['batter'], rosters)
                    h = out[key] = {'name': p['batter'], 'program': hit[0] if hit else prog, 'demo': is_demo, 'pitches': [],
                                    'roster': hit[1] if hit else None, 'on_roster': bool(hit)}
                h['pitches'].append(p)
    import cleanup                                   # hitters the coach moved to another team, or hid (opposing hitters)
    for key, ov in cleanup.hitter_overrides().items():
        h = out.get(key)
        if not h:
            continue
        h['auto_program'] = h['program']
        if ov == cleanup.HIDDEN:
            h['hidden'] = True
            if not include_hidden:
                del out[key]
        else:
            h['program'] = ov
    return out


def batter_names(include_demo=False):
    """Every batter name found in stored outings (used to match an uploaded roster)."""
    return [(h['name'], key) for key, h in _collect(include_demo).items()]


def display_name(n):
    if ',' in n:
        last, first = [x.strip() for x in n.split(',', 1)]
        return f'{first} {last}'.strip()
    return n


@cache.memo
def list_hitters(include_demo=True):
    rows = []
    pidx = _players_index()
    for key, h in _collect(include_demo).items():
        s = hitter_stats(h['pitches'])
        sides = {p['side'] for p in h['pitches'] if p['side']}
        _bs = 'S' if len(sides) > 1 else (next(iter(sides)) if sides else None)
        rows.append({'bio': _bio(key, h, pidx, _bs), 'key': key, 'name': display_name(h['name']), 'raw': h['name'], 'program': h['program'], 'demo': h['demo'], 'roster': h.get('roster'), 'on_roster': h.get('on_roster'),
                     'bats': 'S' if len(sides) > 1 else (next(iter(sides)) if sides else '?'), 's': s})
    rows.sort(key=lambda r: (r['demo'], -r['s']['pitches']))
    return rows


_PT_LABELS = {'Fastball': 'Fastball', 'FourSeamFastBall': 'Fastball', 'FourSeam': 'Fastball', 'Sinker': 'Sinker', 'TwoSeamFastBall': 'Sinker', 'Cutter': 'Cutter',
              'Slider': 'Slider', 'Sweeper': 'Sweeper', 'Curveball': 'Curveball', 'ChangeUp': 'Changeup', 'Changeup': 'Changeup', 'Splitter': 'Splitter',
              'Knuckleball': 'Knuckleball'}
_PT_ORDER = ['Fastball', 'Sinker', 'Cutter', 'Slider', 'Sweeper', 'Curveball', 'Changeup', 'Splitter', 'Knuckleball']


def pitch_type_table(ps):
    """Batted-ball quality against each pitch type he has seen (plus an all-pitches row). One row per type, same numbers as the tiles above it."""
    def row(label, sub):
        s = hitter_stats(sub)
        return {'label': label, 'seen': len(sub), 'swing_pct': s['swing_pct'], 'whiff_pct': s['whiff_pct'], 'bip': s['bip'], 'avg_ev': s['avg_ev'], 'max_ev': s['max_ev'],
                'hard_hit_pct': s['hard_hit_pct'], 'brl_pct': s['brl_pct'], 'avg_la': s['avg_la'], 'gb_pct': s['gb_pct'], 'ld_pct': s['ld_pct'],
                'fb_pct': s['fb_pct'], 'xba': s['xba'], 'ab': s['ab'], 'swings': s['swings']}
    groups = {}
    for p in ps:
        lab = _PT_LABELS.get(p.get('pitch_type') or '', None)
        if lab:
            groups.setdefault(lab, []).append(p)
    rows = [row(lab, groups[lab]) for lab in sorted(groups, key=lambda k: (-len(groups[k]), _PT_ORDER.index(k) if k in _PT_ORDER else 99))]
    return {'all': row('All pitches', ps), 'rows': rows}


# ------------------------------------------------------------------ team rank badges
# stat -> +1 when higher is better, -1 when lower is better. Stats with no clear "better" (launch angle, fly-ball share, volume counts) get no badge.
RANK_STATS = {'xba': 1, 'avg_ev': 1, 'max_ev': 1, 'ev90': 1, 'hard_hit_pct': 1, 'brl_pct': 1, 'sweet_spot_pct': 1,
              'whiff_pct': -1}
RANK_MIN_BIP, RANK_MIN_SWINGS, RANK_MIN_TEAM = 5, 10, 3


def _rank_val(stat, sub):
    """The stat's value if the slice has enough data to be ranked, else None. `sub` is a hitter_stats / pitch-row dict."""
    v = sub.get(stat)
    if v is None:
        return None
    if stat == 'whiff_pct':
        return v if (sub.get('swings') or 0) >= RANK_MIN_SWINGS else None
    return v if (sub.get('bip') or 0) >= RANK_MIN_BIP else None


@cache.memo
def team_ranks(program):
    """{(vs, section): {stat: [value of each qualifying hitter]}} for one program's hitters; section is 'all' or a pitch type label."""
    out = {}
    for key, h in _collect(True).items():
        if h['program'] != program:
            continue
        for vs in ('all', 'R', 'L'):
            ps = [p for p in h['pitches'] if p.get('p_throws') == vs] if vs != 'all' else h['pitches']
            if not ps:
                continue
            pt = pitch_type_table(ps)
            s_all = hitter_stats(ps)
            for section, sub in [('all', s_all)] + [(r['label'], r) for r in pt['rows']]:
                for stat in RANK_STATS:
                    v = _rank_val(stat, sub)
                    if v is not None:
                        out.setdefault((vs, section), {}).setdefault(stat, []).append(v)
    return out


def _badge(stat, v, vals):
    n = len(vals)
    if v is None or n < RANK_MIN_TEAM:
        return None
    d = RANK_STATS[stat]
    rank = 1 + sum(1 for x in vals if (x - v) * d > 1e-9)
    if rank <= 3:
        return {'tier': f'r{rank}', 'txt': f'#{rank}', 'title': (f'Best on the team ({n} hitters ranked)' if rank == 1 else f'#{rank} on the team ({n} hitters ranked)')}
    return None


def rank_badges(program, vs, s, pt):
    """{'bbq': {stat: badge}, 'rows': {pitch label: {stat: badge}}} for one hitter's current view (his stats `s`, pitch table `pt`)."""
    tr = team_ranks(program)
    out = {'bbq': {}, 'rows': {}}
    for stat in RANK_STATS:
        b = _badge(stat, _rank_val(stat, s), (tr.get((vs, 'all')) or {}).get(stat, []))
        if b:
            out['bbq'][stat] = b
    for r in [pt['all']] + pt['rows']:
        sec = 'all' if r is pt['all'] else r['label']
        got = {}
        for stat in RANK_STATS:
            if stat == 'pu_pct' or stat == 'ev90' or stat == 'sweet_spot_pct':
                continue                      # not shown in the pitch-type table
            b = _badge(stat, _rank_val(stat, r), (tr.get((vs, sec)) or {}).get(stat, []))
            if b:
                got[stat] = b
        out['rows'][r['label']] = got
    return out


@cache.memo
def hitter_profile(key, include_demo=True, side='all', vs='all'):
    """vs = the pitcher's hand to show ('R', 'L' or 'all'). `side` is the older switch-hitter control (batting left = vs RHP) and still works."""
    h = (collect_scouting().get(key) if key.startswith(SCOUT) else _collect(include_demo).get(key))
    if not h:
        return None
    ps_all = [dict(p) for p in h['pitches']]       # a private copy: the switch-hitter handling below edits each pitch's side
    sides = {p['side'] for p in ps_all if p['side']}
    bats_seen = 'S' if len(sides) > 1 else (next(iter(sides)) if sides else None)
    bio = _bio(key, h, _players_index(), bats_seen)
    vs = vs if vs in ('R', 'L') else 'all'
    if vs == 'all' and side in ('L', 'R') and bio['bats'] == 'S':
        vs = 'R' if side == 'L' else 'L'
    switch = None
    if bio['bats'] == 'S':
        # The data rarely says which side a switch hitter hit from, so it comes from the pitcher's hand: left-handed against righties,
        # right-handed against lefties. Pitches with no known pitcher hand stay in the all-pitchers view only.
        for p in ps_all:
            if p.get('p_throws') in ('R', 'L'):
                p['side'] = 'L' if p['p_throws'] == 'R' else 'R'
        side = {'R': 'L', 'L': 'R'}.get(vs, 'all')
        switch = {'cur': side, 'n_all': len(ps_all), 'n_l': sum(1 for p in ps_all if p.get('p_throws') == 'R'),
                  'n_r': sum(1 for p in ps_all if p.get('p_throws') == 'L')}
        switch['unknown'] = len(ps_all) - switch['n_l'] - switch['n_r']
    else:
        side = 'all'
    ps = [p for p in ps_all if p.get('p_throws') == vs] if vs in ('R', 'L') else ps_all

    def _bip(rows):
        return sum(1 for p in rows if p['outcome'] == 'inplay' and p['ev'] is not None)
    vs_counts = {'all': {'pitches': len(ps_all), 'bip': _bip(ps_all)}}
    for hand in ('R', 'L'):
        sub = [p for p in ps_all if p.get('p_throws') == hand]
        vs_counts[hand] = {'pitches': len(sub), 'bip': _bip(sub)}
    bats = side if side in ('L', 'R') else bats_seen if not switch else 'S'
    s = hitter_stats(ps)
    pt = pitch_type_table(ps)
    badges = None if (key.startswith(SCOUT) or h.get('scouting')) else rank_badges(h['program'], vs, s, pt)
    import benchmarks as bm
    prow = []
    if s['ev90'] is not None:
        prow.append({'label': 'EV90', 'pctl': bm.interpolate(s['ev90'], bm.HITTER['ev90']), 'value_display': f"{s['ev90']:.1f}"})
    if s['whiff_pct'] is not None and len([p for p in ps if p['outcome'] in SWING]) >= 10:
        prow.append({'label': 'Whiff%', 'pctl': bm.interpolate(s['whiff_pct'], bm.HITTER['whiff_pct']), 'value_display': f"{s['whiff_pct']:.1f}%"})
    return {'bio': bio, 'switch': switch, 'vs': vs, 'vs_counts': vs_counts, 'pt_table': pt, 'badges': badges, 'ps_n': len(ps), 'roster': h.get('roster'), 'pctl_html': sc.percentile_bars_html(prow) if prow else '', 'key': key, 'name': display_name(h['name']), 'program': h['program'], 'demo': h['demo'], 'bats': bats, 'opponent': h.get('opponent'), 'opp_slug': h.get('opp_slug'),
            's': s, 'notes': takeaways(s), 'dates': sorted({p['date'] for p in ps_all if p['date']}),
            'zone_ev': zone_ev_data(ps),
            'decision_svg': decision_chart_svg(ps, side=bats if bats in ('L', 'R') else None),
            'decision_svg_i': team_decision_chart_svg([(display_name(h['name']), p) for p in ps], width=420, height=470, side=bats if bats in ('L', 'R') else None, dot=.66)[0],
            'spray': spray_html(ps)}


# ------------------------------------------------------------------ hitter bios (card + profile header)
HITTER_BIOS_PATH = os.path.join(store.DATA_DIR, 'hitters.json')
_DEMO_BIOS_PATH = os.path.join(store.DEMO_DIR, 'hitters.json')


def _load_json(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_bio(key, fields):
    """Coach edits for a hitter (position, bats/throws, height, weight, class). Kept in data/hitters.json and committed like the rosters."""
    d = _load_json(HITTER_BIOS_PATH)
    e = d.setdefault(key, {})
    e.update({k: v for k, v in fields.items()})
    os.makedirs(os.path.dirname(HITTER_BIOS_PATH), exist_ok=True)
    text = json.dumps(d, separators=(',', ':'), ensure_ascii=False)
    with open(HITTER_BIOS_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    github_sync.put_file('data/hitters.json', text.encode('utf-8'))


def _bio(key, h, players_idx, bats_seen):
    """Everything the card and profile header show. Priority: coach edits > the same person's pitcher profile (two-way players share one
    headshot and bio) > the uploaded roster > what the data itself shows (batting side)."""
    ov = _load_json(HITTER_BIOS_PATH).get(key) or (_load_json(_DEMO_BIOS_PATH).get(key) if h['demo'] else None) or {}
    rost = h.get('roster') or {}
    pm = None if h.get('scouting') else (roster_mod.match_name(h['name'], [(n, s) for n, s, pg in players_idx if pg == h['program']]) if players_idx else None)
    pslug = pm[0] if pm else None
    pl = (store.get_player(pslug) or {}) if pslug else {}
    hpos = next((t for t in rost.get('positions', []) if t not in ('RHP', 'LHP')), None)
    pos = ov.get('position') or ((pl.get('roles') or {}).get('hit') or {}).get('position') or ({'UTL': 'INF', 'DH': 'INF'}.get(hpos, hpos))
    if not pos and rost.get('positions'):
        pos = rost['positions'][0]
    if not pos and pl:
        pos = ((pl.get('roles') or {}).get('pitch') or {}).get('position')      # a pitcher who also bats
    prog = h['program']
    label = store.program_label(prog)
    pr = pl.get('roster') or {}
    cy = ov.get('class_year') or pr.get('class_year') or rost.get('class_year')
    gy = ov.get('grad_year') or pl.get('grad_year')
    two_way = bool(pslug and (pl.get('roles') or {}).get('pitch'))       # a real pitcher profile exists too (not just a name match)
    return {'name': display_name(h['name']), 'school': h.get('school_override') or pl.get('school') or label, 'program': prog, 'position': pos, 'two_way': two_way,
            'bats': ov.get('bats') or rost.get('bats') or pr.get('bats') or bats_seen,
            'throws': ov.get('throws') or rost.get('throws') or pr.get('throws'),
            'height_in': ov.get('height_in') or pl.get('height_in') or rost.get('height_in'),
            'weight_lbs': ov.get('weight_lbs') or pl.get('weight_lbs') or rost.get('weight_lbs'),
            'grad_year': gy, 'class_year': cy, 'class_label': (f'Class of {gy}' if gy else (cy or None)),
            'number': ov.get('number') or rost.get('number') or pr.get('number'),
            'hometown': rost.get('hometown') or pr.get('hometown'),
            'pitcher_slug': pslug, 'photo_slug': pslug if (pslug and headshots.exists(pslug)) else (f'h_{key}' if headshots.exists(f'h_{key}') else None),
            'photo_kind': 'player' if (pslug and headshots.exists(pslug)) else 'hitter'}


def hitter_key_for(name, program, include_demo=True):
    """The hitter profile key for a pitcher (same person, same program), or None. Used for the Hitter/Pitcher switch on two-way players."""
    cands = [(display_name(h['name']), k) for k, h in _collect(include_demo).items() if h['program'] == program]
    m = roster_mod.match_name(name, cands) if cands else None
    return m[0] if m else None


def _players_index(program_agnostic=True):
    return [(b.get('name', ''), s, b.get('program') or 'shepherds') for s, b in store.list_players_view().items() if b.get('name')]

