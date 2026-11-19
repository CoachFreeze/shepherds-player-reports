"""Wins above replacement for the spring season only: pWAR for our pitchers and oWAR for our hitters, from the games and scrimmages
played January 1 through June 30 of the season being viewed. Fall games, live at-bats and bullpens never count.

The method matches how the Northwest college stat sites figure WAR (rebuilt from their 2026 D1, D2, D3 and NAIA leaderboards: the
pitching side to five decimals, the hitting side to within about 0.03 WAR):

    pWAR = IP / 9 x [ (replacement FIP - FIP) / RUNS_PER_WIN + START_CREDIT x GS / G ]
    oWAR = [ (wOBA - league wOBA) / WOBA_SCALE x PA  +  position runs  +  replacement runs ] / RUNS_PER_WIN

League wOBA, the FIP constant and the league ERA come from runenv (the run environment measured from the tagged games in the app),
so the numbers follow our own league instead of theirs. Hitting with runners, steals and defense are not counted, the same as theirs.
"""
import datetime

import cache

RUNS_PER_WIN = 9.5
REPL_FIP_CUSHION = 0.20     # replacement FIP = league FIP + this (theirs sit 0.0 to 0.3 runs above their league ERA)
START_CREDIT = 0.010        # extra wins per 9 innings for a full-time starter, scaled by GS / G
WOBA_SCALE = 1.25           # their fitted scales run 1.15 (D1) to 1.29 (D3)
REPL_RUNS_600 = 20.0        # replacement runs per 600 plate appearances
POS_RUNS_600 = {            # position runs per 600 PA (their values, averaged over four levels; 3B = 0)
    'C': 5.0, 'SS': 4.0, '2B': 0.5, '3B': 0.0, 'CF': 0.0, 'IF': 1.0, 'UT': 0.0, 'OF': -3.0,
    'LF': -6.5, 'RF': -6.0, '1B': -9.0, 'DH': -11.5, 'P': -7.0,
}
MIN_TAG = 0.80              # share of balls in play that must carry a result (HR for FIP, hits for wOBA)
W = {'BB': 0.69, 'HBP': 0.72, '1B': 0.89, '2B': 1.27, '3B': 1.62, 'HR': 2.10}


def spring_window(win, today=None):
    """(first day, day after the last day) of the spring inside the season being viewed. A season that starts in the second half of a
    year (a custom fall-to-spring season) holds the next year's spring."""
    today = today or datetime.date.today()
    start = (win or (None, None))[0]
    if start:
        d = datetime.date.fromisoformat(str(start)[:10])
        yr = d.year + (1 if d.month >= 7 else 0)
    else:
        yr = today.year
    return f'{yr}-01-01', f'{yr}-07-01', yr


_POS_ALIAS = {'INF': 'IF', 'UTIL': 'UT', 'UTILITY': 'UT', 'UTL': 'UT', 'RHP': 'P', 'LHP': 'P', 'PITCHER': 'P', 'CATCHER': 'C', 'OUTFIELD': 'OF',
              'INFIELD': 'IF', 'DESIGNATED HITTER': 'DH'}


def _pos_key(pos):
    """The position his runs come from: the first fielding spot listed ('RHP/3B' -> 3B), P only for a pitcher with no other spot."""
    toks = [_POS_ALIAS.get(t.strip(), t.strip()) for t in (pos or '').upper().replace(',', '/').split('/') if t.strip()]
    toks = [t for t in toks if t in POS_RUNS_600]
    field = [t for t in toks if t != 'P']
    return field[0] if field else (toks[0] if toks else None)


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _pa_end(r):
    """How a plate appearance ended on this pitch, or None if it kept going: 'K', 'BB', 'HBP', a hit or out from the tagged result,
    or 'BIP' for an untagged ball in play."""
    import hitting
    if (r.get('KorBB') or '') == 'Strikeout':
        return 'K'
    if (r.get('KorBB') or '') == 'Walk':
        return 'BB'
    if (r.get('PitchCall') or '') == 'HitByPitch':
        return 'HBP'
    if (r.get('PitchCall') or '') == 'InPlay':
        res = hitting._play_result(r)
        return {'1B': '1B', '2B': '2B', '3B': '3B', 'HR': 'HR'}.get(res, 'OUT' if res else 'BIP')
    return None


@cache.memo
def table(program, win):
    """{'p': {pitcher slug: {...}}, 'h': {hitter key: {...}}, 'year', 'games'} for the spring inside `win` (season.window)."""
    import gamereport as gr
    import hitting
    import runenv
    import store
    lo, hi, yr = spring_window(win)
    env = runenv.environment()
    lg_fip = env['era']                          # runenv sets the FIP constant so the league FIP equals the league ERA
    games = {gid: gm for gid, gm in gr.collect(program).items() if lo <= gm['date'] < hi}
    demo = program in store.DEMO_PROGRAMS
    keys = {}                                    # batter name -> hitter key (our hitters)
    for k, h in hitting._collect(True).items():
        if h['program'] == program and h['demo'] == demo:
            keys.setdefault(h['name'], k)
    P, H = {}, {}
    for gid, gm in games.items():
        first = None
        for x in gm['rows']:
            r = x['r']
            o = (_i(r.get('Inning')), _i(r.get('PAofInning')), _i(r.get('PitchofPA')))
            if x['pit'] == 'us':
                if first is None or o < first[0]:
                    first = (o, x['slug'])
                p = P.setdefault(x['slug'], {'name': r.get('Pitcher') or '', 'g': set(), 'gs': 0, 'outs': 0, 'k': 0, 'bb': 0, 'hbp': 0, 'hr': 0, 'bip': 0, 'tag': 0})
                p['g'].add(gid)
                end = _pa_end(r)
                p['outs'] += _i(r.get('OutsOnPlay'))
                if end == 'K':
                    p['k'] += 1
                    p['outs'] += 0 if _i(r.get('OutsOnPlay')) else 1
                elif end in ('BB', 'HBP'):
                    p['bb' if end == 'BB' else 'hbp'] += 1
                elif end is not None:
                    p['bip'] += 1
                    p['tag'] += end != 'BIP'
                    p['hr'] += end == 'HR'
            else:
                end = _pa_end(r)
                if end is None:
                    continue
                key = keys.get(r.get('Batter') or '')
                if not key:
                    continue
                h = H.setdefault(key, {'name': r.get('Batter'), 'g': set(), 'pa': 0, 'bip': 0, 'tag': 0, **{k: 0 for k in W}, 'k': 0})
                h['g'].add(gid)
                h['pa'] += 1
                if end == 'K':
                    h['k'] += 1
                elif end in W:
                    h[end] += 1
                if end not in ('K', 'BB', 'HBP'):
                    h['bip'] += 1
                    h['tag'] += end != 'BIP'
        if first:
            P[first[1]]['gs'] += 1
    out = {'p': {}, 'h': {}, 'year': yr, 'games': len(games)}
    for slug, p in P.items():
        ip = p['outs'] / 3
        g = len(p['g'])
        cov = p['tag'] / p['bip'] if p['bip'] else 1.0
        v = {'g': g, 'gs': p['gs'], 'ip': ip, 'k': p['k'], 'bb': p['bb'], 'hbp': p['hbp'], 'hr': p['hr'], 'tag_cov': cov, 'fip': None, 'war': None}
        if ip > 0 and cov >= MIN_TAG:
            fip = (13 * p['hr'] + 3 * (p['bb'] + p['hbp']) - 2 * p['k']) / ip + env['fip_const']
            v['fip'] = fip
            v['war'] = ip / 9 * ((lg_fip + REPL_FIP_CUSHION - fip) / RUNS_PER_WIN + START_CREDIT * p['gs'] / g)
        out['p'][slug] = v
    bios = {**hitting._load_json(hitting._DEMO_BIOS_PATH), **hitting._load_json(hitting.HITTER_BIOS_PATH)}
    for key, h in H.items():
        cov = h['tag'] / h['bip'] if h['bip'] else 1.0
        pos = _pos_key((bios.get(key) or {}).get('position'))
        v = {'g': len(h['g']), 'pa': h['pa'], 'pos': pos, 'tag_cov': cov, 'woba': None, 'war': None}
        if h['pa'] and cov >= MIN_TAG:
            known = h['pa'] - (h['bip'] - h['tag'])                    # untagged balls in play are left out of the rate
            woba = sum(W[k] * h[k] for k in W) / known if known else None
            if woba is not None:
                runs = ((woba - env['lg_woba_real']) / WOBA_SCALE * h['pa'] + POS_RUNS_600.get(pos or '3B', 0.0) * h['pa'] / 600
                        + REPL_RUNS_600 * h['pa'] / 600)
                v.update(woba=woba, war=runs / RUNS_PER_WIN)
        out['h'][key] = v
    return out


def for_program(program):
    """table() for the season the viewer has picked."""
    import season
    return table(program, tuple(season.window(program) or (None, None)))


def label(v, side):
    """'1.8 WAR · 12 G, 9 GS, 54.1 IP, 3.92 FIP' style summary, or None."""
    if not v or v.get('war') is None:
        return None
    if side == 'p':
        ip = v['ip']
        ip_s = f"{int(ip)}.{round((ip - int(ip)) * 3)}"
        return f"{v['g']} G, {v['gs']} GS, {ip_s} IP, {v['fip']:.2f} FIP"
    return f"{v['g']} G, {v['pa']} PA, {v['woba']:.3f} wOBA".replace(' 0.', ' .') + (f", {v['pos']}" if v.get('pos') else '')
