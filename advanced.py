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

# ---- constants (wOBA weights are MLB's; the run environment and FIP constant come from runenv, fitted to our own tagged games)
W_BB, W_HBP, W_1B, W_XBH, W_HR = 0.69, 0.72, 0.89, 1.30, 2.10    # wOBA weights; W_XBH blends doubles and triples
FIP_CONST = 3.10
LG_WOBA, WOBA_SCALE, LG_RUNS_PA, PA_PER_9 = 0.315, 1.20, 0.115, 38.0


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _split(ev, la):
    """(single, double-or-triple, home run) chances of a ball in play. The hit chance comes from the calibrated hit model; how it splits
    into bases was tuned on the tagged college batted balls in the app (Nov 2026: 446 balls), where the old MLB-style split
    left expected total bases 22% short."""
    ph = hitting.hit_prob(ev, la)
    if ph is None:
        return None
    hr = min(0.9 * ph, _sig((ev - 97) / 2.5) * _sig((la - 23) / 2) * _sig((40 - la) / 2))
    if 8 <= la <= 40:
        share = min(0.8, 0.15 + 0.02 * max(0, ev - 80))
    else:
        share = 0.14 if (0 <= la < 8 and ev >= 95) else 0.04           # a hard low liner still finds a gap or a line
    xbh = (ph - hr) * share
    return ph - hr - xbh, xbh, hr


def batted_value(ev, la):
    """Expected wOBA value of a ball in play at this exit velocity / launch angle."""
    sp = _split(ev, la)
    return None if sp is None else sp[0] * W_1B + sp[1] * W_XBH + sp[2] * W_HR


def expected_bases(ev, la):
    """Expected total bases of a ball in play (the same model as xBA and xwOBA)."""
    sp = _split(ev, la)
    return None if sp is None else sp[0] + sp[1] * 2.1 + sp[2] * 4


def _int(x):
    try:
        return int(float(x or 0))
    except (TypeError, ValueError):
        return 0


def _from_row(r):
    """A raw pitcher-side CSV row as the small dict the calculations use."""
    import pitchfx
    return {'outcome': e._outcome(r), 'ev': e._fnum(r.get('ExitSpeed')), 'la': e._fnum(r.get('Angle')), 'bunt': r.get('HitType') == 'Bunt',
            'balls': r.get('Balls'), 'strikes': r.get('Strikes'), 'result': hitting._play_result(r), 'runs': _int(r.get('RunsScored')),
            'outs_play': _int(r.get('OutsOnPlay')), 'ptype': pitchfx._label(r), 'raw': r}


def _from_pitch(p):
    return {'outcome': p['outcome'], 'ev': p['ev'], 'la': p['la'], 'bunt': p.get('hit_type') == 'BUNT',
            'balls': p.get('balls'), 'strikes': p.get('strikes'), 'result': p.get('result'), 'runs': 0, 'outs_play': 0,
            'ptype': p.get('pitch') or p.get('type'), 'raw': None}


W_2B, W_3B = 1.27, 1.62
SPLITS = ('ahead', 'even', 'behind')


def _split_of(p):
    """Who is ahead when the plate appearance ends, from the pitcher's side."""
    try:
        b, s_ = int(p['balls']), int(p['strikes'])
    except (TypeError, ValueError):
        return None
    return 'ahead' if s_ > b else ('behind' if b > s_ else 'even')


def _calc(ps, pitcher):
    """Every value for one player, released or not. pitcher=True adds the innings-based stats."""
    import grades
    import runenv
    env = runenv.environment()
    bb = sum(1 for p in ps if p['balls'] == '3' and p['outcome'] == 'ball')
    hbp = sum(1 for p in ps if p['outcome'] == 'hbp')
    ks = sum(1 for p in ps if p['strikes'] == '2' and p['outcome'] in ('whiff', 'cs'))
    tracked = [p for p in ps if p['outcome'] == 'inplay' and not p['bunt'] and p['ev'] is not None and p['la'] is not None]
    vals = [v for v in (batted_value(p['ev'], p['la']) for p in tracked) if v is not None]
    pa = len(vals) + ks + bb + hbp
    xw = (sum(vals) + W_BB * bb + W_HBP * hbp) / pa if pa else None
    out = {'pa': pa, 'xwoba': xw, 'bb': bb, 'hbp': hbp, 'k': ks}
    # ---- expected power (no tagging needed)
    xab = len(vals) + ks
    if xab:
        xtb = sum(expected_bases(p['ev'], p['la']) or 0 for p in tracked)
        xh = sum(hitting.hit_prob(p['ev'], p['la']) or 0 for p in tracked)
        out.update(xab=xab, xslg=xtb / xab, xiso=(xtb - xh) / xab)
    # ---- how the plate appearance ended, by who was ahead (expected, so no tagging needed)
    sp = {k: [0.0, 0] for k in SPLITS}
    for p in ps:
        k = _split_of(p)
        if k is None:
            continue
        if p['outcome'] == 'inplay' and not p['bunt'] and p['ev'] is not None and p['la'] is not None:
            v = batted_value(p['ev'], p['la'])
        elif p['outcome'] == 'hbp':
            v = W_HBP
        elif p['balls'] == '3' and p['outcome'] == 'ball':
            v = W_BB
        elif p['strikes'] == '2' and p['outcome'] in ('whiff', 'cs'):
            v = 0.0
        else:
            continue
        if v is not None:
            sp[k][0] += v
            sp[k][1] += 1
    out['splits'] = {k: {'pa': n, 'xwoba': (t / n if n else None)} for k, (t, n) in sp.items()}
    # ---- run value by pitch type (runs to the hitter per 100 pitches; contact valued by exit velocity / launch angle)
    rv = {}
    for p in ps:
        if not p.get('ptype'):
            continue
        v = grades._pitch_rv(p['raw'], env) if p.get('raw') is not None else _rv_pitch(p, env)
        if v is None:
            continue
        a = rv.setdefault(p['ptype'], [0.0, 0])
        a[0] += v
        a[1] += 1
    out['rv'] = {k: {'n': n, 'rv100': 100 * t / n} for k, (t, n) in rv.items() if n}
    # ---- results-based stats: need the balls in play tagged with how they ended
    bip = [p for p in ps if p['outcome'] == 'inplay']
    tagged = [p for p in bip if p['result']]
    cov = len(tagged) / len(bip) if bip else 0.0
    cnt = {k: sum(1 for p in tagged if p['result'] == k) for k in ('1B', '2B', '3B', 'HR', 'SAC')}
    hits = cnt['1B'] + cnt['2B'] + cnt['3B'] + cnt['HR']
    ab = len(tagged) - cnt['SAC'] + ks
    rpa = len(tagged) + ks + bb + hbp
    out.update(tag_cov=cov, tagged=len(tagged), ab=ab, hits=hits, hr=cnt['HR'], rpa=rpa)
    if ab > 0 and rpa > 0:
        tb = cnt['1B'] + 2 * cnt['2B'] + 3 * cnt['3B'] + 4 * cnt['HR']
        woba = (W_BB * bb + W_HBP * hbp + W_1B * cnt['1B'] + W_2B * cnt['2B'] + W_3B * cnt['3B'] + W_HR * cnt['HR']) / rpa
        den = ab - ks - cnt['HR']
        out.update(avg=hits / ab, slg=tb / ab, iso=(tb - hits) / ab, babip=((hits - cnt['HR']) / den if den > 0 else None), woba=woba,
                   wrc_plus=100 * ((woba - env['lg_woba_real']) / WOBA_SCALE + env['runs_all_pa']) / env['runs_all_pa'],
                   luck=(woba - xw) if xw is not None else None)
    if pitcher:
        outs = sum(p['outs_play'] for p in ps) + ks
        if not any(p['outs_play'] for p in ps):          # older files without OutsOnPlay: count tagged outs
            outs = sum(1 for p in tagged if p['result'] in ('OUT', 'FC', 'SAC')) + ks
        ip = outs / 3
        runs = sum(p['runs'] for p in ps)
        out.update(ip=ip, runs=runs)
        out['fip'] = ((13 * cnt['HR'] + 3 * (bb + hbp) - 2 * ks) / ip + env['fip_const']) if ip > 0 else None
        out['xera'] = max(0.0, env['pa9'] * ((xw - env['lg_woba']) / WOBA_SCALE + env['runs_pa'])) if xw is not None else None
        base = hits + bb + hbp - 1.4 * cnt['HR']
        out['lob'] = max(0.0, min(1.0, (hits + bb + hbp - runs) / base)) if base > 0 else None
    return out


def _rv_pitch(p, env):
    """grades._pitch_rv for the hitter-side pitch dict."""
    import grades
    oc, b, s_ = p['outcome'], p['balls'], p['strikes']
    if oc == 'ball':
        return grades.RV_WALK if b == '3' else grades.RV_BALL
    if oc == 'hbp':
        return grades.RV_WALK
    if oc in ('cs', 'whiff'):
        return grades.RV_K if s_ == '2' else grades.RV_STRIKE
    if oc == 'foul':
        return 0.0 if s_ == '2' else grades.RV_STRIKE
    if oc == 'inplay':
        v = batted_value(p['ev'], p['la'])
        return None if v is None else (v - env['lg_woba']) / WOBA_SCALE
    return None


MIN_SPLIT_PA = 40           # batters in one count split before it shows
MIN_RV_PITCHES = 100        # pitches of one type before its run value shows


@cache.memo
def table(program):
    """{'p': {pitcher slug: {...}}, 'h': {hitter key: {...}}}: every value, released or not."""
    import grades
    res = {'p': {}, 'h': {}}
    for slug, bio, outs in team._pitchers(program):
        rows = [r for o in outs for r in o['rows']]
        v = _calc([_from_row(r) for r in rows], True)
        try:
            v.update(pitch_grades(rows, bio))
        except Exception:
            pass
        res['p'][slug] = v
    for key, h in hitting._collect(True).items():
        if h['program'] == program:
            res['h'][key] = _calc([_from_pitch(p) for p in h['pitches']], False)
    return res


def pitch_grades(rows, bio):
    """Stuff+ and Location+ for one pitcher's rows: {'stuff', 'stuff_by', 'loc', 'loc_by', 'loc_n'}."""
    import grades
    import pitchfx
    name = bio.get('name') or ''
    meta, tm = e.pitcher_trackman_summary(rows, name)
    slot = e.arm_slot_stats(meta.get('release'), bio.get('height_in'))
    ars = [{'type': t['type'], 'pct': t['pct'], 'velo': t['velo'], 'spin': t.get('spin_avg'), 'hb': t['hb'], 'ivb': t['ivb'], 'n': t.get('n')}
           for t in tm if t.get('hb') is not None and t.get('ivb') is not None]
    st = grades.stuff(ars, meta.get('throws') or 'R', slot['angle'] if slot else None) if ars else {'by_type': {}, 'overall': None}
    loc = grades.location(rows, pitchfx._label)
    return {'stuff': st['overall'], 'stuff_by': st['by_type'], 'loc': loc['overall'], 'loc_by': loc['by_type'], 'loc_n': loc['n']}


def released(side, v):
    """The values of one player that clear the minimums (a dict of stat id -> number); {} when none do."""
    if not v:
        return {}
    out = {}
    need = MIN_PA_HITTER if side == 'h' else MIN_BF_PITCHER
    if v.get('xwoba') is not None and v['pa'] >= need:
        out['xwoba'] = v['xwoba']
        for k in ('xslg', 'xiso'):
            if v.get(k) is not None:
                out[k] = v[k]
        if side == 'p' and v.get('xera') is not None:
            out['xera'] = v['xera']
    if v.get('woba') is not None and v.get('rpa', 0) >= need and v.get('tag_cov', 0) >= MIN_TAG_COVERAGE:      # results-based: need the games tagged
        for k in ('woba', 'iso', 'babip', 'luck') + (('wrc_plus',) if side == 'h' else ()):
            if v.get(k) is not None:
                out[k] = v[k]
    if side == 'p':
        if v.get('ip', 0) >= MIN_IP_PITCHER and v.get('tag_cov', 0) >= MIN_TAG_COVERAGE:
            for k in ('fip', 'lob'):
                if v.get(k) is not None:
                    out[k] = v[k]
        for k in ('stuff', 'loc'):                     # shape and location grades carry their own minimums (grades.py)
            if v.get(k) is not None:
                out[k] = v[k]
    return out


def released_detail(side, v):
    """The per-pitch and per-count pieces that clear their minimums: {'splits': {...}, 'rv': {...}}."""
    if not v:
        return {'splits': {}, 'rv': {}}
    sp = {k: d for k, d in (v.get('splits') or {}).items() if d['pa'] >= MIN_SPLIT_PA and d['xwoba'] is not None}
    return {'splits': sp if len(sp) >= 2 else {}, 'rv': {k: d for k, d in (v.get('rv') or {}).items() if d['n'] >= MIN_RV_PITCHES}}
