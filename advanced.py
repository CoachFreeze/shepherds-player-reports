"""Advanced run-value stats: xwOBA, FIP and xERA. They are always calculated in the background (cached), but a page shows one only
once that player's sample clears the minimums below, because these are built from the app's own batted-ball model and tagged results
rather than Statcast. Admins can preview every value with ?preview=1 on the Hitters / Pitchers pages.

Tune the minimums and constants here."""
import math

import cache
import extract as e
import hitting
import outings as outings_mod
import team

# ---- release minimums (a stat appears for a player only past these)
MIN_PA_HITTER = 100        # xwOBA, hitters
MIN_BF_PITCHER = 100       # xwOBA allowed and xERA, pitchers
MIN_IP_PITCHER = 30.0      # FIP
MIN_TAG_COVERAGE = 0.80    # FIP needs home runs: at least this share of balls in play must carry a tagged result

# ---- constants (MLB-based; no college figures built in)
W_BB, W_HBP, W_1B, W_XBH, W_HR = 0.69, 0.72, 0.89, 1.30, 2.10    # wOBA weights; W_XBH blends doubles and triples
FIP_CONST = 3.10
LG_WOBA, WOBA_SCALE, LG_RUNS_PA, PA_PER_9 = 0.315, 1.20, 0.115, 38.0


def _sig(x):
    return 1 / (1 + math.exp(-x))


def batted_value(ev, la):
    """Expected wOBA value of a ball in play at this exit velocity / launch angle (hit chance split into 1B, 2B/3B, HR)."""
    ph = hitting.hit_prob(ev, la)
    if ph is None:
        return None
    hr = min(0.9 * ph, _sig((ev - 103) / 2.5) * _sig((la - 23) / 2) * _sig((40 - la) / 2))
    xbh_share = min(0.5, 0.05 + 0.012 * max(0, ev - 80)) if 8 <= la <= 40 else 0.04
    xbh = (ph - hr) * xbh_share
    return (ph - hr - xbh) * W_1B + xbh * W_XBH + hr * W_HR


def _from_row(r):
    """A raw pitcher-side CSV row as the small dict the calculations use."""
    return {'outcome': e._outcome(r), 'ev': e._fnum(r.get('ExitSpeed')), 'la': e._fnum(r.get('Angle')), 'bunt': r.get('HitType') == 'Bunt',
            'balls': r.get('Balls'), 'strikes': r.get('Strikes'), 'tags': e._tags(r)}


def _from_pitch(p):
    return {'outcome': p['outcome'], 'ev': p['ev'], 'la': p['la'], 'bunt': p.get('hit_type') == 'BUNT',
            'balls': p.get('balls'), 'strikes': p.get('strikes'), 'tags': set()}


def _calc(ps, tags_known):
    bb = sum(1 for p in ps if p['balls'] == '3' and p['outcome'] == 'ball')
    hbp = sum(1 for p in ps if p['outcome'] == 'hbp')
    ks = sum(1 for p in ps if p['strikes'] == '2' and p['outcome'] in ('whiff', 'cs'))
    vals = [batted_value(p['ev'], p['la']) for p in ps if p['outcome'] == 'inplay' and not p['bunt'] and p['ev'] is not None and p['la'] is not None]
    vals = [v for v in vals if v is not None]
    pa = len(vals) + ks + bb + hbp
    xw = (sum(vals) + W_BB * bb + W_HBP * hbp) / pa if pa else None
    out = {'pa': pa, 'xwoba': xw, 'bb': bb, 'hbp': hbp, 'k': ks}
    if tags_known:
        bip = [p for p in ps if p['outcome'] == 'inplay']
        tagged = [p for p in bip if any(t.startswith('PR_') for t in p['tags'])]
        hr = sum(1 for p in ps if 'PR_HomeRun' in p['tags'])
        outs = sum(1 for p in ps if 'PR_Out' in p['tags']) + ks
        ip = outs / 3
        cov = len(tagged) / len(bip) if bip else 0
        out.update(ip=ip, hr=hr, tag_cov=cov)
        out['fip'] = ((13 * hr + 3 * (bb + hbp) - 2 * ks) / ip + FIP_CONST) if ip > 0 else None
        out['xera'] = PA_PER_9 * ((xw - LG_WOBA) / WOBA_SCALE + LG_RUNS_PA) if xw is not None else None
    return out


@cache.memo
def table(program):
    """{'p': {pitcher slug: {...}}, 'h': {hitter key: {...}}}: every value, released or not."""
    res = {'p': {}, 'h': {}}
    for slug, bio, outs in team._pitchers(program):
        res['p'][slug] = _calc([_from_row(r) for o in outs for r in o['rows']], True)
    for key, h in hitting._collect(True).items():
        if h['program'] == program:
            res['h'][key] = _calc([_from_pitch(p) for p in h['pitches']], False)
    return res


def released(side, v):
    """The values of one player that clear the minimums (a dict of stat id -> number); {} when none do."""
    if not v:
        return {}
    out = {}
    if side == 'h':
        if v['xwoba'] is not None and v['pa'] >= MIN_PA_HITTER:
            out['xwoba'] = v['xwoba']
    else:
        if v['xwoba'] is not None and v['pa'] >= MIN_BF_PITCHER:
            out['xwoba'] = v['xwoba']
            if v.get('xera') is not None:
                out['xera'] = v['xera']
        if v.get('fip') is not None and v['ip'] >= MIN_IP_PITCHER and v['tag_cov'] >= MIN_TAG_COVERAGE:
            out['fip'] = v['fip']
    return out
