"""
Arsenal-based MLB comps and "pitches to consider adding".

Reference data: data/mlb_arsenals_2026.csv, a Baseball Savant pitch-arsenal export (one row per
MLB pitcher: arm angle, handedness, and for each pitch type usage %, velo, spin, horizontal
break and induced vertical break).

Everything is compared in a handedness-neutral frame -- horizontal break is "arm-side positive"
(so a righty's sinker and a lefty's sinker both run +), which lets lefties and righties be
compared on pitch SHAPE rather than on which side of the plate it breaks.

  find_arsenal_comps(arsenal, throws, arm_angle)   -> closest MLB arsenals
  suggest_pitches(arsenal, throws, arm_angle, ...) -> pitches worth adding, with target shapes

arsenal = [{'type': '4-Seam'|'Sinker'|..., 'pct': usage 0-100, 'velo': mph, 'spin': rpm,
            'ivb': in, 'hb': in (Trackman sign: + = toward 1B), ...}]
"""
import csv
import math
import os

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'mlb_arsenals_2026.csv')

# report label -> csv prefix
LABEL_TO_CODE = {'4-Seam': 'ff', 'Sinker': 'si', 'Slider': 'sl', 'Sweeper': 'st', 'Cutter': 'fc',
                 'Split': 'fs', 'Curve': 'cu', 'Change': 'ch', 'Slurve': 'sv'}
CODE_TO_LABEL = {v: k for k, v in LABEL_TO_CODE.items()}
CODES = ['ff', 'si', 'fc', 'sl', 'st', 'sv', 'cu', 'ch', 'fs']

# pitches that can stand in for each other when the exact type is missing (cost added to distance)
FALLBACKS = {'ff': [('si', 0.9), ('fc', 1.4)], 'si': [('ff', 0.9)], 'fc': [('sl', 1.0), ('ff', 1.4)],
             'sl': [('st', 0.9), ('fc', 1.0), ('sv', 1.0)], 'st': [('sl', 0.9), ('sv', 0.9)],
             'sv': [('cu', 0.9), ('st', 0.9)], 'cu': [('sv', 0.9), ('sl', 1.6)],
             'ch': [('fs', 0.9)], 'fs': [('ch', 0.9)]}
MISSING_COST = 3.6
DIST_CAP = 3.6

_cache = {}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_reference(path=DATA_PATH):
    if path in _cache:
        return _cache[path]
    rows = []
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                hand = (r.get('pitch_hand') or '').strip().upper()[:1]
                if hand not in ('R', 'L'):
                    continue
                sgn = -1 if hand == 'R' else 1         # Savant break_x: righty arm-side is negative
                pitches = {}
                for c in CODES:
                    n = _f(r.get(f'n_{c}_formatted'))
                    if not n:
                        continue
                    bx, bz = _f(r.get(f'{c}_avg_break_x')), _f(r.get(f'{c}_avg_break_z_induced'))
                    if bx is None or bz is None:
                        continue
                    pitches[c] = {'pct': n, 'velo': _f(r.get(f'{c}_avg_speed')), 'spin': _f(r.get(f'{c}_avg_spin')),
                                  'hb': sgn * bx, 'ivb': bz}                  # hb: arm-side positive
                fbv = (pitches.get('ff') or pitches.get('si') or {}).get('velo')
                for p_ in pitches.values():
                    p_['gap'] = (fbv - p_['velo']) if (fbv and p_.get('velo')) else None
                name = r.get('last_name, first_name') or ''
                if ',' in name:
                    last, first = [x.strip() for x in name.split(',', 1)]
                    name = f'{first} {last}'
                rows.append({'name': name, 'id': r.get('player_id'), 'hand': hand,
                             'arm_angle': _f(r.get('arm_angle')), 'pitches': pitches})
    # per-pitch league spreads, used to standardise distances
    stats = {}
    for c in CODES:
        vals = [p['pitches'][c] for p in rows if c in p['pitches']]
        stats[c] = {}
        for k in ('velo', 'spin', 'hb', 'ivb', 'gap'):
            v = [x[k] for x in vals if x.get(k) is not None]
            if len(v) > 5:
                m = sum(v) / len(v)
                stats[c][k] = (m, max((sum((a - m) ** 2 for a in v) / len(v)) ** 0.5, 0.5))
    _cache[path] = (rows, stats)
    return _cache[path]


def _normalise(arsenal, throws):
    """Our pitches in the same frame as the reference (code, arm-side-positive hb)."""
    sgn = 1 if (throws or 'R').upper().startswith('R') else -1
    out = {}
    for p in arsenal:
        code = LABEL_TO_CODE.get(p.get('type'))
        if not code or p.get('hb') is None or p.get('ivb') is None:
            continue
        out[code] = {'pct': p.get('pct') or 0, 'velo': p.get('velo'), 'spin': p.get('spin'),
                     'hb': sgn * p['hb'], 'ivb': p['ivb'], 'label': p['type']}
    fb = out.get('ff') or out.get('si')
    for p in out.values():
        p['gap'] = (fb['velo'] - p['velo']) if (fb and fb.get('velo') and p.get('velo')) else None
    return out


# how much each feature counts. Absolute velocity does NOT count (a high-school or college arm sits well under
# MLB and we want "same shape", not "same stuff"); what does count is how far each pitch sits off his own
# fastball ('gap'), which is about pitch separation and scales with the pitcher, not the level.
W = {'hb': 1.0, 'ivb': 1.0, 'spin': 0.45, 'gap': 0.3}


def _pitch_distance(ours, theirs, code, stats):
    s = stats.get(code, {})
    tot, wsum = 0.0, 0.0
    for k, w in W.items():
        a, b = ours.get(k), theirs.get(k)
        if a is None or b is None or k not in s:
            continue
        tot += w * ((a - b) / s[k][1]) ** 2
        wsum += w
    if not wsum:
        return DIST_CAP
    return min(DIST_CAP, math.sqrt(tot / wsum * 2.0))


def _arsenal_distance(ours, mlb, stats, our_angle, mlb_angle):
    total_u = sum(p['pct'] for p in ours.values()) or 1.0
    score, matches, used = 0.0, [], set()
    for code, p in sorted(ours.items(), key=lambda kv: -kv[1]['pct']):
        cands = [(code, 0.0)] + FALLBACKS.get(code, [])
        best = None
        for c, pen in cands:
            if c in mlb['pitches']:
                d = _pitch_distance(p, mlb['pitches'][c], c, stats) + pen
                if best is None or d < best[0]:
                    best = (d, c)
        d, c = best if best else (MISSING_COST, None)
        d = min(d, MISSING_COST)
        score += p['pct'] / total_u * d
        if c:
            used.add(c)
            matches.append({'ours': p['label'], 'theirs': CODE_TO_LABEL.get(c, c), 'dist': d,
                            'mlb': mlb['pitches'][c]})
    # a mild penalty for big MLB pitches we have no answer for -- keeps a 2-pitch college arsenal
    # from matching a 6-pitch MLB arsenal just as well as a 2-3 pitch one
    extra = sum(p['pct'] for c, p in mlb['pitches'].items() if c not in used and p['pct'] >= 12)
    score += 0.012 * extra
    if our_angle is not None and mlb.get('arm_angle') is not None:
        score += 0.6 * min(abs(our_angle - mlb['arm_angle']) / 15.0, 2.5)
    return score, matches


def find_arsenal_comps(arsenal, throws='R', arm_angle=None, n=3, same_hand=True, exclude_ids=None):
    rows, stats = load_reference()
    ours = _normalise(arsenal, throws)
    if not rows or not ours:
        return []
    hand = (throws or 'R').upper()[:1]
    scored = []
    for r in rows:
        if same_hand and r['hand'] != hand:
            continue
        if exclude_ids and r['id'] in exclude_ids:
            continue
        sc, matches = _arsenal_distance(ours, r, stats, arm_angle, r.get('arm_angle'))
        scored.append((sc, r, matches))
    scored.sort(key=lambda t: t[0])
    out = []
    fb_o = ours.get('ff') or ours.get('si') or max(ours.values(), key=lambda p: p['pct'])
    for sc, r, matches in scored[:n]:
        fb_m = r['pitches'].get('ff') or r['pitches'].get('si')
        vctx = None
        if fb_o.get('velo') and fb_m and fb_m.get('velo'):
            vctx = {'ours': fb_o['velo'], 'theirs': fb_m['velo'], 'diff': fb_m['velo'] - fb_o['velo']}
        out.append({'velo_ctx': vctx, 'quality': match_quality(max(0, round(100 * math.exp(-sc / 2.2)))),
                    'name': r['name'], 'id': r['id'], 'hand': r['hand'], 'arm_angle': r['arm_angle'],
                    'score': sc, 'match': max(0, round(100 * math.exp(-sc / 2.2))),
                    'matches': matches,
                    'arsenal': {CODE_TO_LABEL[c]: p for c, p in r['pitches'].items() if p['pct'] >= 5}})
    return out


def match_quality(score):
    """Plain-language label for the 0-100 shape-match score."""
    return 'Very close shape' if score >= 70 else ('Good shape match' if score >= 55 else ('Loose match' if score >= 40 else 'Weak match'))


# ---------------------------------------------------------------- pitch suggestions
# how much a pitch leans on raw spin (0 = none, 1 = a lot); sliders/cutters are gyro-friendly, curves and sweepers are not
SPIN_NEED = {'cu': 1.0, 'st': 1.0, 'sv': 1.0, 'sl': 0.6, 'fc': 0.3}
SPIN_IS_LOW_OK = {'ch', 'fs', 'si'}                      # pitches that don't need it (or like less)
BLURB = {
    'ch': 'the best way to give righties/lefties a different look off the fastball',
    'fs': 'a bat-missing, low-spin pitch that tunnels with the fastball',
    'si': 'run and weight on the arm side to get ground balls',
    'fc': 'a hard glove-side pitch that works off the fastball',
    'sl': 'a hard, tight glove-side breaking ball',
    'st': 'big glove-side sweep that plays off the fastball\'s ride',
    'cu': 'a true over-the-top shape that changes the hitter\'s eye level',
    'sv': 'a hybrid curve/sweep with big horizontal and drop',
    'ff': 'a ride-and-carry fastball up in the zone',
}


def _spin_percentile(spin, stats, code='ff'):
    if spin is None or 'spin' not in stats.get(code, {}):
        return None
    m, s = stats[code]['spin']
    return 0.5 * (1 + math.erf((spin - m) / (s * math.sqrt(2)))) * 100


def suggest_pitches(arsenal, throws='R', arm_angle=None, k_neighbors=40, n=3):
    """Pitches the player doesn't throw that fit his slot, spin and current arsenal.
    1) Neighbours: MLB pitchers of the same handedness with the closest fastball shape and arm angle.
    2) Prevalence: how many of those neighbours throw each candidate pitch (usage-weighted).
    3) Contrast: how far the candidate's typical shape sits from what he already throws
       (a new pitch is worth most when it moves differently from the existing ones).
    4) Spin fit: whether his spin ability suits the candidate.
    Target shape = the neighbours' average version of the pitch, expressed relative to his fastball."""
    rows, stats = load_reference()
    ours = _normalise(arsenal, throws)
    if not rows or not ours:
        return []
    hand = (throws or 'R').upper()[:1]
    fb = ours.get('ff') or ours.get('si') or max(ours.values(), key=lambda p: p['pct'])
    fb_code = 'ff' if 'ff' in ours else ('si' if 'si' in ours else None)
    fb_spin_pct = _spin_percentile(fb.get('spin'), stats, fb_code or 'ff') if fb_code else None

    # 1) neighbours
    dists = []
    for r in rows:
        if r['hand'] != hand:
            continue
        ref_fb = r['pitches'].get('ff') or r['pitches'].get('si')
        if not ref_fb:
            continue
        d = ((fb['hb'] - ref_fb['hb']) / 4.0) ** 2 + ((fb['ivb'] - ref_fb['ivb']) / 3.0) ** 2
        if arm_angle is not None and r.get('arm_angle') is not None:
            d += (abs(arm_angle - r['arm_angle']) / 10.0) ** 2 * 1.6
        dists.append((math.sqrt(d), r, ref_fb))
    dists.sort(key=lambda t: t[0])
    neighbours = dists[:k_neighbors]
    if not neighbours:
        return []

    have_families = {c for c in ours}
    out = []
    for code in CODES:
        if code in have_families:
            continue
        if code == 'ff' and 'si' in have_families and 'ff' not in have_families:
            continue                                    # don't tell a sinker guy to 'add' a 4-seam shape as a pitch idea
        users = [(r, r['pitches'][code], rf) for _, r, rf in neighbours if code in r['pitches'] and r['pitches'][code]['pct'] >= 8]
        prevalence = len(users) / len(neighbours)
        if len(users) < 3:
            continue
        mean = lambda key: sum(p[key] for _, p, _ in users if p.get(key) is not None) / max(1, sum(1 for _, p, _ in users if p.get(key) is not None))
        t_hb, t_ivb, t_spin = mean('hb'), mean('ivb'), mean('spin')
        t_gap = sum((rf['velo'] - p['velo']) for _, p, rf in users if p.get('velo') and rf.get('velo')) / max(1, sum(1 for _, p, rf in users if p.get('velo') and rf.get('velo')))
        # scale the speed gap to HIS fastball (an 80 mph arm shouldn't be told to throw a change 12 mph slower)
        ref_fb_v = [rf['velo'] for _, p, rf in users if rf.get('velo')]
        vscale = 1.0
        if fb.get('velo') and ref_fb_v:
            vscale = max(0.6, min(1.0, fb['velo'] / (sum(ref_fb_v) / len(ref_fb_v))))
        t_gap_mlb = t_gap
        t_gap = t_gap * vscale
        # 3) contrast with what he already throws (inches in HB/IVB space)
        contrast = min((math.hypot(t_hb - p['hb'], t_ivb - p['ivb']) for p in ours.values()), default=20.0)
        contrast_s = min(contrast / 18.0, 1.0)
        # 4) spin fit
        spin_s = 0.5
        if fb_spin_pct is not None:
            hi = fb_spin_pct / 100.0
            spin_s = (hi * SPIN_NEED[code] + (1 - SPIN_NEED[code]) * 0.6) if code in SPIN_NEED else (1 - hi * 0.6 if code in SPIN_IS_LOW_OK else 0.5)
        # offspeed gap: if he has no offspeed pitch, change/split get a nudge; if no breaking ball, those do
        have_off = bool({'ch', 'fs'} & have_families)
        have_brk = bool({'sl', 'st', 'cu', 'sv'} & have_families)
        need = 0.0
        if code in ('ch', 'fs') and not have_off:
            need = 0.25
        if code in ('sl', 'st', 'cu', 'sv') and not have_brk:
            need = 0.25
        score = 0.40 * min(prevalence / 0.6, 1.0) + 0.30 * contrast_s + 0.15 * spin_s + need
        examples = sorted(users, key=lambda u: -u[1]['pct'])[:3]
        closest = min(ours.values(), key=lambda p: math.hypot(t_hb - p['hb'], t_ivb - p['ivb']))
        ctx = {'closest': closest['label'], 'have_off': have_off, 'have_brk': have_brk, 'fb_label': fb.get('label'),
               'fb_hb': fb['hb'], 'fb_ivb': fb['ivb'], 'fb_spin': fb.get('spin'), 'fb_spin_pct': fb_spin_pct,
               'n_have': len(ours), 'have': [p['label'] for p in ours.values()]}
        out.append({
            'ctx': ctx,
            'code': code, 'type': CODE_TO_LABEL[code], 'score': score,
            'prevalence': prevalence, 'contrast': contrast, 'spin_fit': spin_s,
            'target': {'velo_gap': t_gap, 'velo_gap_mlb': t_gap_mlb, 'hb': t_hb, 'ivb': t_ivb, 'spin': t_spin,
                       'velo': (fb['velo'] - t_gap) if fb.get('velo') else None},
            'blurb': BLURB.get(code, ''),
            'examples': [{'name': r['name'], 'id': r['id'], 'arm_angle': r['arm_angle']} for r, _, _ in examples],
            'n_users': len(users), 'n_neighbours': len(neighbours),
        })
    out.sort(key=lambda d: -d['score'])
    return out[:n]



_MECH = {  # (what it is for, who it is best against)
    'st': ('big horizontal sweep', 'same-handed hitters'),
    'sl': ('tight, hard glove-side break', 'same-handed hitters'),
    'sv': ('hybrid curve/sweep', 'same-handed hitters'),
    'cu': ('true downward break', 'both sides, and especially as an eye-level change off a ride fastball'),
    'fc': ('late glove-side cut', 'hitters on both sides, to jam them inside'),
    'ch': ('speed and arm-side fade', 'opposite-handed hitters'),
    'fs': ('late drop with little spin', 'opposite-handed hitters, and with two strikes against both sides'),
    'si': ('arm-side run and weight', 'same-handed hitters, for weak contact'),
}


def why_it_helps(s, throws='R'):
    """2-4 short, data-driven reasons this pitch would help his arsenal (list of strings, plain text)."""
    c, t, code = s['ctx'], s['target'], s['code']
    bullets = []
    brk, off = code in ('sl', 'st', 'cu', 'sv'), code in ('ch', 'fs')
    if brk and not c['have_brk']:
        bullets.append('Fills a hole: right now there is no breaking ball in the arsenal, so hitters can sit on fastball-speed pitches.')
    elif off and not c['have_off']:
        bullets.append('Fills a hole: there is no offspeed pitch yet, so hitters never have to adjust their timing.')
    elif c['n_have'] <= 2:
        bullets.append('Adds a third look to a small arsenal, which makes every pitch he already throws harder to anticipate.')
    # separation from the fastball (inches) and from his closest current pitch
    dh, dv = t['hb'] - c['fb_hb'], t['ivb'] - c['fb_ivb']
    parts = []
    if abs(dh) >= 6:
        parts.append(f'{abs(dh):.0f}\u2033 more {"glove" if dh < 0 else "arm"}-side')
    if abs(dv) >= 6:
        parts.append(f'{abs(dv):.0f}\u2033 {"less rise" if dv < 0 else "more rise"}')
    sep = (' and '.join(parts) + f' than his {c["fb_label"]}') if parts else f'a different shape from his {c["fb_label"]}'
    bullets.append(f'Gives hitters a new picture: it moves {sep}.')
    if t.get('velo_gap') and t['velo_gap'] >= 5:
        bullets.append(f'The ~{t["velo_gap"]:.0f} mph gap off the fastball adds a timing change.')
    # spin fit
    pct, fbs = c.get('fb_spin_pct'), c.get('fb_spin')
    if pct is not None and fbs:
        if code in SPIN_NEED and pct >= 60:
            bullets.append(f'His spin ({fbs:,.0f} rpm on the fastball, above-average for MLB) is the kind that helps this pitch hold its shape.')
        elif code in SPIN_NEED and pct <= 35:
            bullets.append(f'Spin is the watch-out: his fastball spin ({fbs:,.0f} rpm) is below MLB average, so the shape may come with less bite; grip and feel will matter.')
        elif code in SPIN_IS_LOW_OK and pct <= 45:
            bullets.append(f'It doesn\'t need big spin, so his fastball spin ({fbs:,.0f} rpm) is not a limiter.')
    what, who = _MECH.get(code, ('', ''))
    if who:
        bullets.append(f'Best used against {who}.')
    return bullets[:5]
