"""College calibration for the expected stats, learned from the tagged games stored in the app (all programs pooled, demo data left out).

1. Hit model. The exit-velocity / launch-angle table is built from MLB results, where fielders turn more weak contact into outs.
   calibration() fits  logit(college hit chance) = a + b * logit(MLB hit chance)  on every tracked ball in play with a tagged result,
   pulled toward "no change" (a=0, b=1) by PRIOR_BALLS so a small sample can't swing it. hitting.hit_prob applies it.
2. Run environment. environment() measures, from the fully tagged games, runs per batter and batters per nine innings, blended with a
   college prior (PRIOR_PA batters' worth), plus the league xwOBA from the same calibrated model, so an average pitcher's xERA comes out
   at the league's ERA. The FIP constant follows from the same numbers.

Both refit on their own whenever stored data changes. Nothing is fitted until MIN_BALLS / MIN_PA is reached; before that the MLB
figures are used unchanged."""
import math
import os
import time

import cache
import extract as e
import outings as outings_mod

HITS = {'Single', 'Double', 'Triple', 'HomeRun'}
MIN_BALLS = 150            # tagged + tracked balls in play before the hit model is recalibrated at all
PRIOR_BALLS = 40           # strength of the pull toward the unchanged MLB table
MIN_PA = 300               # batters in fully tagged games before the run environment uses our own data
PRIOR_PA = 600             # the college prior counts as this many batters
PRIOR_ERA_PA = 0.150       # prior earned runs per batter (about a 5.9 ERA)
PRIOR_PA9 = 39.5           # prior batters per nine innings
EARNED_SHARE = 0.90        # the files carry runs, not earned runs
FULL_TAG = 0.90            # a game counts as fully tagged when this share of its balls in play carry a result
MLB = {'lg_woba': 0.315, 'runs_pa': 0.115, 'pa9': 38.0, 'fip_const': 3.10, 'era': 4.37, 'source': 'mlb', 'pa': 0}
W_BB, W_HBP = 0.69, 0.72

_S = {'ver': object(), 't': 0.0, 'cal': (0.0, 1.0, 0), 'env': None}


def _logit(p):
    p = min(max(p, 0.005), 0.995)
    return math.log(p / (1 - p))


def _rows():
    """Every stored real pitch once (a game uploaded for both the pitcher and the scouting side is the same pitch)."""
    seen, out = set(), []
    d = outings_mod.OUTINGS_DIR
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith('.json'):
            continue
        for o in outings_mod.load(f[:-5], real_only=True).get('outings') or []:
            for r in o.get('rows') or []:
                uid = r.get('PitchUID') or (o.get('date'), r.get('Pitcher'), r.get('Batter'), r.get('Inning'), r.get('PAofInning'), r.get('PitchofPA'))
                if uid in seen:
                    continue
                seen.add(uid)
                out.append((o.get('date'), r))
    return out


def _tagged(r):
    return r.get('PlayResult') not in (None, '', 'Undefined')


def _fit(data, lam):
    a, b = 0.0, 1.0
    for _ in range(40):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in data:
            q = 1 / (1 + math.exp(-(a + b * x)))
            w = q * (1 - q)
            g0 += q - y
            g1 += (q - y) * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        g0 += lam * a
        g1 += lam * (b - 1)
        h00 += lam
        h11 += lam
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        a -= (h11 * g0 - h01 * g1) / det
        b -= (h00 * g1 - h01 * g0) / det
    return a, b


def _compute():
    import hitting
    rows = _rows()
    # ---- 1. hit model
    data = []
    for _d, r in rows:
        if e._outcome(r) != 'inplay' or r.get('HitType') == 'Bunt' or not _tagged(r):
            continue
        p = hitting.hit_prob_mlb(e._fnum(r.get('ExitSpeed')), e._fnum(r.get('Angle')))
        if p is not None:
            data.append((_logit(p), 1.0 if r['PlayResult'] in HITS else 0.0))
    cal = (0.0, 1.0, len(data))
    if len(data) >= MIN_BALLS:
        try:
            a, b = _fit(data, PRIOR_BALLS)
            if -1.5 < a < 1.5 and 0.3 < b < 1.7:
                cal = (a, b, len(data))
        except (OverflowError, ZeroDivisionError):
            pass
    _S['cal'] = cal                                   # the league xwOBA below must use the calibrated model
    # ---- 2. run environment
    import advanced
    games = {}
    for d, r in rows:
        if e._outcome(r) == 'inplay':
            g = games.setdefault((d, r.get('SessionType')), [0, 0])
            g[0] += 1
            g[1] += _tagged(r)
    full = {k for k, (n, t) in games.items() if n >= 5 and t / n >= FULL_TAG}
    pa = runs = outs = bb = hbp = ks = hr = 0
    for d, r in rows:
        if (d, r.get('SessionType')) not in full:
            continue
        oc = e._outcome(r)
        if oc == 'inplay':
            pa += 1
            hr += r.get('PlayResult') == 'HomeRun'
        elif oc == 'hbp':
            pa += 1
            hbp += 1
        elif r.get('KorBB') == 'Strikeout' or (r.get('Strikes') == '2' and oc in ('whiff', 'cs')):
            pa += 1
            ks += 1
            outs += 1
        elif r.get('KorBB') == 'Walk' or (r.get('Balls') == '3' and oc == 'ball'):
            pa += 1
            bb += 1
        try:
            runs += int(float(r.get('RunsScored') or 0))
            outs += int(float(r.get('OutsOnPlay') or 0))
        except (TypeError, ValueError):
            pass
    env = dict(MLB)
    if pa >= MIN_PA and outs >= 90:
        runs_pa = (runs * EARNED_SHARE + PRIOR_ERA_PA * PRIOR_PA) / (pa + PRIOR_PA)
        pa9 = (pa + PRIOR_PA) / ((outs / 27) + PRIOR_PA / PRIOR_PA9)
        xw = advanced._calc([advanced._from_row(r) for _d, r in rows], False)
        era = runs_pa * pa9
        ip = outs / 3
        core = ((13 * hr + 3 * (bb + hbp) - 2 * ks) + 1.27 * 100) / (ip + 100)     # FIP's HR / BB / K part, pulled toward the MLB level over 100 innings
        if xw.get('xwoba') is not None and xw['pa'] >= MIN_PA:
            env = {'lg_woba': xw['xwoba'], 'runs_pa': runs_pa, 'pa9': pa9, 'era': era, 'fip_const': era - core, 'source': 'own', 'pa': pa}
    _S['env'] = env


def _fresh():
    if _S.get('busy'):
        return
    ver = cache._STATE.get('ver')
    now = time.time()
    if _S['env'] is not None and ver == _S['ver'] and (ver is not None or now - _S['t'] < 60):
        return
    if ver is None and _S['env'] is not None and cache.data_version() == _S.get('dv'):
        _S['t'] = now
        return
    _S['ver'], _S['t'], _S['dv'] = ver, now, cache.data_version()
    if _S.get('busy'):
        return
    _S['busy'] = True
    try:
        _S['cal'] = (0.0, 1.0, 0)
        _compute()
    except Exception:
        if _S['env'] is None:
            _S['env'] = dict(MLB)
    finally:
        _S['busy'] = False


def calibration():
    """(a, b, balls used). (0, 1, n) = the MLB table unchanged."""
    _fresh()
    return _S['cal']


def environment():
    _fresh()
    return _S['env'] or dict(MLB)


def adjust(p):
    """A hit chance from the MLB table, as a college hit chance."""
    if _S['env'] is None or _S['ver'] != cache._STATE.get('ver') or cache._STATE.get('ver') is None:
        _fresh()
    a, b, _n = _S['cal']
    if a == 0.0 and b == 1.0:
        return p
    return 1 / (1 + math.exp(-(a + b * _logit(p))))
